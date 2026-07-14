from typing import Optional, AsyncGenerator
from app.services.conversation_service import append_conversation, get_conversation
from app.services.graph_service import run_graph_stream
from app.services.file_service import extract_file_content, is_image_file, encode_image_to_base64
from app.config import MAX_IMAGES_PER_REQUEST
import asyncio
import logging

logger = logging.getLogger("gt_agent.chat_service")


async def chat_with_agent_stream(query: str, conv_id: Optional[str] = None, files: Optional[list[dict]] = None) -> AsyncGenerator[dict, None]:
    file_info = []
    image_list = []
    uploaded_filenames = []

    logger.info("开始聊天: query=%s, conv_id=%s, files=%d",
                query[:50] + "..." if len(query) > 50 else query,
                conv_id, len(files) if files else 0)

    if files and len(files) > 0:
        image_count = 0
        skipped_images = 0
        for file in files:
            if is_image_file(file["filename"]):
                # 限制单次图片数量
                if image_count >= MAX_IMAGES_PER_REQUEST:
                    skipped_images += 1
                    logger.info("图片数量超过上限 %d，跳过: %s", MAX_IMAGES_PER_REQUEST, file["filename"])
                    continue
                img_data = await asyncio.to_thread(encode_image_to_base64, file["content"], file["filename"])
                image_list.append(img_data)
                file_info.append(f"【图片: {file['filename']}】")
                uploaded_filenames.append(file["filename"])
                image_count += 1
                logger.info("图片已编码: %s (原始: %dKB → 压缩: %dKB)",
                            file["filename"],
                            img_data["original_size"] // 1024,
                            img_data["compressed_size"] // 1024)
            else:
                content = await asyncio.to_thread(extract_file_content, file["content"], file["filename"])
                file_info.append(f"【文件: {file['filename']}】\n{content}\n")
                uploaded_filenames.append(file["filename"])

        if skipped_images > 0:
            file_info.append(f"【提示: 还有 {skipped_images} 张图片因超过单次上限({MAX_IMAGES_PER_REQUEST}张)未上传】")
    
    context_messages = []
    if conv_id:
        conv_data = await asyncio.to_thread(get_conversation, conv_id)
        if conv_data and conv_data.get("messages"):
            for msg in conv_data["messages"]:
                role = msg["role"]
                content = msg["content"]
                if role == "user":
                    context_messages.append(f"用户: {content}")
                elif role == "assistant":
                    context_messages.append(f"助手: {content}")
    
    if file_info:
        query_with_files = f"{query}\n\n以下是上传的文件内容，请根据文件内容回答问题：\n{'---\n'.join(file_info)}"
    else:
        query_with_files = query
    
    if context_messages:
        context_str = "\n".join(context_messages[-20:])
        query_with_context = f"""以下是历史对话上下文：

{context_str}

请基于上述上下文，回答用户最新的问题：

{query_with_files}"""
    else:
        query_with_context = query_with_files

    final_result = None

    async for event in run_graph_stream(query_with_context, conv_id, images=image_list if image_list else None):
        if event["type"] == "done":
            final_result = event
            event["files_uploaded"] = uploaded_filenames
        else:
            yield event

    if final_result:
        conv_data = await asyncio.to_thread(
            append_conversation,
            query_with_files,
            final_result["response"],
            final_result["tool_executions"],
            conv_id
        )
        final_result["conversation_id"] = conv_data["id"]
        yield final_result