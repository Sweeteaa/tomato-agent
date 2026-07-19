from typing import Optional, AsyncGenerator
from app.services.conversation_service import append_conversation, get_conversation
from app.services.graph_service import run_graph_stream
from app.services.file_service import extract_file_content, is_image_file, encode_image_to_base64
from app.services.document_image_service import (
    extract_document_images,
    is_office_document,
)
from app.config import MAX_IMAGES_PER_REQUEST, WORKSPACE
import asyncio
import hashlib
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("gt_agent.chat_service")


def _persist_uploaded_documents(files_for_graph: list[dict], conv_id: str = None) -> list[str]:
    """将上传的文本文件保存到 workspace/docs/ 以供后续对话引用

    Returns:
        保存的文件路径列表
    """
    docs_dir = WORKSPACE / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for f in files_for_graph:
        if isinstance(f, dict) and f.get("type") == "text" and f.get("content"):
            filename = f.get("filename", "unknown")
            content = f["content"]

            # 生成安全文件名
            safe_name = "".join(c for c in filename if c.isalnum() or c in (".", "_", "-")).strip()[:60]
            if not safe_name:
                doc_hash = hashlib.md5(filename.encode()).hexdigest()[:8]
                safe_name = f"doc_{doc_hash}"

            save_name = f"{timestamp}_{safe_name}.md"
            save_path = docs_dir / save_name

            # 写入 markdown 格式：包含元信息和内容
            header = f"---\nfilename: {filename}\nuploaded_at: {datetime.now().isoformat()}\nconv_id: {conv_id or ''}\n---\n\n"
            save_path.write_text(header + content, encoding="utf-8")
            saved_paths.append(str(save_path))
            logger.info("文档已持久化: %s → %s (%d 字符)", filename, save_name, len(content))

    return saved_paths


async def chat_with_agent_stream(query: str, conv_id: Optional[str] = None, files: Optional[list[dict]] = None) -> AsyncGenerator[dict, None]:
    file_info = []
    image_list = []
    uploaded_filenames = []
    files_for_graph: list[dict] = []  # 结构化文件块（text/image），透传给工作流

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
            elif is_office_document(file["filename"]):
                # Office 文档：同时提取文字和嵌入图片，实现图文融合理解
                text_content = await asyncio.to_thread(extract_file_content, file["content"], file["filename"])
                doc_image_result = await asyncio.to_thread(extract_document_images, file["content"], file["filename"])

                file_info.append(f"【文件: {file['filename']}】\n{text_content}\n")
                if doc_image_result["returned"] > 0:
                    file_info.append(
                        f"【提示: 已从 {file['filename']} 中提取 {doc_image_result['returned']} 张嵌入图片，"
                        f"{'还有 %d 张因上限被截断' % (doc_image_result['total'] - doc_image_result['returned']) if doc_image_result['truncated'] else '全部参与分析'}】"
                    )

                files_for_graph.append({
                    "type": "text",
                    "filename": file["filename"],
                    "content": text_content,
                })
                for img in doc_image_result["images"]:
                    files_for_graph.append({"type": "image", **img})
                uploaded_filenames.append(file["filename"])
            else:
                content = await asyncio.to_thread(extract_file_content, file["content"], file["filename"])
                file_info.append(f"【文件: {file['filename']}】\n{content}\n")
                files_for_graph.append({
                    "type": "text",
                    "filename": file["filename"],
                    "content": content,
                })
                uploaded_filenames.append(file["filename"])

        if skipped_images > 0:
            file_info.append(f"【提示: 还有 {skipped_images} 张图片因超过单次上限({MAX_IMAGES_PER_REQUEST}张)未上传】")
    
    # 注意：对话历史现在由 AgentLoop + SessionManager 管理
    # 不再需要手动拼接历史上下文

    # 持久化上传的文档到 workspace/docs/，供后续对话引用
    if files_for_graph:
        try:
            saved = await asyncio.to_thread(_persist_uploaded_documents, files_for_graph, conv_id)
            if saved:
                logger.info("已持久化 %d 个文档到 workspace/docs/", len(saved))
        except Exception as e:
            logger.warning("文档持久化失败: %s", e)

    # 将文件信息附加到 query，用于对话历史记录和 chat 意图的文本理解
    query_with_files = query
    if file_info:
        file_text = "\n".join(file_info)
        query_with_files = f"{query}\n\n{file_text}"

    final_result = None

    async for event in run_graph_stream(
        query, conv_id,
        images=image_list if image_list else None,
        files=files_for_graph if files_for_graph else None,
        has_uploaded_files=bool(file_info)
    ):
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
            conv_id,
            trace=final_result.get("execution_trace", []),
            plan=final_result.get("plan", {}),
        )
        final_result["conversation_id"] = conv_data["id"]
        yield final_result
