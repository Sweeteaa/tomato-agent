from typing import TypedDict, Literal
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from openai import OpenAI
import json

from app.config import DASHSCOPE_API_KEY, WORKSPACE_ID, MODEL_NAME, TEMPERATURE
from app.services.file_service import build_context
from app.services.memory_service import get_user_profile, update_profile
from app.services.task_service import get_pending_tasks, save_pending_task
from agent.registry.capability_registry import create_default_registry
from agent.skill_manager.manager import SkillManager

client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=f"https://{WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
)

registry = create_default_registry()
skill_manager = SkillManager()

MAX_STEPS = 5


class AgentState(TypedDict):
    messages: list
    plan: list
    execution_results: list
    execution_trace: list
    original_plan_length: int
    review_feedback: str
    is_complete: bool
    conv_id: str
    step_count: int


def _build_planner_prompt(query: str) -> str:
    context = build_context(query)
    skill_context = skill_manager.get_skill_context(query)
    capabilities = registry.list_capabilities()
    user_profile = get_user_profile()["content"]
    pending_tasks = get_pending_tasks()

    cap_desc = "\n".join(f"- {c['name']}: {c['description']}" for c in capabilities)

    pending_info = ""
    if pending_tasks["count"] > 0:
        pending_info = f"\n## 待办任务提醒\n你有 {pending_tasks['count']} 个未完成任务，请优先处理或询问用户是否继续。\n"
        for task in pending_tasks["tasks"][:3]:
            pending_info += f"- 对话 {task['id']} ({task['created_at']}): {len(task['steps'])} 个待办步骤\n"

    has_files = "文件:" in query or "【文件" in query

    needs_scan = any(keyword in query for keyword in ["扫描项目", "项目结构", "目录结构", "文件列表", "查看目录", "查找文件", "分析代码", "页面文件"])

    prompt = f"""你是 GT Agent 的规划师。根据用户问题，制定详细的执行计划。

用户问题: {query}

{pending_info}

## 用户画像
{user_profile}

## 可用能力
{cap_desc}

## 相关技能
{skill_context if skill_context else "无"}

## 知识库上下文
{context if context else "无"}

## 防幻觉规则（强制遵守）
1. 禁止猜测项目结构、目录内容、文件名
2. 禁止根据需求文档推断文件路径或内容
3. 禁止创建不存在的文件路径
4. 禁止根据目录名称推断业务功能（如不能因目录名包含"data"就推断它是"实验室检查"页面）
5. 当用户要求扫描项目、查看目录结构、分析代码时，必须调用 list_dir / read_file / search_file 工具获取真实结果
6. 扫描项目结构时，**必须先调用 list_dir 工具**获取目录结构信息，建议使用足够的深度（max_depth=5-10）
7. list_dir 必须使用足够的深度（建议 max_depth=5-10），确保扫描到深层目录结构
8. 如果工具没有返回结果，只能回答"无法访问本地文件系统，请检查路径是否正确或提供扫描权限"
9. list_dir 的 path 参数必须是真实存在的绝对路径，如 'D:/projects/xxx'

## 重要提示
{"用户已上传文件，文件内容已包含在用户问题中，请直接根据文件内容回答，不需要再调用 read_file 工具读取文件。" if has_files else ""}
{"用户要求扫描项目或查看文件，必须调用 list_dir 或 read_file 工具获取真实文件系统结果，禁止编造目录结构或文件内容。" if needs_scan else ""}

## 要求
1. 如果需要调用工具，将任务分解为多个步骤，每个步骤明确调用什么工具
2. 如果不需要调用工具，直接回答即可，输出空数组 []
3. 路径参数是相对于 workspace 的相对路径，不需要加 workspace 前缀
4. 输出格式必须是 JSON 数组，包含步骤描述和工具名称：
   [
     {{
       "step": "步骤描述",
       "tool": "工具名称（如 read_file, write_file, list_dir）",
       "args": {{参数键值}}
     }}
   ]"""

    return prompt


def _build_reviewer_prompt(plan: list, results: list, query: str) -> str:
    return f"""评审执行结果：

用户问题: {query}

执行计划:
{json.dumps(plan, ensure_ascii=False)}

执行结果:
{json.dumps(results, ensure_ascii=False)}

## 要求
1. 判断任务是否已完成
2. 如果已完成，总结执行结果给用户
3. 如果未完成但已尽力，也要总结当前结果

输出格式必须是 JSON：
{{
  "is_complete": true,
  "feedback": "总结结果给用户"
}}"""


def planner_node(state: AgentState) -> AgentState:
    query = state["messages"][-1]["content"]
    
    has_uploaded_files = "【文件:" in query or "以下是上传的文件内容" in query
    
    if has_uploaded_files:
        context = build_context(query)
        skill_context = skill_manager.get_skill_context(query)
        capabilities = registry.list_capabilities()
        cap_desc = "\n".join(f"- {c['name']}: {c['description']}" for c in capabilities)

        direct_prompt = f"""你是 GT Agent，一个本地智能开发助手。

## 防幻觉规则（强制遵守）
1. 禁止猜测项目结构、目录内容、文件名
2. 禁止根据需求文档推断文件路径或内容
3. 禁止创建不存在的文件路径
4. 禁止根据目录名称推断业务功能（如不能因目录名包含"data"就推断它是"实验室检查"页面）
5. 如果需要查看文件内容或目录结构，必须通过工具获取，禁止编造
6. 扫描项目结构时，必须先调用 list_dir 工具获取目录结构信息

知识库上下文: {context}
相关技能: {skill_context}
可用能力: {cap_desc}

用户已上传文件，文件内容已包含在问题中，请直接根据文件内容回答用户问题：
{query}"""

        direct_messages = [{"role": "system", "content": "你是一个专业的开发助手"}, {"role": "user", "content": direct_prompt}]
        direct_completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=direct_messages,
            temperature=TEMPERATURE,
        )

        return {
            **state,
            "plan": [],
            "execution_results": [],
            "execution_trace": [],
            "original_plan_length": 0,
            "review_feedback": direct_completion.choices[0].message.content,
            "is_complete": True,
            "step_count": 0
        }

    prompt = _build_planner_prompt(query)

    messages = [{"role": "system", "content": "你是一个专业的任务规划师，只输出 JSON 格式"}, {"role": "user", "content": prompt}]

    completion = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=TEMPERATURE,
        response_format={"type": "json_object"}
    )

    try:
        content = completion.choices[0].message.content.strip()
        if content.startswith('[') and content.endswith(']'):
            plan = json.loads(content)
        else:
            parsed = json.loads(content)
            plan = parsed.get("steps", []) if isinstance(parsed, dict) else []
    except json.JSONDecodeError:
        plan = []

    if not plan:
        context = build_context(query)
        skill_context = skill_manager.get_skill_context(query)
        capabilities = registry.list_capabilities()
        cap_desc = "\n".join(f"- {c['name']}: {c['description']}" for c in capabilities)

        direct_prompt = f"""你是 GT Agent，一个本地智能开发助手。
知识库上下文: {context}
相关技能: {skill_context}
可用能力: {cap_desc}

直接回答用户问题：{query}"""

        direct_messages = [{"role": "system", "content": "你是一个专业的开发助手"}, {"role": "user", "content": direct_prompt}]
        direct_completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=direct_messages,
            temperature=TEMPERATURE,
        )

        return {
            **state,
            "plan": [],
            "execution_results": [],
            "execution_trace": [],
            "original_plan_length": 0,
            "review_feedback": direct_completion.choices[0].message.content,
            "is_complete": True,
            "step_count": 0
        }

    return {**state, "plan": plan, "execution_results": [], "execution_trace": [], "original_plan_length": len(plan), "review_feedback": "", "is_complete": False, "step_count": 0}


def _generate_streaming_response(prompt: str, system_msg: str = "你是一个专业的开发助手"):
    messages = [{"role": "system", "content": system_msg}, {"role": "user", "content": prompt}]
    
    for chunk in client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=TEMPERATURE,
        stream=True
    ):
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def _parse_plan_from_stream(query: str) -> list:
    prompt = _build_planner_prompt(query)
    messages = [{"role": "system", "content": "你是一个专业的任务规划师，只输出 JSON 格式"}, {"role": "user", "content": prompt}]
    
    full_content = ""
    for chunk in client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=TEMPERATURE,
        response_format={"type": "json_object"},
        stream=True
    ):
        if chunk.choices[0].delta.content:
            full_content += chunk.choices[0].delta.content
            yield {"type": "status", "message": "正在规划任务..."}
    
    try:
        content = full_content.strip()
        if content.startswith('[') and content.endswith(']'):
            return json.loads(content)
        else:
            parsed = json.loads(content)
            return parsed.get("steps", []) if isinstance(parsed, dict) else []
    except json.JSONDecodeError:
        return []


def executor_node(state: AgentState) -> AgentState:
    plan = state["plan"]
    results = []
    trace = state.get("execution_trace", [])

    for step in plan:
        if "tool" in step and step["tool"]:
            try:
                args = step.get("args", {})
                result = registry.execute_tool(step["tool"], args)
                results.append({"step": step["step"], "tool": step["tool"], "result": result})
                trace.append({
                    "step": step["step"],
                    "tool": step["tool"],
                    "args": args,
                    "result": result,
                    "status": "success"
                })
            except Exception as e:
                error_msg = f"❌ 执行失败: {str(e)}"
                results.append({"step": step["step"], "tool": step["tool"], "result": error_msg})
                trace.append({
                    "step": step["step"],
                    "tool": step["tool"],
                    "args": step.get("args", {}),
                    "result": error_msg,
                    "status": "error"
                })

    return {**state, "execution_results": results, "execution_trace": trace, "step_count": state["step_count"] + 1}


def reviewer_node(state: AgentState) -> AgentState:
    plan = state["plan"]
    results = state["execution_results"]
    query = state["messages"][-1]["content"]

    if not results:
        return {**state, "is_complete": True}

    prompt = _build_reviewer_prompt(plan, results, query)

    messages = [{"role": "system", "content": "你是一个专业的评审员，只输出 JSON 格式"}, {"role": "user", "content": prompt}]

    completion = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=TEMPERATURE,
        response_format={"type": "json_object"}
    )

    try:
        review = json.loads(completion.choices[0].message.content)
        feedback = review.get("feedback", "")
    except json.JSONDecodeError:
        feedback = completion.choices[0].message.content

    return {
        **state,
        "is_complete": True,
        "review_feedback": feedback
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


def run_graph_stream(query: str, conv_id: str = None):
    has_uploaded_files = "【文件:" in query or "以下是上传的文件内容" in query
    
    if has_uploaded_files:
        yield {"type": "status", "message": "正在分析上传文件..."}
        
        context = build_context(query)
        skill_context = skill_manager.get_skill_context(query)
        capabilities = registry.list_capabilities()
        cap_desc = "\n".join(f"- {c['name']}: {c['description']}" for c in capabilities)

        direct_prompt = f"""你是 GT Agent，一个本地智能开发助手。

## 防幻觉规则（强制遵守）
1. 禁止猜测项目结构、目录内容、文件名
2. 禁止根据需求文档推断文件路径或内容
3. 禁止创建不存在的文件路径
4. 禁止根据目录名称推断业务功能（如不能因目录名包含"data"就推断它是"实验室检查"页面）
5. 如果需要查看文件内容或目录结构，必须通过工具获取，禁止编造
6. 扫描项目结构时，必须先调用 scan_menu_structure 工具获取菜单和路由信息

知识库上下文: {context}
相关技能: {skill_context}
可用能力: {cap_desc}

用户已上传文件，文件内容已包含在问题中，请直接根据文件内容回答用户问题：
{query}"""

        yield {"type": "status", "message": "正在生成回答..."}
        
        messages = [{"role": "system", "content": "你是一个专业的开发助手"}, {"role": "user", "content": direct_prompt}]
        full_response = ""
        
        for chunk in client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=TEMPERATURE,
            stream=True
        ):
            if chunk.choices[0].delta.content:
                token = chunk.choices[0].delta.content
                full_response += token
                yield {"type": "token", "content": token}
        
        update_profile(_extract_preferences(query, [], []))
        
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
    
    prompt = _build_planner_prompt(query)
    messages = [{"role": "system", "content": "你是一个专业的任务规划师，只输出 JSON 格式"}, {"role": "user", "content": prompt}]
    
    full_content = ""
    for chunk in client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=TEMPERATURE,
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
            plan = parsed.get("steps", []) if isinstance(parsed, dict) else []
    except json.JSONDecodeError:
        plan = []

    if not plan:
        yield {"type": "status", "message": "正在生成回答..."}
        
        context = build_context(query)
        skill_context = skill_manager.get_skill_context(query)
        capabilities = registry.list_capabilities()
        cap_desc = "\n".join(f"- {c['name']}: {c['description']}" for c in capabilities)

        direct_prompt = f"""你是 GT Agent，一个本地智能开发助手。
知识库上下文: {context}
相关技能: {skill_context}
可用能力: {cap_desc}

直接回答用户问题：{query}"""

        messages = [{"role": "system", "content": "你是一个专业的开发助手"}, {"role": "user", "content": direct_prompt}]
        full_response = ""
        
        for chunk in client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=TEMPERATURE,
            stream=True
        ):
            if chunk.choices[0].delta.content:
                token = chunk.choices[0].delta.content
                full_response += token
                yield {"type": "token", "content": token}
        
        update_profile(_extract_preferences(query, [], []))
        
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

    config = {"configurable": {"thread_id": conv_id or "default"}}
    trace = []
    step_count = 0
    final_state = None

    for event in graph.stream(
        {
            "messages": [{"role": "user", "content": query}],
            "plan": plan,
            "execution_results": [],
            "execution_trace": [],
            "original_plan_length": len(plan),
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
                        step_count += 1
                        yield {"type": "status", "message": f"正在执行步骤 {step_count}/{len(plan)}: {step['step']}"}
                        yield {"type": "trace", "step": step}
                    trace = current_trace
            elif node == "reviewer":
                yield {"type": "status", "message": "正在评审结果..."}
                final_state = state

    if final_state:
        feedback = final_state.get("review_feedback", "")
        is_complete = final_state.get("is_complete", True)
    else:
        feedback = ""
        is_complete = True

    if not feedback:
        yield {"type": "status", "message": "正在总结回答..."}
        
        context = build_context(query)
        cap_desc = "\n".join(f"- {c['name']}: {c['description']}" for c in registry.list_capabilities())
        
        summary_prompt = f"""总结以下任务执行结果：

用户问题: {query}

执行计划:
{json.dumps(plan, ensure_ascii=False)}

执行结果:
{json.dumps(trace, ensure_ascii=False)}

请用自然语言总结给用户。"""

        messages = [{"role": "system", "content": "你是一个专业的开发助手"}, {"role": "user", "content": summary_prompt}]
        full_response = ""
        
        for chunk in client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=TEMPERATURE,
            stream=True
        ):
            if chunk.choices[0].delta.content:
                token = chunk.choices[0].delta.content
                full_response += token
                yield {"type": "token", "content": token}
        feedback = full_response

    update_profile(_extract_preferences(query, plan, trace))
    
    if not is_complete and plan and conv_id:
        save_pending_task(conv_id, plan)

    yield {
        "type": "done",
        "response": feedback,
        "context_used": len(build_context(query)) > 0,
        "tool_executions": trace,
        "plan": plan,
        "plan_steps": len(plan),
        "execution_trace": trace,
        "is_complete": is_complete,
        "conversation_id": conv_id or ""
    }
