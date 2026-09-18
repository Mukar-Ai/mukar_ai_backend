from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel

# 1. Import de l'engine (Phase 2)
from app.db.session import engine

# 2. Chargement de l'ensemble des modèles pour la création du schéma de BDD
# Il est crucial d'importer tous les modèles ici pour que SQLModel les détecte.
import app.auth.models

# 3. Import des routeurs (API minimale Point 27)
from app.auth.endpoints import router as auth_router
from app.analysis.endpoints import router as analysis_router



@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestionnaire d'événements au démarrage et à l'arrêt de l'application.
    Assure la création des tables dans la base de données.
    """
    SQLModel.metadata.create_all(engine)
    yield
    # Nettoyage à l'extinction si besoin


# Initialisation de l'application FastAPI
app = FastAPI(
    title="Mukar AI",
    lifespan=lifespan
)

# Configuration CORS (Point 26 Sécurité)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En production, spécifier les domaines exacts du front-end
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Enregistrement des routeurs
app.include_router(auth_router, tags=["Authentication"], prefix='/api/auth')
app.include_router(analysis_router, tags=['Extraction'], prefix='/api')
# app.include_router(ressources_router, tags=["Ressource Management"], prefix='/api')
# app.include_router(tenants_router, tags=["Tenants"])
# app.include_router(clients_router, tags=["Clients"])
# app.include_router(credit_router, tags=["Credit Applications"])
# app.include_router(documents_router, tags=["Documents"])
# app.include_router(analysis_router, tags=["AI Analysis"])
# app.include_router(rag_router, tags=["RAG & External Context"])
# app.include_router(chat_router, tags=["Chat"])


@app.get("/", tags=["System"])
def read_root():
    """Vérification de l'état de santé du service."""
    return {
        "service": "Credit Decision Support System API",
        "status": "online",
        "docs_url": "/docs"
    }
