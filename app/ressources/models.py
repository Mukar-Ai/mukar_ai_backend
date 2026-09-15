from typing import Optional
from datetime import datetime, timezone
from sqlmodel import Field, SQLModel


class MFIOrganisation(SQLModel):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
