import uuid
from typing import Any, List

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.api.dependencies import get_session, get_current_user
from app.models.rag import (
    RegulationSource, MacroContext, SectorContext, RegulationStatus
)

router = APIRouter()


@router.get("/regulations/search", response_model=List[RegulationSource])
def search_regulations(
        query: str = Query(..., description="Mot clé de recherche (ex: Ratio de liquidité)"),
        status: RegulationStatus = Query(default=RegulationStatus.ACTIVE),
        session: Session = Depends(get_session),
        _=Depends(get_current_user)  # Exige une authentification, mais pas d'isolation tenant (table globale)
) -> Any:
    """
    Recherche lexicale (ou vectorielle dans le futur) dans la base de connaissances réglementaire (COBAC, OHADA).
    Point 9: "Ne jamais inventer un article, seuil, obligation ou URL".
    """
    # Recherche basique via ILIKE.
    # En phase d'architecture complète, cela utiliserait le RAG / pgvector.
    statement = select(RegulationSource).where(
        RegulationSource.status == status,
        (RegulationSource.title.ilike(f"%{query}%") | RegulationSource.reference.ilike(f"%{query}%"))
    )
    regulations = session.exec(statement).all()
    return regulations


@router.get("/economic-context", response_model=List[MacroContext])
def get_economic_context(
        session: Session = Depends(get_session),
        _=Depends(get_current_user)
) -> Any:
    """
    Récupère le contexte macroéconomique récent. (API exigée Point 27)
    """
    statement = select(MacroContext).order_by(MacroContext.date_recorded.desc()).limit(10)
    context = session.exec(statement).all()
    return context


@router.get("/sector-context", response_model=List[SectorContext])
def get_sector_context(
        sector_name: str = Query(None, description="Filtrer par nom de secteur (ex: BTP)"),
        session: Session = Depends(get_session),
        _=Depends(get_current_user)
) -> Any:
    """
    Récupère le contexte sectoriel. (API exigée Point 27)
    """
    statement = select(SectorContext)
    if sector_name:
        statement = statement.where(SectorContext.sector_name.ilike(f"%{sector_name}%"))

    statement = statement.order_by(SectorContext.date_recorded.desc()).limit(10)
    context = session.exec(statement).all()
    return context
