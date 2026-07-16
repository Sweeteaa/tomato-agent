"""graph_service — Agent 核心入口（意图路由器）

架构:
    graph_service（路由层）
        │
        ├── ChatWorkflow（普通问答）
        ├── ProjectWorkflow（项目扫描/知识更新）
        ├── RequirementWorkflow（需求解析→代码匹配）
        ├── DocumentWorkflow（文档/图片分析）
        └── MemoryWorkflow（知识提取与持久化）

每个 Workflow 独立执行，通过 WorkflowContext 共享上下文。
"""

from typing import Optional
import asyncio
import logging
import re

from app.config import (
    DASHSCOPE_API_KEY, WORKSPACE_ID, MAX_STEPS,
)
from app.services.file_service import build_context
from app.services.memory_service import get_user_profile, update_profile
from app.services.task_service import get_pending_tasks, save_pending_task
from agent.registry.capability_registry import create_default_registry
from agent.skill_manager.manager import SkillManager
from agent.core.state import AgentState
from agent.core.nodes import (
    reasoner_node, tool_node, observation_node, critic_node,
    should_use_tool, should_continue,
    build_reasoner_prompt, build_critic_prompt,
    build_observation_prompt,
)
from agent.memory.extractor import extract_and_save
from agent.workflows.project_scan_workflow import is_project_scan_query, load_project_knowledge
from app.services.conversation_project_memory import (
    get_current_project_for_conversation,
)
from app.workflows.context import WorkflowContext
from app.workflows.project_workflow import ProjectWorkflow
from app.workflows.document_workflow import DocumentWorkflow
from app.workflows.utils import (
    load_project_knowledge as _utils_load_knowledge,
    list_existing_projects,
    save_document_summary,
    list_document_summaries,
    find_relevant_project,
    build_project_context,
)

logger = logging.getLogger("gt_agent.graph")

from openai import AsyncOpenAI
client = AsyncOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=f"https://{WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
)

registry = create_default_registry()
skill_manager = SkillManager()

ANTI_HALLUCINATION_RULES = """## 防幻觉规则（强制遵守）
1. 禁止猜测项目结构、目录内容、文件名
2. 禁止根据需求文档推断文件路径或内容
3. 禁止创建不存在的文件路径
4. 禁止根据目录名称推断业务功能（如不能因目录名包含"data"就推断它是"实验室检查"页面）
5. 当用户要求扫描项目、查看目录结构、分析代码时，必须调用 list_dir / read_file / search_file 工具获取真实结果
6. 扫描项目结构时，**必须先调用 list_dir 工具**获取目录结构信息，建议使用足够的深度（max_depth=5-10）
7. 如果工具没有返回结果，只能回答"无法访问本地文件系统，请检查路径是否正确或提供扫描权限"""


def _build_memory_context(context, skill_context, user_profile, pending_info):
    parts = []
    if context:
        parts.append(f"## 知识库上下文\n{context}")
    if skill_context:
        parts.append(f"## 相关技能\n{skill_context}")
    if user_profile:
        parts.append(f"## 用户画像\n{user_profile}")
    if pending_info:
        parts.append(pending_info)
    return "\n\n".join(parts) if parts else "无"


def _extract_preferences(query: str, trajectory: list) -> dict:
    preferences = {
        "tech_stack": [],
        "skills": [],
        "code_style": [],
        "other": []
    }

    lower_query = query.lower()

    tech_keywords = {
        "vue": ["vue", "vue3", "vue2", "vite", "nuxt"],
        "react": ["react", "nextjs", "next.js", "remix"],
        "angular": ["angular"],
        "springboot": ["springboot", "spring boot", "java", "maven"],
        "python": ["python", "fastapi", "django", "flask"],
        "typescript": ["typescript", "ts"],
        "javascript": ["javascript", "js"],
        "tailwind": ["tailwind", "tailwindcss"],
        "docker": ["docker", "docker-compose"],
        "kubernetes": ["kubernetes", "k8s"],
        "mysql": ["mysql", "database", "sql"],
        "mongodb": ["mongodb", "nosql"]
    }

    for tech, keywords in tech_keywords.items():
        if any(kw in lower_query for kw in keywords):
            preferences["tech_stack"].append(tech.capitalize())

    skill_keywords = {
        "文件操作": ["read_file", "write_file", "delete_file", "list_dir"],
        "文档生成": ["save_skill", "document", "markdown", "文档"],
        "代码分析": ["分析", "review", "debug", "调试"],
        "搜索": ["search", "搜索", "find"],
        "记忆": ["memory", "记忆", "profile"]
    }

    for skill, keywords in skill_keywords.items():
        for step in trajectory:
            action = step.get("action", {})
            step_text = (step.get("thought", "") + " " + action.get("tool", "")).lower()
            if any(kw.lower() in step_text for kw in keywords):
                preferences["skills"].append(skill)
                break

    code_style_keywords = {
        "异步编程": ["async", "await", "promise"],
        "类型安全": ["typescript", "interface", "type"],
        "组件化": ["component", "组件"],
        "模块化": ["module", "import", "export"]
    }

    for style, keywords in code_style_keywords.items():
        if any(kw in lower_query for kw in keywords):
            preferences["code_style"].append(style)

    return preferences


def _build_full_reasoner_prompt(query, context, skill_context, cap_desc, user_profile, pending_info):
    def _prompt_builder(goal, trajectory, observation, memory_context, iteration):
        return build_reasoner_prompt(
            goal=goal,
            trajectory=trajectory,
            observation=observation,
            memory_context=_build_memory_context(context, skill_context, user_profile, pending_info),
            cap_desc=cap_desc,
            iteration=iteration,
            max_steps=MAX_STEPS,
            anti_hallucination_rules=ANTI_HALLUCINATION_RULES,
        )
    return _prompt_builder


def _build_full_critic_prompt():
    def _prompt_builder(goal, trajectory, iteration):
        return build_critic_prompt(
            goal=goal,
            trajectory=trajectory,
            iteration=iteration,
            max_steps=MAX_STEPS,
        )
    return _prompt_builder


async def _reasoner(state: AgentState) -> dict:
    return await reasoner_node(state, client, _reasoner_prompt_builder)


async def _tool(state: AgentState) -> dict:
    return await tool_node(state, registry)


async def _observation(state: AgentState) -> dict:
    return await observation_node(state, client, _observation_prompt_builder)


async def _critic(state: AgentState) -> dict:
    return await critic_node(state, client, _critic_prompt_builder)


_reasoner_prompt_builder = None
_critic_prompt_builder = None
_observation_prompt_builder = None

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

workflow = StateGraph(AgentState)
workflow.add_node("reasoner", _reasoner)
workflow.add_node("tool", _tool)
workflow.add_node("observer", _observation)
workflow.add_node("critic", _critic)
workflow.set_entry_point("reasoner")
workflow.add_conditional_edges("reasoner", should_use_tool)
workflow.add_edge("tool", "observer")
workflow.add_edge("observer", "critic")
workflow.add_conditional_edges("critic", should_continue)
graph = workflow.compile(checkpointer=MemorySaver())


def _detect_intent(query: str, has_uploaded_files: bool) -> str:
    """检测用户意图，确定使用哪个工作流"""
    if has_uploaded_files:
        return "document"
    
    if is_project_scan_query(query):
        return "project"
    
    if re.match(r'^项目路径:\s*\S+', query):
        return "project"
    
    if re.search(r'(D:/\S+|/[a-zA-Z]/\S+|[a-zA-Z]:\\\S+)', query):
        return "project"
    
    return "chat"


async def _run_chat_workflow(ctx: WorkflowContext):
    """执行普通问答工作流（核心循环）"""
    global _reasoner_prompt_builder, _critic_prompt_builder, _observation_prompt_builder

    _reasoner_prompt_builder = _build_full_reasoner_prompt(
        ctx.query, ctx.context, ctx.skill_context, ctx.cap_desc, ctx.user_profile, ctx.pending_info
    )
    _critic_prompt_builder = _build_full_critic_prompt()
    _observation_prompt_builder = None

    yield {"type": "status", "message": "正在推理..."}

    config = {"configurable": {"thread_id": ctx.conv_id or "default"}}
    initial_state = {
        "goal": ctx.query,
        "thought": "",
        "action": {},
        "observation": {},
        "trajectory": [],
        "hypothesis": [],
        "memory_context": _build_memory_context(ctx.context, ctx.skill_context, ctx.user_profile, ctx.pending_info),
        "finished": False,
        "answer": "",
        "iteration": 0,
        "conv_id": ctx.conv_id or "",
    }

    trace = []
    total_step_count = 0
    final_state = None

    async for event in graph.astream(initial_state, config=config):
        for node, state in event.items():
            if node == "reasoner":
                thought = state.get("thought", "")
                action = state.get("action", {})
                finished = state.get("finished", False)
                if finished:
                    yield {"type": "status", "message": "正在生成最终回答..."}
                elif action.get("tool"):
                    total_step_count += 1
                    yield {"type": "status", "message": f"正在推理步骤 {total_step_count}: {thought[:50]}"}
                else:
                    yield {"type": "status", "message": f"推理中: {thought[:50]}"}

            elif node == "tool":
                obs = state.get("observation", {})
                tool_name = obs.get("tool", "unknown")
                tool_status = obs.get("status", "unknown")
                tool_args = obs.get("args", {})
                tool_result = obs.get("result", "")
                
                yield {"type": "tool_start", "tool": tool_name, "args": tool_args}
                yield {"type": "status", "message": f"执行工具 {tool_name} ({tool_status})"}
                
                if tool_status in ("success", "error", "timeout"):
                    yield {
                        "type": "tool_end",
                        "tool": tool_name,
                        "status": tool_status,
                        "args": tool_args,
                        "result": tool_result[:500] if tool_result else "",
                    }

            elif node == "observer":
                obs = state.get("observation", {})
                findings = obs.get("findings", "")
                suggestion = obs.get("next_step_suggestion", "")
                facts = obs.get("facts", [])
                new_questions = obs.get("new_questions", [])
                total_step_count += 1
                
                if findings:
                    yield {"type": "status", "message": f"观察: {findings[:80]}"}
                
                yield {"type": "debug_trace", "trace": {
                    "thought": state.get("thought", ""),
                    "action": {
                        "tool": obs.get("tool", "unknown"),
                        "args": obs.get("args", {}),
                    },
                    "observation": {
                        "status": obs.get("status", "unknown"),
                        "findings": findings,
                        "facts": facts,
                        "new_questions": new_questions,
                        "next_step_suggestion": suggestion,
                        "result": obs.get("result", "")[:300],
                    },
                }}

            elif node == "critic":
                criticism = state.get("criticism", "")
                confidence = state.get("confidence", 0)
                suggestion = state.get("suggestion", "")
                should_continue_flag = state.get("should_continue", False)
                
                yield {"type": "debug_trace", "trace": {
                    "criticism": criticism[:200],
                    "confidence": confidence,
                    "suggestion": suggestion[:200],
                    "should_continue": should_continue_flag,
                }}

            final_state = state
            if "trajectory" in state:
                trace.extend(state["trajectory"])

    answer = final_state.get("answer", "") if final_state else ""
    finished = final_state.get("finished", False) if final_state else False

    yield {"type": "token", "content": answer}

    try:
        await asyncio.to_thread(extract_and_save, answer, trace)
    except Exception as e:
        logger.warning("Memory Extractor 失败: %s", e)

    if not finished and ctx.conv_id:
        pending_plan = [
            {"step": t.get("thought", ""), "tool": t.get("action", {}).get("tool", ""), "args": t.get("action", {}).get("args", {})}
            for t in trace
        ]
        logger.info("保存待办任务: conv_id=%s, plan_steps=%d", ctx.conv_id, len(pending_plan))
        await asyncio.to_thread(save_pending_task, ctx.conv_id, pending_plan)

    await asyncio.to_thread(update_profile, _extract_preferences(ctx.query, trace))

    yield {
        "type": "done",
        "response": answer,
        "context_used": len(ctx.context) > 0,
        "tool_executions": trace,
        "plan": [],
        "plan_steps": total_step_count,
        "execution_trace": trace,
        "is_complete": finished,
        "conversation_id": ctx.conv_id or ""
    }


async def run_graph_stream(query: str, conv_id: Optional[str] = None, images: Optional[list[dict]] = None,
                          has_uploaded_files: bool = False):
    """运行 Agent 核心入口（意图路由器）
    
    根据用户意图路由到不同工作流：
    - document: 文件/图片上传
    - project: 项目扫描
    - chat: 普通问答
    """
    logger.info("run_graph_stream: 开始处理 query=%s, conv_id=%s, images=%d, has_uploaded_files=%s",
                query[:50] + "..." if len(query) > 50 else query, conv_id,
                len(images) if images else 0, has_uploaded_files)

    has_images = bool(images)
    context = await asyncio.to_thread(build_context, query)
    skill_context = await asyncio.to_thread(skill_manager.get_skill_context, query)
    capabilities = await asyncio.to_thread(registry.list_capabilities)
    cap_desc = "\n".join(f"- {c['name']}: {c['description']}" for c in capabilities)
    user_profile = (await asyncio.to_thread(get_user_profile))["content"]

    pending_tasks = await asyncio.to_thread(get_pending_tasks)
    pending_info = ""
    if pending_tasks["count"] > 0:
        pending_info = f"\n## 待办任务提醒\n你有 {pending_tasks['count']} 个未完成任务，请优先处理或询问用户是否继续。\n"
        for task in pending_tasks["tasks"][:3]:
            pending_info += f"- 对话 {task['id']} ({task.get('created_at', '')}): {len(task['steps'])} 个待办步骤\n"

    current_project_name, current_project_path = None, None
    if conv_id:
        current_project_name, current_project_path = get_current_project_for_conversation(conv_id)
        if current_project_name:
            yield {"type": "status", "message": f"检测到当前对话项目: {current_project_name}"}

    intent = _detect_intent(query, has_uploaded_files)
    logger.info(f"检测到意图: {intent}")

    ctx = WorkflowContext(
        query=query,
        conv_id=conv_id,
        context=context,
        skill_context=skill_context,
        cap_desc=cap_desc,
        user_profile=user_profile,
        project_name=current_project_name,
        project_path=current_project_path,
        images=images or [],
        has_images=has_images,
        pending_info=pending_info,
    )

    if intent == "project":
        async for evt in ProjectWorkflow.run(ctx, registry):
            if isinstance(evt, dict):
                if evt.get("type") == "done":
                    yield evt
                    return
                if evt.get("type") == "project_updated":
                    ctx.project_name = evt.get("project_name")
                    ctx.project_path = evt.get("project_path")
                yield evt

    if ctx.project_name:
        project_context = await asyncio.to_thread(build_project_context, ctx.project_name)
        ctx.context = f"{project_context}\n\n{ctx.context}"
        yield {"type": "status", "message": f"已加载项目知识: {ctx.project_name}"}

    if intent == "document":
        async for evt in DocumentWorkflow.run(ctx, registry):
            yield evt
        return

    if not ctx.query:
        if ctx.project_name:
            summary = build_project_context(ctx.project_name)
            yield {"type": "done", "response": summary, "context_used": True,
                   "tool_executions": [], "plan": [], "plan_steps": 0,
                   "execution_trace": [], "is_complete": True,
                   "conversation_id": conv_id or "",
                   "project_context": {"project_name": ctx.project_name, "has_knowledge": True}}
        else:
            yield {"type": "done", "response": "请输入您的问题或上传文件", "context_used": False,
                   "tool_executions": [], "plan": [], "plan_steps": 0,
                   "execution_trace": [], "is_complete": True,
                   "conversation_id": conv_id or ""}
        return

    async for evt in _run_chat_workflow(ctx):
        yield evt
