from typing import Optional
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Mukar AI"
    API_V1_STR: str = "/api/v1"

    # 1. Vercel automatically injects one of these two variables
    DATABASE_URL: Optional[str] = None
    POSTGRES_URL: Optional[str] = None

    # 2. Local fallback credentials
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "123456789"
    POSTGRES_DB: str = "mukar_ai_db"
    POSTGRES_PORT: str = "5432"

    # LLM / AI
    GEMINI_API_KEY: Optional[str] = None

    # 3. Dynamic property that works both Locally and on Vercel
    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        # Check if Vercel provided a direct connection string
        url = self.DATABASE_URL or self.POSTGRES_URL
        
        if url:
            # Vercel provides 'postgres://' or 'postgresql://'
            # We rewrite it to use your preferred driver (psycopg or asyncpg)
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+psycopg://", 1)
            elif url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+psycopg://", 1)
            
            # Serverless databases (Neon/Supabase) require SSL over internet connections
            if "sslmode" not in url:
                url += "&sslmode=require" if "?" in url else "?sslmode=require"
            return url

        # Fallback to building it from parts if running locally without a single URL string
        return f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")


settings = Settings()
