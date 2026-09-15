"""
    Endpoint FastAPI : reçoit un ou plusieurs fichiers + un prompt,
    les fait analyser par Gemini, et retourne le résultat.
"""

import json
import os
import tempfile
from urllib import response
import uuid
from pathlib import Path
from typing import Any
from xmlrpc import client

from fastapi import APIRouter, File, Form, Depends, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from google import genai
from pydantic import BaseModel

from app.analysis.gemini_service import (
    GeminiFileError,
    GeminiSafetyBlockedError,
    GeminiUpstreamError,
    analyze_documents,
    _read_reference_text,
    get_interpretation,
    parse_txt_to_json,
    send_message
)

from app.analysis.configs import UPLOAD_DIR, SCHEMA_PATH, DICTIONARY_PATH, INITIAL_PROMPT_PATH, UPDATE_PROMPT_PATH, SYSTEM_INSTRUCTIONS_PATH, llm
from app.analysis.calculs import compute_analysis


router = APIRouter()

model, api_key = llm.get_model_name(), llm.get_api_key()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Fichiers de référence STATIQUES (schema, dictionnaire...) que tu contrôles.
# Ils sont injectés comme texte brut (jamais via le File API - le File API
# de Gemini ne supporte pas correctement le JSON, cf. gemini_service.py).
# Décommente et adapte les chemins selon ton projet:
# SCHEMA_PATH = Path("/chemin/vers/schema.json")
# DICTIONARY_PATH = Path("/chemin/vers/dictionnaire.txt")

_client: genai.Client | None = None

interpretation_prompt = """
    Voici les indicateurs calculés pour le dossier de "{company_name}" 
    (montant demandé: {requested_amount} {currency}):{calculations_json}
    Produis ton interprétation de ce dossier selon les règles et le format définis dans tes instructions.
"""

def get_client() -> genai.Client:
    """Client Gemini paresseux, réutilisé entre les requêtes."""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=500,
                detail="GEMINI_API_KEY n'est pas configurée côté serveur.",
            )
        _client = genai.Client(api_key=api_key)
    return _client


async def _save_upload(uploaded_file: UploadFile, destination_dir: Path) -> Path:
    """Sauvegarde un UploadFile sur disque en streaming (chunks de 1 Mo)."""
    safe_name = f"{uuid.uuid4().hex}_{uploaded_file.filename}"
    file_path = destination_dir / safe_name
    with open(file_path, "wb") as buffer:
        while chunk := await uploaded_file.read(1024 * 1024):
            buffer.write(chunk)
    return file_path


def parse_json_form(data: str = Form(..., description="Chaîne JSON envoyée via FormData")) -> dict[str, Any]:
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le champ 'data' doit être une chaîne JSON valide."
        )
    
@router.post("/analyze")
async def analyze_endpoint(
    data: dict[str, Any] = Depends(parse_json_form),
    files: list[UploadFile] = File(...),
):
    """Reçoit un ou plusieurs fichiers, les envoie à Gemini, retourne l'analyse."""

    mfi_name = data['mfi_name']
    user_prompt = data["user_prompt"]
    if bool(data.get("credit_analysis", False)):
        if bool(data['is_update']) is True:
            prompt = _read_reference_text(UPDATE_PROMPT_PATH)
            company_data_path = UPLOAD_DIR / mfi_name / f"{data['company_name']}_credit_request.json"
            reference_files = [company_data_path, DICTIONARY_PATH]
            print("\n\n ----> It is a update case")
        else:
            if not files:
                raise HTTPException(status_code=400, detail="RequireFileError")
            prompt = _read_reference_text(INITIAL_PROMPT_PATH)
            reference_files = [SCHEMA_PATH, DICTIONARY_PATH]

        saved_paths: list[Path] = []
        try: 
            for uploaded_file in files:
                if not uploaded_file.filename:
                    # raise HTTPException(status_code=400, detail="NoNameFileError")
                    continue  # Ignore les fichiers sans nom (ex: champs vides dans le formulaire)
                saved_path = await _save_upload(uploaded_file, UPLOAD_DIR)
                print("---- File saved at: ", saved_path)
                if saved_path.stat().st_size == 0:
                    raise HTTPException(
                        status_code=400,
                        detail="EmptyFileError",
                    )
                saved_paths.append(saved_path)

            print("-->> All files saved successfully. Proceeding to analyze documents...")
            client = get_client()
            demand_data = await analyze_documents(
                client=client,
                model=model,
                document_paths=saved_paths,
                prompt=prompt + user_prompt,
                reference_files=reference_files,
            )
            print("-->> analyze_documents completed successfully. Company data received.")
           
            company_name = demand_data["company"]["legal_name"]["value"]
            (UPLOAD_DIR / mfi_name).mkdir(parents=True, exist_ok=True)

            with open(UPLOAD_DIR / mfi_name / f"{company_name}_credit_request.json", "w", encoding="utf-8") as f:
                print("---- We are writing !! ")
                json.dump(demand_data, f, ensure_ascii=True, indent=True)  
                print(f"-- {company_name}_credit_request.json created with success !--")
            
            missing_information = demand_data['missing_information']
            if missing_information:
                return JSONResponse(
                    {
                        "description": "Les informations necesaires a l'analyse sont manquantes",
                        "detail": missing_information[0]["question"],
                        "is_update": True
                    }, 
                    status_code=status.HTTP_412_PRECONDITION_FAILED
                )
            
            interpretation_prompt_filled = interpretation_prompt.format(
                company_name=company_name, 
                requested_amount=demand_data["credit_request"]["requested_amount"]["value"], 
                currency=demand_data["credit_request"]["requested_amount"]["currency"], 
                calculations_json=json.dumps(compute_analysis(demand_data), ensure_ascii=False)
            )
            interpretation_prompt_filled += f" ------ ADDITIONAL INSTRUCTION ------\n {user_prompt}"
            
            system_instructions = _read_reference_text(SYSTEM_INSTRUCTIONS_PATH)
            interpretation = await get_interpretation(client, model, system_instructions, interpretation_prompt_filled)

            # interpretation = "```json\n{\n  \"score\": 30,\n  \"label\": \"INCOMPLET\",\n  \"description\": \"Le dossier de REDCAP SOCITY SARL présente un nombre élevé de champs obligatoires manquants (8 sur 37), ce qui rend une évaluation complète impossible. Le chiffre d'affaires mensuel moyen de 413 333 XAF est en forte croissance, avec une évolution de +191.7% sur 3 mois, ce qui est positif. Cependant, le montant demandé de 3 000 000 XAF représente 7.26 mois de chiffre d'affaires moyen, un ratio potentiellement élevé. L'absence de données sur la mensualité du nouveau crédit, les dettes existantes et la marge d'exploitation réelle empêche le calcul du ratio de couverture du service de la dette (DSCR). De plus, aucune information sur le bilan, les flux bancaires ou les encaissements futurs n'est disponible, limitant l'analyse de la solidité financière et de la capacité de remboursement.\"\n}\n```"
            # company_name = "C-GIFT SARL"

            result = {
                "mfi_name": mfi_name,
                "company_name": company_name,
                "detail": parse_txt_to_json(interpretation)
            }
            return result

        except GeminiSafetyBlockedError as exc:
            # Pas la peine de réessayer: c'est le contenu du document qui est
            # rejeté, pas un problème serveur transitoire.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except GeminiFileError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except GeminiUpstreamError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:  # garde-fou pour toute erreur inattendue
            raise HTTPException(status_code=500, detail=f"Erreur interne: {exc}") from exc
        finally:
            # ------------------------------------------------
            # 3. Nettoyage des fichiers temporaires, dans tous les cas
            # ------------------------------------------------
            for path in saved_paths:
                path.unlink(missing_ok=True)
    else:
        promt = data.get("prompt") 
        return {"result": "Reponse utilisateur"}


@router.post("/chat")
async def chat_endpoint(
    data: dict[str, Any] = Depends(parse_json_form),
):
    """Reçoit un prompt utilisateur, le renvoie à Gemini, retourne la réponse."""
    user_prompt = data.get("prompt")
    if not user_prompt:
        raise HTTPException(status_code=400, detail="Le champ 'prompt' est requis.")
    try: 
        client = get_client()   
        system_instruction = """
            Tu es un assistant IA expert en finance et en comptabilité. Ton rôle est d'accompagner l'utilisateur sur tous les sujets liés à la comptabilité (générale, analytique), la fiscalité, la gestion de trésorerie, l'analyse financière, le contrôle de gestion et la paie.

            Directives de comportement :
            1. Périmètre strict : Tu dois répondre exclusivement aux questions relevant du domaine financier et comptable.
            2. Traitement du hors-sujet : Si la question de l'utilisateur ne concerne pas la finance ou la comptabilité (ex. cuisine, sport, programmation générale, culture générale, conseils de vie, etc.), refuse poliment d'y répondre en expliquant clairement ta spécialisation.
            - Exemple de formulation : "Je suis désolé, mais mes compétences sont limitées au domaine de la finance et de la comptabilité. Je ne peux pas répondre à cette question. N'hésite pas si tu as des interrogations comptables ou financières !"
            3. Qualité des réponses : Tes explications doivent être rigoureuses, claires, structurées et pédagogiques si demande de l'utilisatuer sinon donne juste une reponse claire.
            4. Précision du cadre : Si une question dépend de la législation d'un pays précis (ex. fiscalité), demande à l'utilisateur de préciser sa juridiction si ce n'est pas mentionné.
            5. Avertissement : Rappelle si nécessaire que tes analyses sont fournies à titre indicatif et ne remplacent pas le conseil d'un expert-comptable certifié.
        """ 
        response_txt = await send_message(client, model, system_instruction, user_prompt)
        return JSONResponse({"response": response_txt})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'appel à Gemini: {exc}") from exc
    