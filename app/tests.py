"""
Script autonome : demande à Gemini d'analyser un fichier.

Usage:
    export GEMINI_API_KEY="votre_clé_api"
    python analyze_file_with_gemini.py chemin/vers/fichier.txt
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from google import genai
from google.genai import errors, types

MODEL = "gemini-2.5-flash"
MAX_RETRIES = 3
POLL_INTERVAL_SECONDS = 1.0
POLL_TIMEOUT_SECONDS = 60.0


async def upload_and_wait_active(client: genai.Client, file_path: Path) -> types.File:
    """Upload un fichier vers Gemini et attend qu'il soit ACTIVE avant de le réutiliser."""
    uploaded_file = await client.aio.files.upload(file=file_path)
    print(f">> Upload lancé: {uploaded_file.name} "
          f"(mime={uploaded_file.mime_type}, size={uploaded_file.size_bytes})")

    elapsed = 0.0
    while uploaded_file.state == types.FileState.PROCESSING:
        if elapsed >= POLL_TIMEOUT_SECONDS:
            raise TimeoutError(
                f"Le fichier {file_path} est resté en PROCESSING "
                f"plus de {POLL_TIMEOUT_SECONDS}s."
            )
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS
        uploaded_file = await client.aio.files.get(name=uploaded_file.name)
        print(f"   ... état actuel: {uploaded_file.state.name}")

    if uploaded_file.state == types.FileState.FAILED:
        detail = getattr(uploaded_file, "error", None)
        raise RuntimeError(f"Le traitement du fichier {file_path} a échoué: {detail}")

    if uploaded_file.state != types.FileState.ACTIVE:
        raise RuntimeError(
            f"État inattendu pour {file_path}: {uploaded_file.state.name}"
        )

    print(f">> Fichier prêt (ACTIVE): {uploaded_file.name}")
    return uploaded_file


async def send_with_retry(chat, contents, max_retries: int = MAX_RETRIES):
    """Envoie le message avec retry/backoff sur les erreurs serveur (5xx) transitoires."""
    for attempt in range(1, max_retries + 1):
        try:
            return await chat.send_message(contents)
        except errors.ServerError as exc:
            if attempt == max_retries:
                raise
            wait = 2 ** attempt
            print(f">> Erreur serveur ({exc}). Nouvelle tentative dans {wait}s "
                  f"({attempt}/{max_retries})...")
            await asyncio.sleep(wait)


async def analyze_file(file_path: Path, prompt: str) -> str:
    api_key = "AIzaSyB4WGkKltXQcpx5u1yjOrK3mKheXN3vCW8"
    if not api_key:
        raise RuntimeError(
            "Variable d'environnement GEMINI_API_KEY manquante. "
            "Faites: export GEMINI_API_KEY='votre_clé'"
        )

    if not file_path.exists():
        raise FileNotFoundError(f"Fichier introuvable: {file_path}")
    if file_path.stat().st_size == 0:
        raise ValueError(f"Le fichier {file_path} est vide.")

    client = genai.Client(api_key=api_key)

    uploaded_file = await upload_and_wait_active(client, file_path)

    chat = client.aio.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            temperature=0,
            system_instruction="Tu es un assistant qui analyse des documents avec précision.",
        ),
    )

    response = await send_with_retry(chat, [prompt, uploaded_file])

    if not response or not response.candidates:
        raise RuntimeError("Gemini n'a retourné aucun contenu.")

    text = response.candidates[0].content.parts[0].text
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse un fichier avec Gemini.")
    parser.add_argument("file", type=Path, help="Chemin vers le fichier à analyser")
    parser.add_argument(
        "--prompt",
        type=str,
        default="Analyse ce document et résume son contenu.",
        help="Instruction envoyée à Gemini",
    )
    args = parser.parse_args()

    try:
        result = asyncio.run(analyze_file(args.file, args.prompt))
    except Exception as exc:
        print(f"\n[ERREUR] {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)

    print("\n=== Réponse de Gemini ===")
    print(result)


if __name__ == "__main__":
    main()