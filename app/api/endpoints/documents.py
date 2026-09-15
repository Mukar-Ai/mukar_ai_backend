import uuid
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlmodel import Session, select

from app.api.dependencies import get_session, get_current_tenant_id
from app.models.credit import CreditApplication
from app.models.document import (
    Document, DocumentRead, DocumentStatus, DocumentRequirement
)

router = APIRouter()


# Note: Dans une application réelle, ce service uploaderait vers S3/MinIO
# Pour l'instant, on simule l'enregistrement du fichier.
def mock_upload_to_s3(file: UploadFile, tenant_id: uuid.UUID) -> str:
    return f"s3://tenant-{tenant_id}/documents/{uuid.uuid4()}-{file.filename}"


@router.post("/credit-applications/{application_id}/documents", response_model=DocumentRead)
def upload_document(
        application_id: uuid.UUID,
        file: UploadFile = File(...),
        requirement_id: uuid.UUID = Form(None),
        session: Session = Depends(get_session),
        tenant_id: uuid.UUID = Depends(get_current_tenant_id)
) -> Any:
    """
    Uploade un document physique pour un dossier de crédit spécifique.
    Vérifie l'appartenance du dossier au tenant avant l'upload.
    """
    # 1. Vérifier que le dossier existe et appartient au tenant
    app_statement = select(CreditApplication).where(
        CreditApplication.id == application_id,
        CreditApplication.tenant_id == tenant_id
    )
    application = session.exec(app_statement).first()
    if not application:
        raise HTTPException(
            status_code=404,
            detail="Credit application not found or unauthorized"
        )

    # 2. Vérifier que le requirement (s'il est fourni) appartient bien au tenant
    if requirement_id:
        req_statement = select(DocumentRequirement).where(
            DocumentRequirement.id == requirement_id,
            DocumentRequirement.tenant_id == tenant_id
        )
        if not session.exec(req_statement).first():
            raise HTTPException(
                status_code=404,
                detail="Document requirement not found or unauthorized"
            )

    # 3. "Uploader" le fichier (Simulé)
    storage_path = mock_upload_to_s3(file, tenant_id)

    # 4. Enregistrer la métadonnée du document en base
    # La taille du fichier doit être récupérée (file.size n'est pas toujours disponible selon le backend UploadFile)
    # Dans une version de prod, on utilise `file.file.seek(0, 2)` pour lire la taille réelle.
    file_size = getattr(file, 'size', 0) or 0

    document = Document(
        file_name=file.filename,
        file_type=file.content_type or "application/octet-stream",
        file_size_bytes=file_size,
        storage_path=storage_path,
        status=DocumentStatus.RECEIVED,
        application_id=application_id,
        requirement_id=requirement_id,
        tenant_id=tenant_id
    )

    session.add(document)
    session.commit()
    session.refresh(document)

    return document


@router.get("/credit-applications/{application_id}/documents", response_model=List[DocumentRead])
def list_documents(
        application_id: uuid.UUID,
        session: Session = Depends(get_session),
        tenant_id: uuid.UUID = Depends(get_current_tenant_id)
) -> Any:
    """
    Liste tous les documents uploadés pour un dossier de crédit donné.
    """
    # Toujours filtrer par tenant_id de manière sécurisée
    statement = select(Document).where(
        Document.application_id == application_id,
        Document.tenant_id == tenant_id
    )
    documents = session.exec(statement).all()
    return documents
