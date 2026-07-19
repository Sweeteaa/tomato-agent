"""graph_service — Agent 核心入口（意图路由器）

重构后架构:
    graph_service（路由层）
        │
        ├── AgentLoop（核心 Agent 循环 — 纯 asyncio 单循环）
        ├── ProjectWorkflow（项目扫描/知识更新）
        └── DocumentWorkflow（文档/图片分析）

移除:
  - LangGraph 依赖（StateGraph, MemorySaver, 4 节点循环）
  - 全局可变状态（_reasoner_prompt_builder 等）
  - reasoner/observer/critic 节点
"""

import asyncio
import logging
import re
from typing import Optional

from openai import AsyncOpenAI

from app.config import (
    DASHSCOPE_API_KEY, WORKSPACE_ID, WORKSPACE, MAX_STEPS,
    MODEL_NAME, TEMPERATURE_CHAT,
)
from app.services.file_service import build_context
from app.services.memory_service import get_user_profile
from app.services.task_service import get_pending_tasks
from agent.registry.capability_registry import create_default_registry
from agent.skill_manager.manager import SkillManager
from agent.agent_loop import AgentLoop
from app.workflows.context import WorkflowContext
from app.workflows.project_workflow import ProjectWorkflow
from app.workflows.document_workflow import DocumentWorkflow
from app.workflows.utils import (
    load_project_knowledge,
    list_existing_projects,
    build_project_context,
)
from app.services.conversation_project_memory import (
    get_current_project_for_conversation,
)

logger = logging.getLogger("gt_agent.graph")

# ─── 全局单例（只读，非可变状态）───

_client = AsyncOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=f"https://{WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
)

_registry = create_default_registry()
_skill_manager = SkillManager()

_agent_loop = AgentLoop(
    client=_client,
    model=MODEL_NAME,
    workspace=WORKSPACE,
    registry=_registry,
    temperature=TEMPERATURE_CHAT,
    max_iterations=MAX_STEPS,
)


def _detect_intent(query: str, has_uploaded_files: bool) -> str:
    """检测用户意图，确定使用哪个工作流

    Returns:
        "document": 纯文档/图片分析
        "project": 纯项目扫描
        "document+project": 文档 + 项目扫描复合意图
        "chat": 普通问答
    """
    has_project_intent = False

    # 检查是否有项目相关意图
    if re.match(r'^项目路径:\s*\S+', query):
        has_project_intent = True
    # 匹配各种绝对路径格式：Windows/macOS/Linux
    elif re.search(r'(D:/\S+|/[a-zA-Z]/\S+|[a-zA-Z]:\\\S+|/Users/\S+|/home/\S+)', query):
        has_project_intent = True
    else:
        project_keywords = [
            '扫描项目', '分析项目', '看看项目', '项目结构',
            'scan project', 'analyze project',
            '扫描代码', '分析代码', '看看代码',
            '项目路径', '项目目录',
            '结合项目', '结合代码',
        ]
        query_lower = query.lower()
        if any(kw in query_lower for kw in project_keywords):
            has_project_intent = True

    if has_uploaded_files and has_project_intent:
        return "document+project"
    if has_uploaded_files:
        return "document"
    if has_project_intent:
        return "project"

    return "chat"


def _mentions_documents(query: str) -> bool:
    """检测 query 是否提及之前上传的文档"""
    doc_keywords = [
        '结合文档', '结合需求文档', '需求文档', '上传的文档', '刚刚的文档',
        '刚才的文档', '之前上传', '文档分析', '文档内容', '文档中',
        '结合文档分析', '根据文档', '按文档',
    ]
    query_lower = query.lower()
    return any(kw in query_lower for kw in doc_keywords)


def _load_recent_documents() -> str:
    """从 workspace/docs/ 加载最近上传的文档内容（摘要）"""
    docs_dir = WORKSPACE / "docs"
    if not docs_dir.exists():
        return ""

    parts = []
    try:
        for f in sorted(docs_dir.glob("*.md"), reverse=True)[:3]:
            try:
                text = f.read_text(encoding="utf-8")
                # 提取原始文件名
                original_name = f.stem
                for line in text.split("\n"):
                    if line.startswith("filename:"):
                        original_name = line.split(":", 1)[1].strip()
                        break
                # 取前 3000 字符作为摘要
                content_preview = text[:3000]
                parts.append(f"### 文档: {original_name}\n{content_preview}")
            except Exception:
                pass
    except Exception:
        return ""

    if parts:
        return "\n\n".join(parts)
    return ""


def _load_all_memories() -> str:
    """加载所有记忆文件内容（包括子目录）"""
    mem_dir = WORKSPACE / "memory"
    if not mem_dir.exists():
        return ""
    
    parts = []
    # 加载顶层 .md 文件
    for f in sorted(mem_dir.glob("*.md")):
        try:
            content = f.read_text(encoding="utf-8")
            if content.strip():
                parts.append(f"### {f.stem}\n{content[:2000]}")
        except Exception:
            pass
    # 加载子目录（episodic/, semantic/ 等）
    for subdir in sorted(mem_dir.iterdir()):
        if subdir.is_dir():
            for f in sorted(subdir.glob("*.md"), reverse=True)[:10]:  # 每个子目录最多 10 个
                try:
                    content = f.read_text(encoding="utf-8")
                    if content.strip():
                        parts.append(f"### {subdir.name}/{f.stem}\n{content[:1500]}")
                except Exception:
                    pass
    return "\n\n".join(parts)


async def _build_agent_context(query: str, conv_id: Optional[str] = None):
    """构建 Agent 运行所需的上下文"""
    # 并行获取各类上下文
    memory_task = asyncio.to_thread(_load_all_memories)
    skill_task = asyncio.to_thread(_skill_manager.get_skill_context, query)
    profile_task = asyncio.to_thread(get_user_profile)
    pending_task = asyncio.to_thread(get_pending_tasks)

    memory_context, skill_context, profile_data, pending_tasks = await asyncio.gather(
        memory_task, skill_task, profile_task, pending_task
    )

    user_profile = profile_data.get("content", "")

    # 待办任务提醒
    pending_info = ""
    if pending_tasks.get("count", 0) > 0:
        pending_info = f"\n## 待办任务提醒\n你有 {pending_tasks['count']} 个未完成任务，请优先处理或询问用户是否继续。\n"
        for task in pending_tasks.get("tasks", [])[:3]:
            pending_info += f"- 对话 {task['id']} ({task.get('created_at', '')}): {len(task['steps'])} 个待办步骤\n"

    # 当前对话关联的项目
    project_name, project_path = None, None
    if conv_id:
        project_name, project_path = get_current_project_for_conversation(conv_id)

    return {
        "context": memory_context,
        "skill_context": skill_context,
        "user_profile": user_profile,
        "pending_info": pending_info,
        "project_name": project_name,
        "project_path": project_path,
    }


def _build_query_with_files(query: str, files: Optional[list[dict]]) -> str:
    """将 files 中的文本块附加到 query，供 chat 意图的 AgentLoop 使用。"""
    if not files:
        return query
    text_parts = []
    for f in files:
        if isinstance(f, dict) and f.get("type") == "text" and "content" in f:
            text_parts.append(f"【文件: {f.get('filename', 'unknown')}】\n{f['content']}\n")
    if not text_parts:
        return query
    return f"{query}\n\n" + "\n".join(text_parts)


def _has_image_blocks(files: Optional[list[dict]]) -> bool:
    """判断 files 中是否包含图片块。"""
    if not files:
        return False
    return any(isinstance(f, dict) and f.get("type") == "image" for f in files)


async def run_graph_stream(
    query: str,
    conv_id: Optional[str] = None,
    images: Optional[list[dict]] = None,
    files: Optional[list[dict]] = None,
    has_uploaded_files: bool = False,
):
    """运行 Agent 核心入口（意图路由器）

    根据用户意图路由到不同工作流：
    - document: 文件/图片上传
    - project: 项目扫描
    - chat: 普通问答（使用 AgentLoop）
    """
    logger.info(
        "run_graph_stream: query=%s, conv_id=%s, images=%d, has_uploaded_files=%s",
        query[:50] + "..." if len(query) > 50 else query,
        conv_id,
        len(images) if images else 0,
        has_uploaded_files,
    )

    # 构建上下文
    agent_ctx = await _build_agent_context(query, conv_id)

    intent = _detect_intent(query, has_uploaded_files)
    logger.info("检测到意图: %s", intent)

    ctx = WorkflowContext(
        query=query,
        conv_id=conv_id,
        context=agent_ctx["context"],
        skill_context=agent_ctx["skill_context"],
        cap_desc="",
        user_profile=agent_ctx["user_profile"],
        project_name=agent_ctx["project_name"],
        project_path=agent_ctx["project_path"],
        images=images or [],
        has_images=bool(images) or _has_image_blocks(files),
        files=files or [],
        pending_info=agent_ctx["pending_info"],
    )

    # ─── 项目扫描工作流（纯 project 或 document+project 复合意图） ───
    if intent in ("project", "document+project"):
        async for evt in ProjectWorkflow.run(ctx, _registry):
            if isinstance(evt, dict):
                if evt.get("type") == "done" and intent == "project":
                    # 纯项目扫描直接返回
                    yield evt
                    return
                if evt.get("type") == "project_updated":
                    ctx.project_name = evt.get("project_name")
                    ctx.project_path = evt.get("project_path")
                yield evt

    # 加载项目知识
    project_context = ""
    if ctx.project_name:
        try:
            project_context = await asyncio.to_thread(build_project_context, ctx.project_name)
            yield {"type": "status", "message": f"已加载项目知识: {ctx.project_name}"}
        except Exception as e:
            logger.warning("加载项目知识失败: %s", e)

    # ─── 文档分析工作流（纯 document 或 document+project 复合意图） ───
    if intent in ("document", "document+project"):
        async for evt in DocumentWorkflow.run(ctx, _registry):
            yield evt
        return

    # ─── 空查询处理 ───
    if not ctx.query:
        if ctx.project_name:
            summary = build_project_context(ctx.project_name)
            yield {
                "type": "done", "response": summary, "context_used": True,
                "tool_executions": [], "plan": [], "plan_steps": 0,
                "execution_trace": [], "is_complete": True,
                "conversation_id": conv_id or "",
            }
        else:
            yield {
                "type": "done", "response": "请输入您的问题或上传文件", "context_used": False,
                "tool_executions": [], "plan": [], "plan_steps": 0,
                "execution_trace": [], "is_complete": True,
                "conversation_id": conv_id or "",
            }
        return

    # ─── 核心 Agent 循环 ───
    # chat 意图：把 files 中的文本块拼回 query，保持原有文本理解行为
    chat_query = _build_query_with_files(ctx.query, files)

    # 自动关联文档：当用户提到“结合文档”等时，加载 workspace/docs/ 最近文档
    if _mentions_documents(ctx.query):
        doc_context = await asyncio.to_thread(_load_recent_documents)
        if doc_context:
            project_context += f"\n\n## 用户上传的文档内容\n\n{doc_context}"
            yield {"type": "status", "message": "已关联之前上传的文档内容"}
            logger.info("chat 意图自动关联文档内容")

    # 自动关联项目知识：如果 conv 关联了项目但还没加载
    if ctx.project_name and not project_context:
        try:
            project_context = await asyncio.to_thread(build_project_context, ctx.project_name)
            if project_context:
                yield {"type": "status", "message": f"已自动关联项目知识: {ctx.project_name}"}
        except Exception as e:
            logger.warning("自动关联项目知识失败: %s", e)

    async for evt in _agent_loop.process_message(
        query=chat_query,
        conv_id=conv_id or "default",
        images=images,
        user_profile=ctx.user_profile,
        memory_context=ctx.context,
        skill_context=ctx.skill_context,
        project_context=project_context,
        pending_info=ctx.pending_info,
    ):
        yield evt
