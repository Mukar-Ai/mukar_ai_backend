from typing import Generator
from sqlmodel import create_engine, Session
from app.core.config import settings

# Création du moteur de base de données via SQLModel (qui wrap SQLAlchemy)
# pool_pre_ping=True garantit que la connexion est toujours valide avant de l'utiliser.
engine = create_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    echo=False,  # Passer à True pour debugger les requêtes SQL générées
    pool_pre_ping=True
)


def get_session() -> Generator[Session, None, None]:
    """
    Dépendance FastAPI pour injecter la session de base de données.
    Assure la fermeture automatique de la session après chaque requête.
    """
    with Session(engine) as session:
        yield session
