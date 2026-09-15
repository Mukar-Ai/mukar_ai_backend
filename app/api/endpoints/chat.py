import uuid
from typing import Any, List, Optional
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.api.dependencies import get_session, get_current_tenant_id
from app.models.chat import (
    ChatSession, ChatSessionRead, ChatSessionStatus,
    ChatMessage, ChatMessageRead, SenderRole,
    Question, QuestionStatus, Answer, AnswerBase
)
from app.models.credit import CreditApplication

router = APIRouter()


# --- SCHEMAS IN-LINE ---
class ChatSessionCreate(BaseModel):
    title: Optional[str] = "Nouvelle conversation"
    application_id: Optional[uuid.UUID] = None


class ChatMessageCreate(BaseModel):
    content: str


class AnswerCreate(BaseModel):
    question_id: uuid.UUID
    content: str


# --- ENDPOINTS CHAT SESSIONS ---
@router.post("/chat/sessions", response_model=ChatSessionRead, status_code=status.HTTP_201_CREATED)
def create_chat_session(
        *,
        session: Session = Depends(get_session),
        session_in: ChatSessionCreate,
        tenant_id: uuid.UUID = Depends(get_current_tenant_id)
) -> Any:
    """Créer une nouvelle session de chat (Point 27 de la spec)."""

    # Vérifier l'accès à l'application si fournie
    if session_in.application_id:
        app = session.exec(
            select(CreditApplication).where(
                CreditApplication.id == session_in.application_id,
                CreditApplication.tenant_id == tenant_id
            )
        ).first()
        if not app:
            raise HTTPException(status_code=404, detail="Credit application not found")

    db_session = ChatSession(
        title=session_in.title or "Nouvelle conversation",
        application_id=session_in.application_id,
        tenant_id=tenant_id
    )
    session.add(db_session)
    session.commit()
    session.refresh(db_session)
    return db_session


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionRead)
def get_chat_session(
        session_id: uuid.UUID,
        session: Session = Depends(get_session),
        tenant_id: uuid.UUID = Depends(get_current_tenant_id)
) -> Any:
    """Récupérer une session de chat."""
    db_session = session.exec(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.tenant_id == tenant_id
        )
    ).first()
    if not db_session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return db_session


@router.get("/chat/sessions/{session_id}/messages", response_model=List[ChatMessageRead])
def get_chat_messages(
        session_id: uuid.UUID,
        session: Session = Depends(get_session),
        tenant_id: uuid.UUID = Depends(get_current_tenant_id)
) -> Any:
    """Récupérer l'historique des messages d'une session."""
    # Vérification sécurisée
    db_session = session.exec(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.tenant_id == tenant_id)).first()
    if not db_session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    messages = session.exec(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.sent_at.asc())
    ).all()
    return messages


@router.post("/chat/sessions/{session_id}/messages", response_model=ChatMessageRead,
             status_code=status.HTTP_201_CREATED)
def post_chat_message(
        session_id: uuid.UUID,
        message_in: ChatMessageCreate,
        session: Session = Depends(get_session),
        tenant_id: uuid.UUID = Depends(get_current_tenant_id)
) -> Any:
    """
    Publie un message utilisateur et simule une réponse de l'IA (Point 27).
    """
    # Vérification sécurisée
    db_session = session.exec(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.tenant_id == tenant_id)).first()
    if not db_session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    # Enregistrer message utilisateur
    user_msg = ChatMessage(
        sender_role=SenderRole.USER,
        content=message_in.content,
        session_id=session_id,
        tenant_id=tenant_id
    )
    session.add(user_msg)

    # Simuler la réponse de l'IA (Dans un système réel, on appellerait le LLM / RAG ici)
    ai_msg = ChatMessage(
        sender_role=SenderRole.AI_ASSISTANT,
        content="Je comprends. J'analyse actuellement cette information dans le contexte du dossier de crédit.",
        session_id=session_id,
        tenant_id=tenant_id
    )
    session.add(ai_msg)

    session.commit()
    session.refresh(user_msg)

    # On renvoie le message utilisateur pour confirmer le POST, le GET ramènera l'historique complet
    return user_msg


# --- ENDPOINT REPONSES AUX QUESTIONS DYNAMIQUES (Point 27) ---
@router.post("/credit-applications/{application_id}/answers", response_model=AnswerBase,
             status_code=status.HTTP_201_CREATED)
def submit_answer_to_question(
        application_id: uuid.UUID,
        answer_in: AnswerCreate,
        session: Session = Depends(get_session),
        tenant_id: uuid.UUID = Depends(get_current_tenant_id)
) -> Any:
    """
    Soumet une réponse humaine à une question dynamique soulevée par l'IA (Point 17 & 27).
    """
    # 1. Vérifier la question
    question = session.exec(
        select(Question).where(
            Question.id == answer_in.question_id,
            Question.application_id == application_id,
            Question.tenant_id == tenant_id
        )
    ).first()

    if not question:
        raise HTTPException(status_code=404, detail="Question not found or unauthorized")

    if question.status == QuestionStatus.ANSWERED:
        raise HTTPException(status_code=400, detail="Question has already been answered")

    # 2. Créer la réponse
    answer = Answer(
        content=answer_in.content,
        question_id=question.id,
        tenant_id=tenant_id
    )

    # 3. Mettre à jour la question
    question.status = QuestionStatus.ANSWERED

    session.add(answer)
    session.add(question)
    session.commit()
    session.refresh(answer)

    return answer
