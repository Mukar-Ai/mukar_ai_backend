from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select


from app.db.session import get_session
from app.core.security import verify_password, create_access_token
from app.auth.models import User, Token, generate_access_token
from pydantic import BaseModel

router = APIRouter()


# Schema de réponse pour le token
@router.post("/register")
async def signup(request: Request, session: Session = Depends(get_session)):
    data = await request.json()
    user = User(**data)
    session.add(user)
    session.commit()
    session.refresh(user)

    # access_token = generate_access_token()
    # token = Token(access_token=access_token, user_id=user.id)
    # session.add(token)
    # session.commit()

    return JSONResponse({
        'mfi_name': user.mfi_name,
        'email': user.email,
    }, status.HTTP_201_CREATED)


@router.post("/login")
async def login_access_token(request: Request, session: Session = Depends(get_session)):
    data = await request.json()
    statement = select(User).where(User.email == data['email'], User.password == data['password'])
    user = session.exec(statement).first()
    print("user: ", user)
    if not user:
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

    return JSONResponse({
        "email": user.email,
        "mfi_name": user.mfi_name
    })
