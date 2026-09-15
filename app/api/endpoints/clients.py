import uuid
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.api.dependencies import get_session, get_current_tenant_id
from app.models.client import (
    Client, ClientCreate, ClientRead, ClientType,
    Enterprise, Individual
)

router = APIRouter()


@router.post("/", response_model=ClientRead, status_code=status.HTTP_201_CREATED)
def create_client(
        *,
        session: Session = Depends(get_session),
        client_in: ClientCreate,
        tenant_id: uuid.UUID = Depends(get_current_tenant_id)
) -> Any:
    """
    Crée un nouveau client (Entreprise ou Particulier).
    Verrouille la création sur le tenant de l'utilisateur actif.
    """
    # 1. Validation métier des sous-schémas
    if client_in.client_type == ClientType.ENTERPRISE and not client_in.enterprise:
        raise HTTPException(
            status_code=400, detail="Enterprise details are required for ENTERPRISE client type"
        )
    if client_in.client_type == ClientType.INDIVIDUAL and not client_in.individual:
        raise HTTPException(
            status_code=400, detail="Individual details are required for INDIVIDUAL client type"
        )

    # 2. Création de l'entité mère avec le tenant_id forcé
    client = Client(
        client_type=client_in.client_type,
        email=client_in.email,
        phone=client_in.phone,
        address=client_in.address,
        tenant_id=tenant_id
    )
    session.add(client)
    session.commit()
    session.refresh(client)

    # 3. Création de l'entité fille selon le polymorphisme
    if client_in.client_type == ClientType.ENTERPRISE:
        enterprise = Enterprise.model_validate(
            client_in.enterprise, update={"client_id": client.id}
        )
        session.add(enterprise)
    else:
        individual = Individual.model_validate(
            client_in.individual, update={"client_id": client.id}
        )
        session.add(individual)

    session.commit()
    session.refresh(client)

    return client


@router.get("/{client_id}", response_model=ClientRead)
def read_client(
        client_id: uuid.UUID,
        session: Session = Depends(get_session),
        tenant_id: uuid.UUID = Depends(get_current_tenant_id)
) -> Any:
    """
    Récupère un client par son ID.
    Rejette la requête (404) si le client appartient à un autre EMF.
    """
    statement = select(Client).where(
        Client.id == client_id,
        Client.tenant_id == tenant_id
    )
    client = session.exec(statement).first()

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    return client
