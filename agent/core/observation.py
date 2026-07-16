"""Observation — 观察节点（环境理解）

这是 Agent 模式和 Workflow 模式最大的区别:

  Workflow: 工具结果 → Reviewer（机械评审）
  Agent:    工具结果 → Observation（智能观察/环境理解）→ 重新思考

Observation 节点的作用:
1. 整理工具的原始返回，提取关键发现（findings）
2. 提炼事实（facts）—— 可用于后续推理的结构化知识
3. 生成新问题（new_questions）—— 基于当前结果需要进一步探索的问题
4. 生成下一步建议，引导 Reasoner 更高效推理
5. 将非结构化的工具输出转化为 Agent 友好的结构化观察

示例:
  工具返回: {"files": ["src/router/index.js", "src/store/user.js"]}
  Observation: {
    "findings": "项目使用 Vue2，路由在 src/router/index.js，用户状态在 src/store/user.js",
    "facts": [
      "这是 Vue2 项目",
      "路由配置位于 src/router/index.js",
      "用户状态管理位于 src/store/user.js"
    ],
    "new_questions": [
      "路由中是否有登录相关的守卫？",
      "用户状态中是否包含登录态？"
    ],
    "next_step_suggestion": "检查 router 动态加载和登录相关组件",
    "tool": "scan_project",
    "status": "success",
    "result": <原始结果>
  }
"""

import json
import logging

from agent.core.state import AgentState
from app.config import MODEL_NAME, TEMPERATURE_PLANNING

logger = logging.getLogger("gt_agent.core.observation")


def build_observation_prompt(
    goal: str,
    thought: str,
    action: dict,
    raw_result: str,
    tool_status: str,
    trajectory: list,
) -> str:
    """构建 Observation 节点的提示词"""

    # 格式化之前轨迹的摘要（只显示最近3步）
    recent_steps = trajectory[-3:] if trajectory else []
    if recent_steps:
        recent_lines = []
        for i, step in enumerate(recent_steps):
            s_thought = step.get("thought", "")[:60]
            s_action = step.get("action", {})
            s_tool = s_action.get("tool", "N/A")
            recent_lines.append(f"  {i+1}. [{s_tool}] {s_thought}")
        recent_str = "\n".join(recent_lines)
    else:
        recent_str = "  （首次执行）"

    # 截断原始结果避免过长
    if len(raw_result) > 2000:
        raw_display = raw_result[:2000] + f"\n...[已截断，完整结果共 {len(raw_result)} 字符]"
    else:
        raw_display = raw_result

    return f"""你是开发 Agent 的观察分析器（环境理解模块）。整理工具返回的结果，理解环境变化，为后续推理提供结构化输入。

## 用户目标
{goal}

## 当前推理
思考: {thought}
动作: {json.dumps(action, ensure_ascii=False)}
执行状态: {tool_status}

## 工具原始返回
{raw_display}

## 最近轨迹
{recent_str}

## 你的任务（环境理解）
1. **提取关键发现** — 用简洁自然语言描述你看到了什么
2. **提炼事实（facts）** — 将发现转化为可复用的结构化知识，供后续推理使用
3. **生成新问题（new_questions）** — 基于当前结果，还有哪些问题需要进一步探索
4. **判断充分性** — 当前结果是否足够回答目标
5. **建议下一步** — 如果不够，建议下一步应该做什么

## 输出格式（严格 JSON）
{{
  "findings": "从工具结果中提取的关键发现（简洁自然语言，1-2句话）",
  "facts": ["事实1", "事实2", "事实3"],
  "new_questions": ["问题1", "问题2"],
  "next_step_suggestion": "建议下一步操作（如：读取 src/router/index.js 了解路由配置）",
  "is_sufficient": false
}}

- findings: 简洁描述观察到的关键信息，对目标的意义
- facts: 从结果中提炼的结构化知识，每条一个独立事实，便于后续推理引用
- new_questions: 根据当前发现生成的待探索问题列表
- next_step_suggestion: 如果信息不够，建议下一步做什么；如果已足够，写"已收集到足够信息"
- is_sufficient: 当前观察 + 历史轨迹是否已足够回答用户目标"""


async def observe(state: AgentState, client, prompt_builder=None) -> dict:
    """Observation 节点 — 整理工具返回为结构化观察

    流程:
    1. 读取 state["observation"]（工具原始结果）
    2. 如果是 skipped/error，直接透传
    3. 调用 LLM 分析原始结果，提取 findings + next_step_suggestion
    4. 更新 observation 为结构化格式

    Args:
        state: 当前 Agent 状态
        client: AsyncOpenAI 客户端
        prompt_builder: 可选的 prompt 构建闭包

    Returns:
        部分状态更新: {"observation": {...结构化观察...}}
    """
    observation = state.get("observation", {})
    tool_status = observation.get("status", "unknown")

    # 无需分析的观察直接透传
    if tool_status in ("skipped",):
        logger.debug("observe: 跳过观察 (status=%s)", tool_status)
        return {}

    # 错误结果也做简单结构化
    if tool_status == "error":
        error_result = observation.get("result", "")
        observation["findings"] = f"工具执行失败: {error_result}"
        observation["next_step_suggestion"] = "可以尝试其他工具或调整参数"
        observation["is_sufficient"] = False
        return {"observation": observation}

    # 成功结果 → 调用 LLM 分析
    goal = state["goal"]
    thought = state.get("thought", "")
    action = state.get("action", {})
    raw_result = str(observation.get("result", ""))
    trajectory = state.get("trajectory", [])

    if prompt_builder:
        prompt = prompt_builder(goal, thought, action, raw_result, tool_status, trajectory)
    else:
        prompt = build_observation_prompt(goal, thought, action, raw_result, tool_status, trajectory)

    messages = [
        {"role": "system", "content": "你是开发 Agent 的观察分析器，只输出 JSON 格式"},
        {"role": "user", "content": prompt},
    ]

    try:
        completion = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=TEMPERATURE_PLANNING,
            response_format={"type": "json_object"},
        )
        result = json.loads(completion.choices[0].message.content)
        findings = result.get("findings", "")
        facts = result.get("facts", [])
        new_questions = result.get("new_questions", [])
        suggestion = result.get("next_step_suggestion", "")
        is_sufficient = result.get("is_sufficient", False)
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("observe: JSON 解析失败 (%s)，使用原始结果", e)
        findings = ""
        facts = []
        new_questions = []
        suggestion = ""
        is_sufficient = False

    # 将结构化观察写入 observation
    observation["findings"] = findings
    observation["facts"] = facts
    observation["new_questions"] = new_questions
    observation["next_step_suggestion"] = suggestion
    observation["is_sufficient"] = is_sufficient

    logger.info("observe: findings=%s, facts=%d, questions=%d, suggestion=%s, sufficient=%s",
                findings[:80] if findings else "(空)",
                len(facts),
                len(new_questions),
                suggestion[:80] if suggestion else "(空)",
                is_sufficient)

    return {"observation": observation}
