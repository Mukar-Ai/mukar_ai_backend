import uuid
import secrets
from datetime import datetime, timezone
from typing import Optional, List

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    mfi_name: str = Field(unique=True, index=True)
    email: str = Field(unique=True, index=True)
    password: str
    is_active: bool = Field(default=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Token(SQLModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    access_token: str = Field(unique=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    token_type: str = Field(default="Bearer")


def generate_access_token() -> str:
    return secrets.token_urlsafe(30).replace('-', '').replace('_', '')[:30]
