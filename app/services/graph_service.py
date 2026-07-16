"""graph_service — Agent 核心循环入口

架构: Reasoner → Tool → Observation → Memory → Critic
（替代旧架构: Planner → Executor → Reviewer）

循环流程:
  User Goal → Reasoner(LLM思考) → 是否需要工具?
    是 → Tool → Observation → Memory → Critic → 继续? → Reasoner
    否 → Final Answer

新增功能:
  - Project Context Check: 检查 workspace 是否已有项目知识，避免重复扫描
  - Requirement Analysis: 文件上传后进行需求结构化解析
  - Code Matching: 需求与代码的智能匹配
"""

from typing import Optional
import asyncio
import json
import logging
import re
from pathlib import Path
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from openai import AsyncOpenAI

from app.config import (
    DASHSCOPE_API_KEY, WORKSPACE_ID, MODEL_NAME, VL_MODEL_NAME,
    TEMPERATURE_PLANNING, TEMPERATURE_CHAT, MAX_STEPS, WORKSPACE,
)
from app.services.file_service import build_context
from app.services.memory_service import get_user_profile, update_profile
from app.services.task_service import get_pending_tasks, save_pending_task
from app.services.requirement_analyzer_service import RequirementAnalyzer
from app.services.code_matcher_service import CodeMatcher
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
from agent.workflows.project_scan_workflow import run_project_scan, is_project_scan_query, extract_project_path, load_project_knowledge
from app.services.conversation_project_memory import (
    set_conversation_project, get_current_project_for_conversation,
    clear_conversation_project,
)

logger = logging.getLogger("gt_agent.graph")

client = AsyncOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=f"https://{WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
)

registry = create_default_registry()
skill_manager = SkillManager()

requirement_analyzer = RequirementAnalyzer()
code_matcher = CodeMatcher()


def _load_project_knowledge(project_name: str) -> dict:
    knowledge_path = WORKSPACE / "projects" / project_name / "knowledge.json"
    if knowledge_path.exists():
        try:
            return json.loads(knowledge_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def _list_existing_projects() -> list:
    projects_dir = WORKSPACE / "projects"
    if not projects_dir.exists():
        return []
    projects = []
    for child in projects_dir.iterdir():
        if child.is_dir():
            knowledge = _load_project_knowledge(child.name)
            projects.append({
                "name": child.name,
                "has_knowledge": knowledge is not None,
                "framework": knowledge.get("framework", "") if knowledge else "",
                "page_count": len(knowledge.get("pages", [])) if knowledge else 0,
            })
    return projects


def _find_relevant_project(query: str) -> str:
    projects = _list_existing_projects()
    if not projects:
        return ""

    lower_query = query.lower()
    matched_projects = []

    for project in projects:
        score = 0
        if project["name"].lower() in lower_query:
            score += 10
        if project["framework"].lower() in lower_query:
            score += 5
        if any(kw in lower_query for kw in ["vue", "react", "angular"]):
            if project["framework"].lower().startswith(kw.split()[0]):
                score += 3
        if score > 0:
            matched_projects.append((project, score))

    if matched_projects:
        matched_projects.sort(key=lambda x: x[1], reverse=True)
        return matched_projects[0][0]["name"]

    return ""

# ─── 防幻觉规则（统一常量，避免重复） ───
ANTI_HALLUCINATION_RULES = """## 防幻觉规则（强制遵守）
1. 禁止猜测项目结构、目录内容、文件名
2. 禁止根据需求文档推断文件路径或内容
3. 禁止创建不存在的文件路径
4. 禁止根据目录名称推断业务功能（如不能因目录名包含"data"就推断它是"实验室检查"页面）
5. 当用户要求扫描项目、查看目录结构、分析代码时，必须调用 list_dir / read_file / search_file 工具获取真实结果
6. 扫描项目结构时，**必须先调用 list_dir 工具**获取目录结构信息，建议使用足够的深度（max_depth=5-10）
7. 如果工具没有返回结果，只能回答"无法访问本地文件系统，请检查路径是否正确或提供扫描权限"""


# ─── 构建 Reasoner prompt（注入完整上下文） ───

def _build_full_reasoner_prompt(query, context, skill_context, cap_desc, user_profile, pending_info):
    """返回一个闭包，供 reasoner_node 调用"""
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
    """返回一个闭包，供 critic_node 调用"""
    def _prompt_builder(goal, trajectory, iteration):
        return build_critic_prompt(
            goal=goal,
            trajectory=trajectory,
            iteration=iteration,
            max_steps=MAX_STEPS,
        )
    return _prompt_builder


def _build_memory_context(context, skill_context, user_profile, pending_info):
    """组装长期记忆上下文字符串"""
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


def _build_project_context(project_name: str) -> str:
    """构建项目知识上下文"""
    from agent.workflows.project_scan_workflow import load_project_knowledge
    from app.services.project_registry_service import get_registered_project
    
    project_info = get_registered_project(project_name)
    knowledge = load_project_knowledge(project_name)
    
    if not knowledge and not project_info:
        return ""
    
    parts = [f"## 当前项目: {project_name}"]
    
    if project_info:
        parts.append(f"- 路径: {project_info.get('root_path', '')}")
        parts.append(f"- 框架: {project_info.get('framework', '未知')}")
        parts.append(f"- 构建工具: {project_info.get('build_tool', '未知')}")
        parts.append(f"- 包管理器: {project_info.get('package_manager', '未知')}")
    
    if knowledge:
        pages = knowledge.get('pages', [])
        components = knowledge.get('components', [])
        api_modules = knowledge.get('api_modules', [])
        
        if pages:
            page_names = [p.get('name', '') for p in pages[:10]]
            parts.append(f"\n### 页面列表 ({len(pages)}个)")
            parts.append("\n".join(f"- {name}" for name in page_names))
            if len(pages) > 10:
                parts.append(f"- ... 还有 {len(pages) - 10} 个页面")
        
        if components:
            comp_names = [c.get('name', '') for c in components[:10]]
            parts.append(f"\n### 组件列表 ({len(components)}个)")
            parts.append("\n".join(f"- {name}" for name in comp_names))
            if len(components) > 10:
                parts.append(f"- ... 还有 {len(components) - 10} 个组件")
        
        if api_modules:
            api_names = [a.get('name', '') for a in api_modules[:10]]
            parts.append(f"\n### API模块 ({len(api_modules)}个)")
            parts.append("\n".join(f"- {name}" for name in api_names))
            if len(api_modules) > 10:
                parts.append(f"- ... 还有 {len(api_modules) - 10} 个模块")
    
    return "\n".join(parts)


# ─── 图节点包装（注入 client/registry 依赖） ───

async def _reasoner(state: AgentState) -> dict:
    return await reasoner_node(state, client, _reasoner_prompt_builder)


async def _tool(state: AgentState) -> dict:
    return await tool_node(state, registry)


async def _observation(state: AgentState) -> dict:
    return await observation_node(state, client, _observation_prompt_builder)


async def _critic(state: AgentState) -> dict:
    return await critic_node(state, client, _critic_prompt_builder)


# 闭包占位 — 在 run_graph_stream 中动态设置
_reasoner_prompt_builder = None
_critic_prompt_builder = None
_observation_prompt_builder = None


# ─── 构建图 ───
# 流程: reasoner → (tool → observer → critic | critic) → (reasoner | END)
# Memory 不再作为中间节点，改在任务完成后执行（由 run_graph_stream 调用 extract_and_save）

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


# ─── 偏好提取 ───

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


# ─── 主入口 ───

async def run_graph_stream(query: str, conv_id: Optional[str] = None, images: Optional[list[dict]] = None,
                          has_uploaded_files: bool = False):
    """运行 Agent 核心循环: Reasoner→Tool→Observation→MemoryUpdate→Critic

    Args:
        query: 用户问题（可能包含历史对话上下文）
        conv_id: 会话 ID
        images: 当前消息上传的图片列表
        has_uploaded_files: 当前消息是否包含上传文件
    """
    global _reasoner_prompt_builder, _critic_prompt_builder, _observation_prompt_builder

    logger.info("run_graph_stream: 开始处理 query=%s, conv_id=%s, images=%d, has_uploaded_files=%s",
                query[:50] + "..." if len(query) > 50 else query, conv_id,
                len(images) if images else 0, has_uploaded_files)
    has_images = bool(images)

    # 预计算共享上下文
    context = await asyncio.to_thread(build_context, query)
    skill_context = await asyncio.to_thread(skill_manager.get_skill_context, query)
    capabilities = await asyncio.to_thread(registry.list_capabilities)
    cap_desc = "\n".join(f"- {c['name']}: {c['description']}" for c in capabilities)
    user_profile = (await asyncio.to_thread(get_user_profile))["content"]

    # 预计算待办任务信息
    pending_tasks = await asyncio.to_thread(get_pending_tasks)
    pending_info = ""
    if pending_tasks["count"] > 0:
        pending_info = f"\n## 待办任务提醒\n你有 {pending_tasks['count']} 个未完成任务，请优先处理或询问用户是否继续。\n"
        for task in pending_tasks["tasks"][:3]:
            pending_info += f"- 对话 {task['id']} ({task['created_at']}): {len(task['steps'])} 个待办步骤\n"

    # ─── 检查对话记忆中的项目上下文 ───
    current_project_name, current_project_path = None, None
    if conv_id:
        current_project_name, current_project_path = get_current_project_for_conversation(conv_id)
        if current_project_name:
            yield {"type": "status", "message": f"检测到当前对话项目: {current_project_name}"}

    # ─── 提取消息中的项目路径前缀 ───
    # 前端格式: "项目路径: D:/projects/xxx\n\n用户消息" 或 "项目路径: D:/projects/xxx"（仅路径无消息）
    provided_project_path = None
    project_path_prefix_match = re.match(r'^项目路径:\s*(\S+)(?:\s*\n\n(.+))?$', query, re.DOTALL)
    if project_path_prefix_match:
        provided_project_path = project_path_prefix_match.group(1)
        remaining_query = (project_path_prefix_match.group(2) or "").strip()
        provided_project_name = Path(provided_project_path).name
        # 设置对话项目上下文
        if conv_id:
            set_conversation_project(conv_id, provided_project_name, provided_project_path)
            yield {"type": "status", "message": f"已设置项目上下文: {provided_project_name}"}
        # 更新当前项目信息
        current_project_name = provided_project_name
        current_project_path = provided_project_path
        # 剥离路径前缀，用剩余内容继续处理
        query = remaining_query

    # ─── 判断是否需要触发项目扫描 ───
    # 扫描条件：1) 明确的扫描关键词 2) 提供了项目路径但该项目尚无知识
    project_path = None
    project_name = None
    need_scan = False

    if is_project_scan_query(query):
        # 用户明确请求扫描
        need_scan = True
        project_path = extract_project_path(query) or provided_project_path
    elif provided_project_path:
        # 提供了项目路径，检查是否已有知识
        existing_knowledge = _load_project_knowledge(provided_project_name)
        if not existing_knowledge:
            need_scan = True
            project_path = provided_project_path
        else:
            yield {"type": "status", "message": f"项目 {provided_project_name} 已有知识，跳过扫描"}

    if need_scan and project_path:
        async for evt in run_project_scan(project_path, registry):
            yield evt
            if evt.get('type') == 'project_scan_done' and evt.get('project_context'):
                project_name = evt['project_context'].get('project_name')
                project_path = evt['project_context'].get('project_path')
                if conv_id:
                    set_conversation_project(conv_id, project_name, project_path)
                    yield {"type": "status", "message": f"已将 {project_name} 设置为当前对话项目"}

    # ─── 确定当前项目（优先使用新扫描的，否则使用记忆中的） ───
    final_project_name = project_name if project_name else current_project_name
    final_project_path = project_path if project_path else current_project_path

    # ─── 将项目知识注入上下文 ───
    if final_project_name:
        project_context = await asyncio.to_thread(_build_project_context, final_project_name)
        context = f"{project_context}\n\n{context}"
        yield {"type": "status", "message": f"已加载项目知识: {final_project_name}"}

    # ─── 仅项目路径（无消息、无文件）：扫描后直接返回结果 ───
    if not query and not has_uploaded_files and need_scan:
        summary = _build_project_context(final_project_name) if final_project_name else "项目扫描完成"
        yield {"type": "done", "response": summary, "context_used": True,
               "tool_executions": [], "plan": [], "plan_steps": 0,
               "execution_trace": [], "is_complete": True,
               "conversation_id": conv_id or "",
               "project_context": {"project_name": final_project_name, "has_knowledge": True} if final_project_name else {}}
        return

    # ─── 仅项目路径但已有知识（无消息、无文件）：返回已有知识摘要 ───
    if not query and not has_uploaded_files and not need_scan and final_project_name:
        summary = _build_project_context(final_project_name)
        yield {"type": "done", "response": summary, "context_used": True,
               "tool_executions": [], "plan": [], "plan_steps": 0,
               "execution_trace": [], "is_complete": True,
               "conversation_id": conv_id or "",
               "project_context": {"project_name": final_project_name, "has_knowledge": True}}
        return

    # 设置闭包（供图节点使用）
    _reasoner_prompt_builder = _build_full_reasoner_prompt(
        query, context, skill_context, cap_desc, user_profile, pending_info
    )
    _critic_prompt_builder = _build_full_critic_prompt()
    _observation_prompt_builder = None  # 使用默认 prompt

    # ─── 文件上传处理（含项目知识） ───
    # 项目路径+文件同时上传：扫描已在上面完成，此处用已有项目知识进行文档分析
    if has_uploaded_files:
        async for evt in _handle_uploaded_files(
            query, conv_id, images, has_images, context, skill_context, cap_desc, final_project_name
        ):
            yield evt
        return

    # ─── 进入核心循环 ───
    yield {"type": "status", "message": "正在推理..."}

    config = {"configurable": {"thread_id": conv_id or "default"}}
    initial_state = {
        "goal": query,
        "thought": "",
        "action": {},
        "observation": {},
        "trajectory": [],
        "hypothesis": [],
        "memory_context": _build_memory_context(context, skill_context, user_profile, pending_info),
        "finished": False,
        "answer": "",
        "iteration": 0,
        "conv_id": conv_id or "",
    }

    trace = []
    total_step_count = 0
    final_state = None
    max_steps_reached = False

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
                
                yield {"type": "trace", "step": {
                    "step": state.get("thought", ""),
                    "tool": obs.get("tool", "unknown"),
                    "args": obs.get("args", {}),
                    "result": obs.get("result", ""),
                    "status": obs.get("status", "unknown"),
                    "findings": findings,
                    "next_step_suggestion": suggestion,
                }}

            

            elif node == "critic":
                finished = state.get("finished", False)
                hypothesis = state.get("hypothesis", [])
                if finished:
                    yield {"type": "status", "message": "评判完成，准备输出回答"}
                else:
                    yield {"type": "status", "message": "评判: 需要继续推理"}
                final_state = state

    # ─── 处理最终结果 ───
    if final_state:
        answer = final_state.get("answer", "")
        finished = final_state.get("finished", True)
        iteration = final_state.get("iteration", 0)
        if not finished and iteration >= MAX_STEPS:
            max_steps_reached = True
    else:
        answer = ""
        finished = True

    # MAX_STEPS 强制结束提示
    if max_steps_reached:
        if answer:
            answer += "\n\n⚠️ 已达到最大执行轮次限制，部分任务可能未完成。"
        else:
            answer = "已达到最大执行轮次限制，部分任务可能未完成。"

    # 如果没有 answer，用轨迹总结
    if not answer:
        answer = await _summarize_trajectory(query, trace)

    await asyncio.to_thread(update_profile, _extract_preferences(query, trace))

    # ─── Memory Extractor: 从轨迹中提取值得保存的知识 ───
    if final_state and finished and trace:
        try:
            await extract_and_save(final_state, client)
        except Exception as e:
            logger.warning("Memory Extractor 失败: %s", e)

    # 未完成时保存待办任务
    if not finished and conv_id:
        pending_plan = [
            {"step": t.get("thought", ""), "tool": t.get("action", {}).get("tool", ""), "args": t.get("action", {}).get("args", {})}
            for t in trace
        ]
        logger.info("保存待办任务: conv_id=%s, plan_steps=%d", conv_id, len(pending_plan))
        await asyncio.to_thread(save_pending_task, conv_id, pending_plan)

    logger.info("run_graph_stream: 完成 (finished=%s, iteration=%d, steps=%d)",
                finished, final_state.get("iteration", 0) if final_state else 0, total_step_count)

    yield {
        "type": "done",
        "response": answer,
        "context_used": len(context) > 0,
        "tool_executions": trace,
        "plan": [],
        "plan_steps": total_step_count,
        "execution_trace": trace,
        "is_complete": finished,
        "conversation_id": conv_id or ""
    }


async def _handle_uploaded_files(query, conv_id, images, has_images, context, skill_context, cap_desc, project_name=None):
    """处理文件上传（需求分析流程）"""
    use_vl = has_images
    active_model = VL_MODEL_NAME if use_vl else MODEL_NAME
    status_msg = "正在分析上传图片..." if use_vl else "正在分析上传文件..."
    yield {"type": "status", "message": status_msg}

    image_hint = ""
    if has_images:
        image_names = ", ".join(img["filename"] for img in images)
        image_hint = f"\n\n## 上传图片\n用户上传了 {len(images)} 张图片: {image_names}\n图片已附带在消息中，你可以直接看到图片内容。请结合图片和文本内容回答用户问题。"

    existing_projects = _list_existing_projects()
    
    target_project = project_name if project_name else _find_relevant_project(query)
    project_knowledge = None

    if target_project:
        yield {"type": "status", "message": f"发现已存在项目知识: {target_project}"}
        project_knowledge = _load_project_knowledge(target_project)
        if project_knowledge:
            yield {"type": "status", "message": f"项目框架: {project_knowledge.get('framework', '未知')}, 页面数: {len(project_knowledge.get('pages', []))}"}

    if not has_images:
        yield {"type": "status", "message": "正在解析需求文档..."}
        parsed_requirements = requirement_analyzer.parse_requirements(query, conv_id or "")

        yield {"type": "status", "message": f"解析出 {parsed_requirements['total_requirements']} 条需求"}

        all_matches = []
        if project_knowledge:
            yield {"type": "status", "message": "正在进行需求代码匹配..."}
            for req in parsed_requirements["requirements"]:
                matches = code_matcher.match_requirement_to_code(req, project_knowledge)
                all_matches.append(matches)

            impact_analysis = code_matcher.analyze_impact(all_matches, parsed_requirements["requirements"])
            impact_summary = impact_analysis["summary"]
            requirement_summary = requirement_analyzer.generate_requirement_summary(parsed_requirements)

            full_response = f"{requirement_summary}\n\n{impact_summary}"
        else:
            requirement_summary = requirement_analyzer.generate_requirement_summary(parsed_requirements)
            full_response = f"{requirement_summary}\n\n## 注意\n当前 workspace 中未找到项目知识，请先扫描项目以进行代码匹配分析。"

        yield {"type": "token", "content": full_response}
    else:
        direct_prompt = f"""你是 GT Agent，一个本地智能开发助手。

{ANTI_HALLUCINATION_RULES}
6. 扫描项目结构时，必须先调用 scan_menu_structure 工具获取菜单和路由信息

## 路径规则
- 扫描用户项目: 使用绝对路径，如 'D:/projects/xxx'
- workspace 内操作: 使用相对路径，如 'skill/hello.md'

知识库上下文: {context}
相关技能: {skill_context}
可用能力: {cap_desc}
{image_hint}

用户已上传文件，文件内容已包含在问题中，请直接根据文件内容回答用户问题：
{query}"""

        yield {"type": "status", "message": "正在生成回答..."}

        user_content = [{"type": "text", "text": direct_prompt}]
        for img in images:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{img['mime']};base64,{img['data']}"}
            })
        messages = [
            {"role": "system", "content": "你是一个专业的开发助手，具备图片理解能力"},
            {"role": "user", "content": user_content}
        ]

        logger.info("使用模型 %s 处理上传文件 (images=%d)", active_model, len(images) if images else 0)
        full_response = ""

        async for chunk in await client.chat.completions.create(
            model=active_model,
            messages=messages,
            temperature=TEMPERATURE_CHAT,
            stream=True
        ):
            if chunk.choices[0].delta.content:
                token = chunk.choices[0].delta.content
                full_response += token
                yield {"type": "token", "content": token}

    await asyncio.to_thread(update_profile, _extract_preferences(query, []))

    yield {
        "type": "done",
        "response": full_response,
        "context_used": len(context) > 0,
        "tool_executions": [],
        "plan": [],
        "plan_steps": 0,
        "execution_trace": [],
        "is_complete": True,
        "conversation_id": conv_id or "",
        "project_context": {
            "project_name": target_project,
            "has_knowledge": project_knowledge is not None,
        } if target_project else {},
    }


async def _summarize_trajectory(query: str, trace: list) -> str:
    """用 LLM 总结轨迹，生成最终回答"""
    summary_prompt = f"""总结以下任务执行结果：

用户问题: {query}

执行轨迹:
{json.dumps(trace, ensure_ascii=False)}

请用自然语言总结给用户。"""

    messages = [{"role": "system", "content": "你是一个专业的开发助手"}, {"role": "user", "content": summary_prompt}]
    full_response = ""

    async for chunk in await client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=TEMPERATURE_CHAT,
        stream=True
    ):
        if chunk.choices[0].delta.content:
            full_response += chunk.choices[0].delta.content

    return full_response
