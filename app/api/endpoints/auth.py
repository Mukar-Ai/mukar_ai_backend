from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from app.api.dependencies import get_session
from app.core.security import verify_password, create_access_token
from app.models.tenant import User
from pydantic import BaseModel

router = APIRouter()


# Schema de réponse pour le token
class Token(BaseModel):
    access_token: str
    token_type: str


@router.post("/login", response_model=Token)
def login_access_token(
        session: Session = Depends(get_session),
        form_data: OAuth2PasswordRequestForm = Depends()
) -> Token:
    """
    Authentification OAuth2 compatible avec OpenAPI.
    Vérifie l'email (username) et le mot de passe de l'utilisateur,
    puis renvoie un Token JWT d'accès.
    """
    # Dans OAuth2PasswordRequestForm, le champ 'username' est standard.
    # Dans notre système, il correspond à l'adresse 'email'.
    statement = select(User).where(User.email == form_data.username)
    user = session.exec(statement).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )

    # Création du payload JWT
    access_token = create_access_token(subject=str(user.id))

    return Token(access_token=access_token, token_type="bearer")
