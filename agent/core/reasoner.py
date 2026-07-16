"""Reasoner — 推理节点

核心职责：根据当前状态（目标 + 轨迹 + 最新观察）决定下一步 Action。

与旧 Planner 的区别：
  - Planner: 一次性生成完整计划（所有步骤）
  - Reasoner: 每次只决定一步（工具调用 或 最终回答）

示例输入:
  目标: 分析 Vue 项目登录失败
  当前: 还没有项目结构

示例输出:
  {
    "thought": "我需要先了解项目结构",
    "action": {"tool": "scan_project", "args": {"project_path": "/xxx"}},
    "finished": false
  }
"""

import json
import logging

from agent.core.state import AgentState
from app.config import MODEL_NAME, TEMPERATURE_PLANNING

logger = logging.getLogger("gt_agent.core.reasoner")

# ─── 工具列表（供 prompt 使用） ───

TOOL_LIST = """- read_file(path, max_size) — 读取文件内容
- list_dir(path, recursive, max_depth) — 列出目录内容
- search_file(keyword, root_path, file_extensions, context_lines, max_results) — 搜索项目源码
- scan_menu_structure(project_path) — 扫描菜单和路由配置
- project_discover(project_path 或 name) — 轻量级项目发现（快速识别技术栈）
- scan_project(project_path 或 name, full_scan) — 深度扫描项目结构
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
- delete_memory(name) — 删除记忆"""


TOOL_POLICY = """## 工具使用规则（强制遵守）

### 项目分析流程（必须遵循）
1. 第一步：使用 list_dir(root, max_depth=5) 获取项目根目录结构
2. 第二步：使用 project_discover(project_path) 识别技术栈和主要目录
3. 第三步：使用 scan_menu_structure(project_path) 获取路由和菜单信息
4. 按需：使用 search_file(keyword, root_path) 搜索具体业务代码
5. 最后：使用 read_file(path) 精读相关文件

### 禁止规则
- 禁止直接调用 scan_project(full_scan=true) — 会导致扫描过慢甚至超时
- 禁止在未了解项目结构前直接调用 scan_project — 应先用 project_discover
- 禁止猜测目录结构或文件内容 — 必须调用工具获取真实结果
- 禁止在未定位到具体文件前读取大量文件 — 应先用 search_file 精确定位

### 工具选择优先级
- 快速了解项目 → project_discover（< 1秒）
- 查看目录结构 → list_dir
- 查找业务代码 → search_file（最精准）
- 获取路由信息 → scan_menu_structure
- 深度分析架构 → scan_project（仅在必要时）
- 精读具体文件 → read_file"""


def build_reasoner_prompt(
    goal: str,
    trajectory: list,
    observation: dict,
    memory_context: str,
    cap_desc: str,
    iteration: int,
    max_steps: int,
    anti_hallucination_rules: str,
) -> str:
    """构建 Reasoner 的提示词 — 聚焦「根据当前状态决定下一步」"""

    # 格式化历史轨迹
    if trajectory:
        traj_lines = []
        for i, step in enumerate(trajectory):
            thought = step.get("thought", "")
            action = step.get("action", {})
            obs = step.get("observation", {})
            # 优先展示结构化观察（findings），其次 raw result
            obs_insight = obs.get("findings", "") or str(obs.get("result", ""))
            if len(obs_insight) > 500:
                obs_insight = obs_insight[:500] + "...[已截断]"
            traj_lines.append(
                f"  {i+1}. 思考: {thought}\n"
                f"     动作: {json.dumps(action, ensure_ascii=False)}\n"
                f"     观察: {obs_insight}"
            )
        traj_str = "\n".join(traj_lines)
    else:
        traj_str = "  （暂无执行记录）"

    # 格式化最新观察（observation_node 产出的结构化结果）
    if observation:
        obs_tool = observation.get("tool", "")
        obs_status = observation.get("status", "unknown")
        obs_findings = observation.get("findings", "")
        obs_suggestion = observation.get("next_step_suggestion", "")
        obs_raw = str(observation.get("result", ""))
        if len(obs_raw) > 300:
            obs_raw = obs_raw[:300] + "...[已截断]"

        obs_parts = [f"最新工具: {obs_tool} ({obs_status})"]
        if obs_findings:
            obs_parts.append(f"发现: {obs_findings}")
        if obs_suggestion:
            obs_parts.append(f"建议下一步: {obs_suggestion}")
        obs_parts.append(f"原始结果: {obs_raw}")
        obs_str = "\n".join(obs_parts)
    else:
        obs_str = "  （首次推理，尚无观察）"

    remaining = max_steps - iteration

    return f"""你是开发 Agent 的推理引擎。根据目标、历史轨迹和当前观察，决定下一步动作。

## 目标
{goal}

## 长期记忆上下文
{memory_context}

## 可用能力
{cap_desc}

## 可用工具（只能使用以下工具）
{TOOL_LIST}

**禁止使用不在上述列表中的工具名**

{TOOL_POLICY}

## 历史轨迹（第 {iteration} 轮，剩余 {remaining} 轮）
{traj_str}

## 当前观察
{obs_str}

{anti_hallucination_rules}

## 路径规则
- 扫描用户项目: 使用绝对路径，如 list_dir(path='/Users/xxx/projects/xxx')
- workspace 内操作: 使用相对路径，如 write_file(path='skill/hello.md')

## 输出格式（严格 JSON）
如果需要调用工具：
{{
  "thought": "你的推理过程",
  "action": {{
    "tool": "工具名称",
    "args": {{"参数名": "参数值"}}
  }},
  "finished": false,
  "answer": ""
}}

如果已收集到足够信息，直接给出最终回答：
{{
  "thought": "你的推理过程",
  "action": {{}},
  "finished": true,
  "answer": "最终回答"
}}"""


async def reason(state: AgentState, client, prompt_builder=None) -> dict:
    """Reasoner 核心函数 — 推理并决定下一步 Action

    Args:
        state: 当前 Agent 状态
        client: AsyncOpenAI 客户端
        prompt_builder: 可选的 prompt 构建闭包（由 graph_service 注入上下文）

    Returns:
        部分状态更新: {thought, action, finished, answer}
    """
    goal = state["goal"]
    trajectory = state.get("trajectory", [])
    observation = state.get("observation", {})
    memory_context = state.get("memory_context", "")
    iteration = state.get("iteration", 0)

    # 使用外部传入的 prompt_builder 或默认
    if prompt_builder:
        prompt = prompt_builder(goal, trajectory, observation, memory_context, iteration)
    else:
        prompt = build_reasoner_prompt(
            goal, trajectory, observation, memory_context,
            "", iteration, 10, ""
        )

    messages = [
        {"role": "system", "content": "你是开发 Agent 的推理引擎，只输出 JSON 格式"},
        {"role": "user", "content": prompt},
    ]

    completion = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=TEMPERATURE_PLANNING,
        response_format={"type": "json_object"},
    )

    try:
        result = json.loads(completion.choices[0].message.content)
        thought = result.get("thought", "")
        action = result.get("action", {})
        finished = result.get("finished", False)
        answer = result.get("answer", "")
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("reasoner: JSON 解析失败 (%s)，默认直接回答", e)
        thought = "解析失败，直接回答"
        action = {}
        finished = True
        answer = completion.choices[0].message.content

    logger.info("reasoner: thought=%s, action=%s, finished=%s, iter=%d",
                thought[:80], json.dumps(action, ensure_ascii=False)[:100], finished, iteration)

    return {
        "thought": thought,
        "action": action,
        "finished": finished,
        "answer": answer,
    }
