from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.conversation import Conversation, Message, MessageRole
from app.models.file import UploadedFile
from app.models.user import User
from app.schemas.chat import ConversationCreate, ConversationOut, MessageCreate, MessageOut
from app.services.vision_ai import VisionAIError, VisionAIService
from app.utils.response import APIResponse

router = APIRouter(tags=["chat"])
vision_ai_service = VisionAIService()


def serialize_conversation(conversation: Conversation) -> dict:
    return ConversationOut.model_validate(conversation).model_dump(mode="json")


def serialize_message(message: Message) -> dict:
    return {
        "id": str(message.id),
        "conversation_id": str(message.conversation_id),
        "role": message.role.value if hasattr(message.role, "value") else str(message.role),
        "message": message.message,
    }


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.file_id:
        result = await db.execute(
            select(UploadedFile).where(UploadedFile.id == payload.file_id, UploadedFile.user_id == current_user.id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    conversation = Conversation(user_id=current_user.id, file_id=payload.file_id, title=payload.title)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return APIResponse.success(serialize_conversation(conversation), "Conversation created", status.HTTP_201_CREATED)


@router.get("/conversations")
async def list_conversations(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Conversation).where(Conversation.user_id == current_user.id).order_by(Conversation.created_at.desc())
    )
    return APIResponse.success([serialize_conversation(item) for item in result.scalars().all()])


@router.post("/conversations/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
async def create_message(
    conversation_id: UUID,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == current_user.id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    uploaded_file = None
    if conversation.file_id:
        file_result = await db.execute(
            select(UploadedFile).where(
                UploadedFile.id == conversation.file_id,
                UploadedFile.user_id == current_user.id,
            )
        )
        uploaded_file = file_result.scalar_one_or_none()

    if uploaded_file is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vision chat requires a conversation linked to an uploaded image",
        )

    try:
        vision_result = await vision_ai_service.analyze(uploaded_file.file_path, payload.message)
    except VisionAIError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content=APIResponse.error(str(exc), exc.code),
        )

    user_message = Message(conversation_id=conversation.id, role=MessageRole.USER, message=payload.message)
    assistant_message = Message(
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        message=vision_result["ai_response"],
    )
    db.add_all([user_message, assistant_message])
    await db.commit()
    await db.refresh(user_message)
    await db.refresh(assistant_message)
    return APIResponse.success(
        {"messages": [serialize_message(user_message), serialize_message(assistant_message)]},
        "Message created",
        status.HTTP_201_CREATED,
    )
