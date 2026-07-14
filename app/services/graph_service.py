from typing import TypedDict, Literal, Optional
import asyncio
import json
import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from openai import AsyncOpenAI

from app.config import DASHSCOPE_API_KEY, WORKSPACE_ID, MODEL_NAME, VL_MODEL_NAME, TEMPERATURE_PLANNING, TEMPERATURE_CHAT, MAX_STEPS
from app.services.file_service import build_context
from app.services.memory_service import get_user_profile, update_profile
from app.services.task_service import get_pending_tasks, save_pending_task
from agent.registry.capability_registry import create_default_registry
from agent.skill_manager.manager import SkillManager
from agent.exceptions import ToolError

logger = logging.getLogger("gt_agent.graph")

client = AsyncOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=f"https://{WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
)

registry = create_default_registry()
skill_manager = SkillManager()

# ─── 防幻觉规则（统一常量，避免重复） ───
ANTI_HALLUCINATION_RULES = """## 防幻觉规则（强制遵守）
1. 禁止猜测项目结构、目录内容、文件名
2. 禁止根据需求文档推断文件路径或内容
3. 禁止创建不存在的文件路径
4. 禁止根据目录名称推断业务功能（如不能因目录名包含"data"就推断它是"实验室检查"页面）
5. 当用户要求扫描项目、查看目录结构、分析代码时，必须调用 list_dir / read_file / search_file 工具获取真实结果
6. 扫描项目结构时，**必须先调用 list_dir 工具**获取目录结构信息，建议使用足够的深度（max_depth=5-10）
7. 如果工具没有返回结果，只能回答"无法访问本地文件系统，请检查路径是否正确或提供扫描权限"""


class AgentState(TypedDict):
    messages: list[str]
    plan: list[dict]
    execution_results: list[dict]
    execution_trace: list[dict]
    review_feedback: str
    is_complete: bool
    revised_plan: list[dict]
    conv_id: Optional[str]
    step_count: int


def _build_planner_prompt(query: str, context: str = None, skill_context: str = None, cap_desc: str = None,
                          user_profile: str = None, pending_info: str = None) -> str:
    if context is None:
        context = build_context(query)
    if skill_context is None:
        skill_context = skill_manager.get_skill_context(query)
    if cap_desc is None:
        capabilities = registry.list_capabilities()
        cap_desc = "\n".join(f"- {c['name']}: {c['description']}" for c in capabilities)
    if user_profile is None:
        user_profile = get_user_profile()["content"]
    if pending_info is None:
        pending_tasks = get_pending_tasks()
        pending_info = ""
        if pending_tasks["count"] > 0:
            pending_info = f"\n## 待办任务提醒\n你有 {pending_tasks['count']} 个未完成任务，请优先处理或询问用户是否继续。\n"
            for task in pending_tasks["tasks"][:3]:
                pending_info += f"- 对话 {task['id']} ({task['created_at']}): {len(task['steps'])} 个待办步骤\n"

    prompt = f"""你是 GT Agent 的规划师。根据用户问题，制定详细的执行计划。

用户问题: {query}

{pending_info}

## 用户画像
{user_profile}

## 可用能力
{cap_desc}

## 可用工具完整列表（只能使用以下工具，禁止使用不在此列表的工具）
- read_file(path, max_size) — 读取文件内容，支持绝对路径和相对路径
- list_dir(path, recursive, max_depth) — 列出目录内容，支持绝对路径和相对路径
- search_file(keyword, root_path, file_extensions, context_lines, max_results) — 搜索项目源码，返回匹配行号和上下文代码（定位业务页面最精准的方式）
- scan_menu_structure(project_path) — 扫描菜单和路由配置
- scan_project(project_path 或 name, full_scan) — 深度扫描项目结构（推荐传 project_path）
- list_registered_projects() — 列出已注册项目
- get_project_info(name) — 获取已注册项目元数据
- list_project_docs() — 列出项目文档
- get_project_doc(project, doc) — 读取项目文档
- write_file(path, content) — 写入文件（仅 workspace 内）
- delete_file(path) — 删除文件（仅 workspace 内）
- append_file(path, content) — 追加内容（仅 workspace 内）
- create_folder(path) — 创建文件夹（仅 workspace 内）
- save_skill(name, content) — 保存技能文档
- read_skill(name) — 读取技能文档
- list_skills() — 列出所有技能
- save_task(name, content) — 保存任务清单
- read_task(name) — 读取任务清单
- list_tasks() — 列出所有任务
- save_memory(name, content) — 保存记忆
- read_memory(name) — 读取记忆
- list_memory() — 列出所有记忆
- delete_memory(name) — 删除记忆

**禁止使用不在上述列表中的工具名（如 http_request、search_files、execute_command 等均不存在）**

## 相关技能
{skill_context if skill_context else "无"}

## 知识库上下文
{context if context else "无"}

{ANTI_HALLUCINATION_RULES}

## 路径规则（重要！）
- **扫描用户项目**: 使用绝对路径，如 list_dir(path='/Users/xxx/projects/xxx'), read_file(path='/Users/xxx/projects/xxx/src/App.vue'), scan_project(project_path='/Users/xxx/projects/xxx')
- **workspace 内操作**: 使用相对路径（不需要加 workspace 前缀），如 write_file(path='skill/hello.md'), save_skill(name='xxx', content='...')
- read_file 和 list_dir 同时支持绝对路径和相对路径
- scan_project 推荐使用 project_path 参数（绝对路径），无需注册即可扫描
- write_file / delete_file / append_file / create_folder 只支持 workspace 相对路径

## 项目代码分析策略（重要！）
当用户要求"分析项目"、"结合项目修改需求"时，按以下策略规划步骤：

### 推荐工作流
1. **scan_project(project_path=项目绝对路径)** — 获取项目概览（框架、技术栈、页面/组件数量）
2. **search_file(keyword='业务关键词', root_path=项目路径)** — 用需求中的字段名/业务术语搜索源码，直接定位需修改的文件
3. **read_file(path=搜索到的文件绝对路径)** — 读取匹配文件的具体内容

### 关键原则
- **禁止读取 scan_project 生成的 .md 文档**（如 routes.md, overview.md）——这些是中间产物，信息有损。直接搜索源码更准确
- **动态路由陷阱**：很多项目的路由是后端返回动态添加的（如 router.addRoute()），静态路由文件只包含 /login、/home 等基础路由。**不要依赖路由文件定位业务页面**
- **用需求关键词搜索源码**：从需求文档中提取字段名、业务术语作为 keyword。例如：
  - 需求提到"数据看板" → search_file(keyword='数据看板,data-board,databoard', root_path=项目路径)
  - 需求提到"病灶编号" → search_file(keyword='病灶编号,US-1,lesion', root_path=项目路径, file_extensions='vue')
  - 需求提到"研究状态" → search_file(keyword='研究状态,followStatus', root_path=项目路径, file_extensions='vue')
- **多关键词搜索**：keyword 支持逗号分隔（OR逻辑），中文业务名 + 英文字段名一起搜命中率最高
- **file_extensions 过滤**：搜索表单页面时用 file_extensions='vue'，搜索接口时用 'js,ts'
- **search_file 返回匹配行号和上下文**：根据返回的代码片段判断是否为目标文件，再用 read_file 读取完整内容

## 要求
1. 如果需要调用工具，将任务分解为多个步骤，每个步骤明确调用什么工具
2. 每个步骤的 "tool" 必须是上方列表中的工具名，"args" 中的参数名必须与列表中一致
3. 如果不需要调用工具，直接回答即可，输出空数组 []
4. 输出格式必须是 JSON 数组，包含步骤描述和工具名称：
   [
     {{
       "step": "步骤描述",
       "tool": "工具名称",
       "args": {{"参数名": "参数值"}}
     }}
   ]"""

    return prompt


def _build_reviewer_prompt(query: str, trace: list, step_count: int, max_steps: int) -> str:
    # 截断单个工具结果到 500 字符（保留关键信息，避免 reviewer 丢失上下文）
    def _summarize_result(result, max_len=500):
        text = str(result)
        if len(text) <= max_len:
            return text
        return text[:max_len] + "...[已截断，完整结果见 execution_trace]"

    trace_summary = "\n".join(
        f"  {i+1}. [{t.get('status', 'unknown')}] {t.get('step', '')} (工具: {t.get('tool', 'N/A')}) → {_summarize_result(t.get('result', ''))}"
        for i, t in enumerate(trace)
    ) if trace else "  （无执行记录）"

    remaining_steps = max_steps - step_count

    return f"""评审执行结果：

用户问题: {query}

## 完整执行轨迹（第 {step_count} 轮，剩余 {remaining_steps} 轮）
{trace_summary}

## 评审要求
1. 仔细检查每个步骤的执行结果，判断用户问题是否已被充分解决
2. 检查是否有失败的步骤（status=error），这些步骤是否影响最终结果
3. 判断是否需要补充执行额外步骤（如：读取更多文件、搜索更多目录、修复错误后重试）

## 判定规则（重要！避免无效循环）
- **is_complete = true 的条件**（满足任一即可）:
  a) 所有步骤成功执行，用户问题已得到回答
  b) 大部分步骤成功，已获取足够信息回答用户问题（个别失败步骤不影响整体结论）
  c) 失败的步骤是因为工具不存在或参数错误，重试也不会成功
- **is_complete = false** 仅当: 有关键步骤失败且重试可能成功，或缺少必要信息无法回答用户问题
  - 此时必须提供 revised_plan，包含**仅新增的**步骤（不要重复已成功的步骤）
  - revised_plan 中每个步骤格式与原始 plan 相同：{{"step": "描述", "tool": "工具名", "args": {{...}}}}
  - **不要重复已失败的步骤**（除非有充分理由认为重试会成功）
- **当剩余轮次 ≤ 2 时，倾向于 is_complete = true**，用已有信息总结回答

## 输出格式（严格 JSON）
{{
  "is_complete": true,
  "feedback": "用自然语言总结执行结果，回答用户问题",
  "revised_plan": []
}}

或当未完成时：
{{
  "is_complete": false,
  "feedback": "简要说明当前进展和未完成原因",
  "revised_plan": [
    {{
      "step": "补充步骤描述",
      "tool": "工具名称",
      "args": {{}}
    }}
  ]
}}"""


async def planner_node(state: AgentState) -> AgentState:
    """规划节点 — 使用 run_graph_stream 已生成的 plan，避免重复 LLM 调用。

    plan 在 run_graph_stream() 中通过流式 LLM 调用预先生成，
    此节点仅做 pass-through，将 plan 传递给 executor。

    文件上传和 no-plan 场景已在 run_graph_stream() 中提前 return，
    到达此节点时 plan 必然非空。
    """
    plan = state.get("plan", [])
    return {
        **state,
        "plan": plan,
        "execution_results": [],
        "execution_trace": [],
        "review_feedback": "",
        "is_complete": False,
        "step_count": 0
    }


async def executor_node(state: AgentState) -> AgentState:
    plan = state["plan"]
    results = []
    trace = state.get("execution_trace", [])

    for step in plan:
        if "tool" in step and step["tool"]:
            try:
                args = step.get("args", {})
                result = await asyncio.to_thread(registry.execute_tool, step["tool"], args)
                results.append({"step": step["step"], "tool": step["tool"], "result": result})
                trace.append({
                    "step": step["step"],
                    "tool": step["tool"],
                    "args": args,
                    "result": result,
                    "status": "success"
                })
            except ToolError as e:
                logger.warning("工具 %s 执行失败: %s", e.tool_name, e.detail)
                error_msg = f"执行失败: {e.detail}"
                results.append({"step": step["step"], "tool": step["tool"], "result": error_msg})
                trace.append({
                    "step": step["step"],
                    "tool": e.tool_name or step["tool"],
                    "args": step.get("args", {}),
                    "result": error_msg,
                    "status": "error"
                })
            except KeyError as e:
                # handler 内部 args["key"] 取值失败 — 参数名不匹配
                logger.warning("工具 %s 参数缺失: %s (args=%s)", step["tool"], e, step.get("args", {}))
                error_msg = f"参数缺失: {e}。请检查工具参数名是否正确，args={step.get('args', {})}"
                results.append({"step": step["step"], "tool": step["tool"], "result": error_msg})
                trace.append({
                    "step": step["step"],
                    "tool": step["tool"],
                    "args": step.get("args", {}),
                    "result": error_msg,
                    "status": "error"
                })
            except Exception as e:
                logger.error("工具 %s 未知异常: %s", step["tool"], e, exc_info=True)
                error_msg = f"执行失败: {str(e)}"
                results.append({"step": step["step"], "tool": step["tool"], "result": error_msg})
                trace.append({
                    "step": step["step"],
                    "tool": step["tool"],
                    "args": step.get("args", {}),
                    "result": error_msg,
                    "status": "error"
                })

    return {**state, "execution_results": results, "execution_trace": trace, "step_count": state["step_count"] + 1}


async def reviewer_node(state: AgentState) -> AgentState:
    """评审节点 — 评估执行结果，决定是否完成或需要补充执行。

    流程：
    1. 无执行结果 → 直接完成
    2. 达到 MAX_STEPS → 强制完成（避免无限循环）
    3. 调用 LLM 评审 → 根据返回的 is_complete 决定后续：
       - complete=True → 结束，feedback 作为最终回答
       - complete=False → 使用 revised_plan 回到 executor 执行补充步骤
    """
    trace = state.get("execution_trace", [])
    results = state.get("execution_results", [])
    query = state["messages"][-1]["content"]
    step_count = state.get("step_count", 0)

    # 无结果可评审 → 直接完成
    if not results and not trace:
        logger.debug("reviewer: 无执行结果，直接完成")
        return {**state, "is_complete": True, "review_feedback": "没有需要执行的步骤。"}

    # 达到最大步数 → 强制完成，防止无限循环
    if step_count >= MAX_STEPS:
        logger.warning("reviewer: 达到 MAX_STEPS=%d，强制完成", MAX_STEPS)
        return {
            **state,
            "is_complete": True,
            "review_feedback": "已达到最大执行轮次限制，以下是当前已完成的执行结果总结。",
        }

    prompt = _build_reviewer_prompt(query, trace, step_count, MAX_STEPS)

    messages = [
        {"role": "system", "content": "你是一个专业的任务评审员，只输出 JSON 格式"},
        {"role": "user", "content": prompt},
    ]

    completion = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=TEMPERATURE_PLANNING,
        response_format={"type": "json_object"},
    )

    try:
        review = json.loads(completion.choices[0].message.content)
        is_complete = review.get("is_complete", True)
        feedback = review.get("feedback", "")
        revised_plan = review.get("revised_plan", [])
    except (json.JSONDecodeError, KeyError) as e:
        # JSON 解析失败 → 默认完成
        logger.warning("reviewer: JSON 解析失败 (%s)，默认完成", e)
        is_complete = True
        feedback = completion.choices[0].message.content
        revised_plan = []

    # 安全网：revised_plan 必须是非空列表才有效
    if not is_complete and not revised_plan:
        # LLM 说未完成但没给修订计划 → 视为完成
        logger.warning("reviewer: LLM 说未完成但未提供修订计划，视为完成")
        is_complete = True

    if is_complete:
        logger.info("reviewer: 任务完成 (step_count=%d)", step_count)
        return {
            **state,
            "is_complete": True,
            "review_feedback": feedback,
        }
    else:
        # 未完成 → 设置修订计划，清空 execution_results，回到 executor
        logger.info("reviewer: 任务未完成，修订计划 %d 步，回到 executor", len(revised_plan))
        return {
            **state,
            "is_complete": False,
            "plan": revised_plan,
            "execution_results": [],  # 清空，让 executor 重新填充
            # execution_trace 保留——跨轮累积
            "review_feedback": feedback,
        }


def _should_continue(state: AgentState) -> Literal["executor", END]:
    if state["is_complete"]:
        return END
    if state["step_count"] >= MAX_STEPS:
        return END
    if state["plan"]:
        return "executor"
    return END


workflow = StateGraph(AgentState)

workflow.add_node("planner", planner_node)
workflow.add_node("executor", executor_node)
workflow.add_node("reviewer", reviewer_node)

workflow.set_entry_point("planner")
workflow.add_edge("planner", "executor")
workflow.add_edge("executor", "reviewer")
workflow.add_conditional_edges("reviewer", _should_continue)

graph = workflow.compile(checkpointer=MemorySaver())


def _extract_preferences(query: str, plan: list, trace: list) -> dict:
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
        for step in plan:
            step_text = (step.get("step", "") + " " + step.get("tool", "")).lower()
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


async def run_graph_stream(query: str, conv_id: Optional[str] = None, images: Optional[list[dict]] = None,
                          has_uploaded_files: bool = False):
    """运行 Agent 图流水线。

    Args:
        query: 用户问题（可能包含历史对话上下文）
        conv_id: 会话 ID
        images: 当前消息上传的图片列表
        has_uploaded_files: 当前消息是否包含上传文件（由调用方显式传入，
            不能从 query 文本推断——因为历史对话中也可能包含【文件:标记）
    """
    logger.info("run_graph_stream: 开始处理 query=%s, conv_id=%s, images=%d, has_uploaded_files=%s",
                query[:50] + "..." if len(query) > 50 else query, conv_id,
                len(images) if images else 0, has_uploaded_files)
    has_images = bool(images)

    # 预计算共享上下文（文件上传、规划、no-plan fallback、summary 均复用，避免重复调用 build_context 等）
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

    if has_uploaded_files:
        # 有图片时用视觉模型，纯文本文件用普通模型
        use_vl = has_images
        active_model = VL_MODEL_NAME if use_vl else MODEL_NAME
        status_msg = "正在分析上传图片..." if use_vl else "正在分析上传文件..."
        yield {"type": "status", "message": status_msg}

        image_hint = ""
        if has_images:
            image_names = ", ".join(img["filename"] for img in images)
            image_hint = f"\n\n## 上传图片\n用户上传了 {len(images)} 张图片: {image_names}\n图片已附带在消息中，你可以直接看到图片内容。请结合图片和文本内容回答用户问题。"

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

        # 构建消息：有图片时用多模态格式，无图片时用纯文本
        if has_images:
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
        else:
            messages = [{"role": "system", "content": "你是一个专业的开发助手"}, {"role": "user", "content": direct_prompt}]

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

        await asyncio.to_thread(update_profile, _extract_preferences(query, [], []))

        yield {
            "type": "done",
            "response": full_response,
            "context_used": len(context) > 0,
            "tool_executions": [],
            "plan": [],
            "plan_steps": 0,
            "execution_trace": [],
            "is_complete": True,
            "conversation_id": conv_id or ""
        }
        return

    yield {"type": "status", "message": "正在规划任务..."}
    
    prompt = _build_planner_prompt(query, context, skill_context, cap_desc, user_profile, pending_info)
    messages = [{"role": "system", "content": "你是一个专业的任务规划师，只输出 JSON 格式"}, {"role": "user", "content": prompt}]
    
    full_content = ""
    async for chunk in await client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=TEMPERATURE_PLANNING,
        response_format={"type": "json_object"},
        stream=True
    ):
        if chunk.choices[0].delta.content:
            full_content += chunk.choices[0].delta.content
    
    try:
        content = full_content.strip()
        if content.startswith('[') and content.endswith(']'):
            plan = json.loads(content)
        else:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                # 模型可能用不同的 key 包裹步骤数组，按优先级搜索
                for key in ("steps", "plan", "tasks", "result", "actions"):
                    if key in parsed and isinstance(parsed[key], list):
                        plan = parsed[key]
                        break
                else:
                    # 兜底：找第一个 list 类型的值
                    plan = next((v for v in parsed.values() if isinstance(v, list)), [])
            else:
                plan = []
    except json.JSONDecodeError as e:
        logger.warning("plan JSON 解析失败: %s, 原始内容: %s", e, full_content[:200])
        plan = []

    if not plan:
        yield {"type": "status", "message": "正在生成回答..."}

        direct_prompt = f"""你是 GT Agent，一个本地智能开发助手。
知识库上下文: {context}
相关技能: {skill_context}
可用能力: {cap_desc}

直接回答用户问题：{query}"""

        logger.info("plan 为空，直接回答用户")

        messages = [{"role": "system", "content": "你是一个专业的开发助手"}, {"role": "user", "content": direct_prompt}]
        full_response = ""
        
        async for chunk in await client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=TEMPERATURE_CHAT,
            stream=True
        ):
            if chunk.choices[0].delta.content:
                token = chunk.choices[0].delta.content
                full_response += token
                yield {"type": "token", "content": token}
        
        await asyncio.to_thread(update_profile, _extract_preferences(query, [], []))
        
        yield {
            "type": "done",
            "response": full_response,
            "context_used": len(context) > 0,
            "tool_executions": [],
            "plan": [],
            "plan_steps": 0,
            "execution_trace": [],
            "is_complete": True,
            "conversation_id": conv_id or ""
        }
        return

    yield {"type": "plan", "steps": plan, "plan_steps": len(plan)}
    logger.info("规划完成: %d 步", len(plan))

    config = {"configurable": {"thread_id": conv_id or "default"}}
    trace = []
    total_step_count = 0  # 跨所有轮次的步骤计数
    final_state = None
    max_steps_reached = False

    async for event in graph.astream(
        {
            "messages": [{"role": "user", "content": query}],
            "plan": plan,
            "execution_results": [],
            "execution_trace": [],
            "review_feedback": "",
            "is_complete": False,
            "conv_id": conv_id or "",
            "step_count": 0
        },
        config=config
    ):
        for node, state in event.items():
            if node == "executor":
                current_trace = state.get("execution_trace", [])
                if len(current_trace) > len(trace):
                    new_steps = current_trace[len(trace):]
                    for step in new_steps:
                        total_step_count += 1
                        yield {"type": "status", "message": f"正在执行步骤 {total_step_count}: {step['step']}"}
                        yield {"type": "trace", "step": step}
                    trace = current_trace
            elif node == "reviewer":
                yield {"type": "status", "message": "正在评审结果..."}
                final_state = state
                # 评审后如果有修订计划，通知前端
                revised_plan = state.get("plan", [])
                if revised_plan and not state.get("is_complete", True):
                    yield {"type": "status", "message": f"评审发现需要补充 {len(revised_plan)} 个步骤，继续执行..."}

    if final_state:
        feedback = final_state.get("review_feedback", "")
        is_complete = final_state.get("is_complete", True)
        final_plan = final_state.get("plan", plan)
        graph_step_count = final_state.get("step_count", 0)
        # 检查是否因 MAX_STEPS 被强制结束
        if not is_complete and graph_step_count >= MAX_STEPS:
            max_steps_reached = True
    else:
        feedback = ""
        is_complete = True
        final_plan = plan

    # MAX_STEPS 强制结束时，追加提示
    if max_steps_reached:
        if feedback:
            feedback += "\n\n⚠️ 已达到最大执行轮次限制，部分任务可能未完成。"
        else:
            feedback = "已达到最大执行轮次限制，部分任务可能未完成。"

    if not feedback:
        yield {"type": "status", "message": "正在总结回答..."}

        summary_prompt = f"""总结以下任务执行结果：

用户问题: {query}

执行计划:
{json.dumps(plan, ensure_ascii=False)}

执行结果:
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
                token = chunk.choices[0].delta.content
                full_response += token
                yield {"type": "token", "content": token}
        feedback = full_response

    await asyncio.to_thread(update_profile, _extract_preferences(query, plan, trace))

    # 未完成时保存待办任务 — 使用 final_plan（可能含修订计划）
    if not is_complete and final_plan and conv_id:
        logger.info("保存待办任务: conv_id=%s, plan_steps=%d", conv_id, len(final_plan))
        await asyncio.to_thread(save_pending_task, conv_id, final_plan)

    logger.info("run_graph_stream: 完成 (is_complete=%s, steps=%d, tools=%d)", 
                is_complete, total_step_count, len(trace))

    yield {
        "type": "done",
        "response": feedback,
        "context_used": len(context) > 0,
        "tool_executions": trace,
        "plan": plan,
        "plan_steps": len(plan),
        "execution_trace": trace,
        "is_complete": is_complete,
        "conversation_id": conv_id or ""
    }
