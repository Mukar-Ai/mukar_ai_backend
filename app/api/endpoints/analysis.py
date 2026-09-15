import uuid
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlmodel import Session, select

from app.api.dependencies import get_session, get_current_tenant_id
from app.models.credit import CreditApplication, ApplicationStatus
from app.models.analysis import CreditAnalysis, CreditAnalysisRead, RiskPolicy, DecisionType

router = APIRouter()


def mock_ai_analysis_task(
        application_id: uuid.UUID,
        tenant_id: uuid.UUID,
        policy_id: uuid.UUID,
        session: Session
):
    """
    Simule la tâche asynchrone (Celery/Dramatiq en prod) qui orchestre le RAG,
    le moteur financier, et l'appel LLM pour générer l'analyse finale.
    """
    # 1. Dans la vraie vie, on charge tous les documents, données client, et politique.
    # 2. On exécute le moteur RAG et l'extraction.
    # 3. On appelle le LLM via un orchestrateur.

    # Création d'un mock d'analyse positive
    analysis = CreditAnalysis(
        risk_score=35.5,
        risk_level="LOW",
        confidence_score=0.92,
        data_quality_score=0.85,
        ai_recommendation=DecisionType.APPROVED_WITH_CONDITIONS,
        ai_rationale="Capacité de remboursement adéquate. Le ratio d'endettement est acceptable, mais la garantie proposée manque légèrement de liquidité.",
        hard_blockers_found="[]",
        missing_information="[]",
        key_strengths=json.dumps(["Croissance CA de +15%", "Marge EBE stable"]),
        key_risks=json.dumps(["Délai client à 90 jours"]),
        conditions=json.dumps(["Domiciliation des revenus", "Mise en place d'un nantissement"]),
        application_id=application_id,
        policy_id=policy_id,
        tenant_id=tenant_id
    )

    # 4. Mettre à jour le statut du dossier
    app = session.get(CreditApplication, application_id)
    if app:
        app.status = ApplicationStatus.ANALYSIS_READY
        session.add(app)

    session.add(analysis)
    session.commit()


@router.post("/credit-applications/{application_id}/analyze", status_code=status.HTTP_202_ACCEPTED)
def trigger_analysis(
        application_id: uuid.UUID,
        background_tasks: BackgroundTasks,
        session: Session = Depends(get_session),
        tenant_id: uuid.UUID = Depends(get_current_tenant_id)
) -> Any:
    """
    Déclenche l'orchestrateur IA pour analyser le dossier de crédit.
    Traitement asynchrone (simulé ici via FastAPI BackgroundTasks).
    """
    # Vérification dossier
    app_statement = select(CreditApplication).where(
        CreditApplication.id == application_id,
        CreditApplication.tenant_id == tenant_id
    )
    application = session.exec(app_statement).first()
    if not application:
        raise HTTPException(status_code=404, detail="Credit application not found")

    if application.status == ApplicationStatus.ANALYZING:
        raise HTTPException(status_code=400, detail="Analysis already in progress")

    # Trouver la politique active
    policy_statement = select(RiskPolicy).where(
        RiskPolicy.tenant_id == tenant_id,
        RiskPolicy.is_active == True
    )
    policy = session.exec(policy_statement).first()
    if not policy:
        raise HTTPException(status_code=400, detail="No active Risk Policy found for this organization")

    # Mettre à jour le statut
    application.status = ApplicationStatus.ANALYZING
    session.add(application)
    session.commit()

    # Déclencher la tâche de fond
    background_tasks.add_task(mock_ai_analysis_task, application.id, tenant_id, policy.id, session)

    return {"message": "Analysis started successfully"}


@router.get("/credit-applications/{application_id}/analysis", response_model=CreditAnalysisRead)
def get_analysis(
        application_id: uuid.UUID,
        session: Session = Depends(get_session),
        tenant_id: uuid.UUID = Depends(get_current_tenant_id)
) -> Any:
    """
    Récupère le résultat complet de l'analyse IA.
    """
    statement = select(CreditAnalysis).where(
        CreditAnalysis.application_id == application_id,
        CreditAnalysis.tenant_id == tenant_id
    )
    analysis = session.exec(statement).first()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found for this application")

    return analysis
