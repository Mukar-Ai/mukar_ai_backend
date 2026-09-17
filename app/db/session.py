from typing import Generator
from sqlmodel import create_engine, Session
from app.core.config import settings

# Configuration arguments dynamically adapted for Serverless environments
connect_args = {}

# Check if we are running in production (on Vercel's infrastructure)
# If using Neon/Supabase pooling, we reduce the client-side pool sizes
if settings.DATABASE_URL or settings.POSTGRES_URL:
    # 1. Prevent Vercel instances from holding onto dead idle connections
    pool_size = 5
    max_overflow = 10
    pool_recycle = 1800  # Recycle connections every 30 minutes
else:
    # Local defaults
    pool_size = 5
    max_overflow = 10
    pool_recycle = -1

# Create the SQLModel engine
engine = create_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    echo=False,  # Set to True locally if you need to debug queries
    pool_size=pool_size,
    max_overflow=max_overflow,
    pool_recycle=pool_recycle,
    pool_pre_ping=True,  # Crucial for Vercel: tests the connection before running your endpoint code
    connect_args=connect_args
)


def get_session() -> Generator[Session, None, None]:
    """
    FastAPI dependency to inject the database session.
    Ensures the session is cleanly closed right after the HTTP request finishes.
    """
    with Session(engine) as session:
        yield session
