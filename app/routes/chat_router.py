import json
import logging
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from app.services.chat_service import chat_with_agent_stream

logger = logging.getLogger("gt_agent.chat_router")

router = APIRouter(prefix="/api", tags=["chat"])


async def _stream_events(query: str, conv_id: str, file_contents: list):
    async for event in chat_with_agent_stream(query, conv_id, file_contents):
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat_endpoint(
    message: str = Form(None),
    conversation_id: str = Form(None),
    files: list[UploadFile] = File(None)
):
    if not message and not files:
        logger.warning("聊天请求缺少 message 和 files")
        raise HTTPException(status_code=400, detail="Message or file is required")
    
    file_contents = []
    if files:
        for file in files:
            content = await file.read()
            file_contents.append({"filename": file.filename, "content": content})
    
    try:
        return StreamingResponse(
            _stream_events(message or "", conversation_id, file_contents),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive"
            }
        )
    except Exception as e:
        logger.error("聊天流式响应异常: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"LLM Error: {str(e)}")