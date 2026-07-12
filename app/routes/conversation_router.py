from fastapi import APIRouter, HTTPException
from app.services.conversation_service import (
    list_conversations,
    get_conversation,
    save_conversation,
    create_conversation,
    delete_conversation,
)

router = APIRouter(prefix="/api", tags=["conversations"])


@router.get("/conversations")
async def list_conversations_endpoint():
    return list_conversations()


@router.post("/conversations")
async def create_conversation_endpoint():
    """创建新对话"""
    return create_conversation()


@router.get("/conversations/{conv_id}")
async def get_conversation_endpoint(conv_id: str):
    result = get_conversation(conv_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return result


@router.post("/conversations/{conv_id}")
async def save_conversation_endpoint(conv_id: str, data: dict):
    return save_conversation(conv_id, data)


@router.delete("/conversations/{conv_id}")
async def delete_conversation_endpoint(conv_id: str):
    result = delete_conversation(conv_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return result
