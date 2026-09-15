from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Mukar Ai" 
    API_V1_STR: str = "/api/v1"

    # Security
    SECRET_KEY: str  # plus de valeur par défaut : on veut que ça plante si oublié en prod
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Database (Neon fournit l'URL complète)
    DATABASE_URL: str  # ex: postgresql://user:pass@ep-xxx-pooler.eu-west-2.aws.neon.tech/dbname?sslmode=require

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        # SQLAlchemy + psycopg v3 attendent le schéma "postgresql+psycopg://"
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    # LLM / AI
    GEMINI_API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")


settings = Settings()