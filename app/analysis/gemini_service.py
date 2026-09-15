"""
Logique d'appel à Gemini : upload de fichiers, attente de l'état ACTIVE,
puis envoi du message avec retry sur les erreurs serveur transitoires.
"""
import json
import re
import asyncio
from pathlib import Path

from google import genai
from google.genai import errors, types

MAX_RETRIES = 3
POLL_INTERVAL_SECONDS = 1.0
POLL_TIMEOUT_SECONDS = 60.0


class GeminiFileError(Exception):
    """Le traitement d'un fichier par Gemini a échoué (état FAILED, timeout...)."""


class GeminiUpstreamError(Exception):
    """Gemini renvoie une erreur serveur persistante après épuisement des retries."""


class GeminiSafetyBlockedError(Exception):
    """
    Gemini a bloqué la requête ou la génération pour des raisons de contenu
    (sécurité, PII sensible, contenu prohibé...), avant ou pendant la
    génération. Contrairement à GeminiUpstreamError, réessayer ne change rien:
    c'est le contenu du document qui pose problème, pas un incident serveur.
    """


async def upload_and_wait_active(client: genai.Client, file_path: Path) -> types.File:
    """Upload un fichier vers Gemini et attend qu'il soit ACTIVE avant réutilisation."""
    uploaded_file = await client.aio.files.upload(file=file_path)

    elapsed = 0.0
    while uploaded_file.state == types.FileState.PROCESSING:
        if elapsed >= POLL_TIMEOUT_SECONDS:
            raise GeminiFileError(
                f"Le fichier {file_path.name} est resté en PROCESSING trop longtemps."
            )
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS
        uploaded_file = await client.aio.files.get(name=uploaded_file.name)

    if uploaded_file.state == types.FileState.FAILED:
        raise GeminiFileError(
            f"Le traitement du fichier {file_path.name} a échoué côté Gemini."
        )
    if uploaded_file.state != types.FileState.ACTIVE:
        raise GeminiFileError(
            f"État inattendu pour {file_path.name}: {uploaded_file.state.name}"
        )

    return uploaded_file


async def send_with_retry(chat, contents, max_retries: int = MAX_RETRIES):
    """Envoie le message avec retry/backoff exponentiel sur les erreurs serveur (5xx)."""
    last_exc: errors.ServerError | None = None
    for attempt in range(1, max_retries + 1):
        try:
            print(f"-->> Attempt {attempt} to send message to Gemini...")
            return await chat.send_message(contents)
        except errors.ServerError as exc:
            last_exc = exc
            print(f"\t-->> Gemini server error on attempt {attempt}: {exc}. Retrying...")
            if attempt == max_retries:
                break
            # await asyncio.sleep(2 ** attempt)
    raise GeminiUpstreamError(
        f"Gemini a renvoyé une erreur serveur après {max_retries} tentatives: {last_exc}"
    ) from last_exc


def _read_reference_text(path: Path) -> str:
    """Lit un fichier de référence (schema.json, dictionnaire.txt...) comme texte brut."""
    return path.read_text(encoding="utf-8")


def parse_txt_to_json(raw_text: str) -> dict:
    """Parse la réponse de Gemini en dict, même si elle est entourée de ```json ... ```."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", raw_text.strip())
    return json.loads(cleaned)


async def analyze_documents(
    client: genai.Client,
    model: str,
    document_paths: list[Path],
    prompt: str,
    reference_files: list[Path] | None = None,
    system_instruction: str | None = None,
) -> dict:
    """
    Upload une liste de documents vers Gemini (via le File API, avec polling
    ACTIVE) puis demande une analyse. Retourne le texte brut de la réponse
    (à parser en JSON par l'appelant si besoin).

    `document_paths` : fichiers à envoyer via le File API (PDF, image, fichier
        utilisateur réel...). C'est le seul cas où le File API a un intérêt
        (OCR/vision, gros fichiers, réutilisation entre requêtes).

    `reference_files` : fichiers de référence statiques que TU contrôles
        (schema.json, dictionnaire.txt...). Ils sont lus et injectés comme
        texte brut dans le message, PAS envoyés via le File API.
        Important: le File API de Gemini ne supporte pas correctement les
        fichiers .json (erreur 500 documentée côté Google) - les données
        structurées de référence doivent donc toujours être inlinées ainsi,
        jamais uploadées comme "document".
    """
    if not document_paths and not reference_files:
        raise ValueError("Aucun document ni fichier de référence fourni pour l'analyse.")

    contents: list = []
    for ref_path in reference_files or []:
        try:
            ref_text = _read_reference_text(ref_path)
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"Le fichier de référence {ref_path.name} n'est pas du texte UTF-8 valide."
            ) from exc
        contents.append(f"--- Contenu de référence ({ref_path.name}) ---\n{ref_text}")

    contents.append(prompt)

    for path in document_paths:
        uploaded_file = await upload_and_wait_active(client, path)
        contents.append(uploaded_file)

    chat = client.aio.chats.create(
        model=model,
        config=types.GenerateContentConfig(
            temperature=0,
            system_instruction=system_instruction,
        ),
    )

    print("-->> Chat created !!")
    response = await send_with_retry(chat, contents)
    print("-->> Response received !!")
    # 1. Bloqué avant même la génération (ex: le contenu du PDF déclenche
    #    un classifieur de sécurité côté Gemini sur la requête entière).
    feedback = getattr(response, "prompt_feedback", None)
    block_reason = getattr(feedback, "block_reason", None)
    if block_reason is not None and block_reason.name != "BLOCKED_REASON_UNSPECIFIED":
        raise GeminiSafetyBlockedError(
            f"Requête bloquée par Gemini avant génération "
            f"(block_reason={block_reason.name}): "
            f"{getattr(feedback, 'block_reason_message', None)}"
        )

    if not response.candidates:
        raise GeminiUpstreamError("Gemini n'a retourné aucun candidat (réponse vide).")

    candidate = response.candidates[0]

    # 2. Génération interrompue en cours de route (SAFETY, SPII,
    #    PROHIBITED_CONTENT, IMAGE_SAFETY... fréquent sur des PDF scannés
    #    contenant des données personnelles/financières, alors que le même
    #    contenu envoyé en texte brut ne passe pas par le classifieur vision).
    finish_reason = getattr(candidate, "finish_reason", None)
    if finish_reason is not None and finish_reason.name not in (
        "STOP",
        "MAX_TOKENS",
        "FINISH_REASON_UNSPECIFIED",
    ):
        raise GeminiSafetyBlockedError(
            f"Génération interrompue par Gemini (finish_reason={finish_reason.name}). "
            f"safety_ratings={getattr(candidate, 'safety_ratings', None)}"
        )

    if not candidate.content or not candidate.content.parts:
        raise GeminiUpstreamError("Gemini a retourné une réponse sans contenu exploitable.")

    return parse_txt_to_json(candidate.content.parts[0].text)


async def get_interpretation(client: genai.Client, model: str, system_instruction: str, prompt: str) -> str:

    chat = client.aio.chats.create(
        model=model,
        config=types.GenerateContentConfig(
            temperature=0,
            system_instruction=system_instruction,
        ),
    )

    contents = [prompt]
    response = await send_with_retry(chat, contents)

    return response.candidates[0].content.parts[0].text


async def send_message(client: genai.Client, model: str, system_instruction: str, prompt: str) -> str:
    """
    Envoie un prompt à Gemini et retourne la réponse brute.
    """
    chat = client.aio.chats.create(
        model=model,
        config=types.GenerateContentConfig(
            temperature=0,
            system_instruction=system_instruction,
        ),
    )

    contents = [prompt]
    response = await send_with_retry(chat, contents)
    return response.candidates[0].content.parts[0].text