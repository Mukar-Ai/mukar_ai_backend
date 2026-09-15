from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from app.ressources.models import MFIOrganisation
from app.db.session import get_session


router = APIRouter(prefix="/mfi")


@router.post("/create")
def create_mfi_organization(data: dict, session: Session = Depends(get_session)):
    mfi = MFIOrganisation(**data)
    session.add(mfi)
    session.commit()
    session.refresh

    data['id'] = mfi.id
    return JSONResponse(data, status.HTTP_201_CREATED)

@router.get("/get/{mfi_id}")
def get_mfi_organization(mfi_id:str, session: Session = Depends(get_session)):
    return select(MFIOrganisation).where(MFIOrganisation.id == int(mfi_id))