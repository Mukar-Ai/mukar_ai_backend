from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.dependencies import get_session, get_current_user
from app.models.tenant import EMFOrganization, EMFOrganizationCreate, EMFOrganizationRead, User

router = APIRouter()

@router.post("/", response_model=EMFOrganizationRead, status_code=status.HTTP_201_CREATED)
def create_tenant(
    *,
    session: Session = Depends(get_session),
    tenant_in: EMFOrganizationCreate
) -> Any:
    """
    Crée une nouvelle organisation EMF (Tenant).
    Dans un environnement de production réel, cette route devrait
    probablement être protégée par un rôle "SuperAdmin" global.
    """
    tenant = EMFOrganization.model_validate(tenant_in)
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant


@router.get("/me", response_model=EMFOrganizationRead)
def read_current_tenant(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Récupère les informations de l'organisation EMF (Tenant)
    à laquelle l'utilisateur actuellement authentifié appartient.
    """
    tenant_id = current_user.tenant_id
    tenant = session.get(EMFOrganization, tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant organization not found"
        )
    return tenant
