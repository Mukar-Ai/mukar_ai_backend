import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.api.dependencies import get_session, get_current_tenant_id
from app.models.credit import (
    CreditApplication, CreditApplicationCreate, CreditApplicationRead,
    CreditProduct, ApplicationStatus
)
from app.models.client import Client

router = APIRouter()


@router.post("/", response_model=CreditApplicationRead, status_code=status.HTTP_201_CREATED)
def create_credit_application(
        *,
        session: Session = Depends(get_session),
        application_in: CreditApplicationCreate,
        tenant_id: uuid.UUID = Depends(get_current_tenant_id)
) -> Any:
    """
    Crée un nouveau dossier de crédit (CreditApplication).
    S'assure que le client et le produit existent et appartiennent au même tenant.
    Initialise le statut à DRAFT.
    """
    # 1. Vérification de l'existence et de l'appartenance du client
    client_statement = select(Client).where(
        Client.id == application_in.client_id,
        Client.tenant_id == tenant_id
    )
    if not session.exec(client_statement).first():
        raise HTTPException(
            status_code=404,
            detail="Client not found or does not belong to your organization"
        )

    # 2. Vérification de l'existence et de l'appartenance du produit
    product_statement = select(CreditProduct).where(
        CreditProduct.id == application_in.product_id,
        CreditProduct.tenant_id == tenant_id
    )
    if not session.exec(product_statement).first():
        raise HTTPException(
            status_code=404,
            detail="Credit Product not found or does not belong to your organization"
        )

    # 3. Création sécurisée de l'application
    db_application = CreditApplication.model_validate(
        application_in,
        update={
            "tenant_id": tenant_id,
            "status": ApplicationStatus.DRAFT
        }
    )

    session.add(db_application)
    session.commit()
    session.refresh(db_application)

    return db_application


@router.get("/{application_id}", response_model=CreditApplicationRead)
def read_credit_application(
        application_id: uuid.UUID,
        session: Session = Depends(get_session),
        tenant_id: uuid.UUID = Depends(get_current_tenant_id)
) -> Any:
    """
    Récupère un dossier de crédit par son ID.
    Isole strictement par tenant.
    """
    statement = select(CreditApplication).where(
        CreditApplication.id == application_id,
        CreditApplication.tenant_id == tenant_id
    )
    application = session.exec(statement).first()

    if not application:
        raise HTTPException(status_code=404, detail="Credit Application not found")

    return application
