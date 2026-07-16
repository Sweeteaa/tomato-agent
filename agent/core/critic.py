"""Critic — 评判节点

核心职责：三个问题
  1. 正确性 — 回答是否有依据？
  2. 完整性 — 是否遗漏关键步骤？
  3. 下一步   — 是否需要继续探索？

输出示例:
  {
    "score": 8,
    "issues": ["没有验证接口"],
    "continue": true,
    "suggestion": "检查axios配置"
  }

score: 0-10，10=完全解决，0=毫无进展
issues: 发现的问题列表
continue: 是否需要继续推理
suggestion: 如果继续，建议下一步做什么
"""

import json
import logging

from agent.core.state import AgentState
from app.config import MODEL_NAME, TEMPERATURE_PLANNING, MAX_STEPS

logger = logging.getLogger("gt_agent.core.critic")


def build_critic_prompt(
    goal: str,
    trajectory: list,
    iteration: int,
    max_steps: int,
) -> str:
    """构建 Critic 的提示词 — 三问评判"""
    if trajectory:
        traj_lines = []
        for i, step in enumerate(trajectory):
            thought = step.get("thought", "")
            action = step.get("action", {})
            obs = step.get("observation", {})
            # 优先展示结构化观察
            obs_text = obs.get("findings", "") or str(obs.get("result", ""))
            if len(obs_text) > 500:
                obs_text = obs_text[:500] + "...[已截断]"
            status = obs.get("status", "unknown")
            traj_lines.append(
                f"  {i+1}. [{status}] 思考: {thought} → 动作: {json.dumps(action, ensure_ascii=False)} → 观察: {obs_text}"
            )
        traj_str = "\n".join(traj_lines)
    else:
        traj_str = "  （暂无执行记录）"

    remaining = max_steps - iteration

    return f"""你是 GT Agent 的评判器（Critic）。对当前执行轨迹进行三问评判。

## 用户目标
{goal}

## 执行轨迹（第 {iteration} 轮，剩余 {remaining} 轮）
{traj_str}

## 三问评判

### 1. 正确性 — 回答是否有依据？
- 每个结论是否有工具返回的数据支撑？
- 是否存在无依据的推断？

### 2. 完整性 — 是否遗漏关键步骤？
- 目标中的每个子问题是否都被涉及？
- 是否有遗漏的关键文件、配置、接口？

### 3. 下一步 — 是否需要继续探索？
- 当前信息是否足以回答用户目标？
- 如果不够，最关键的下一步是什么？

## 评判规则（严格执行）
- **continue = false 的条件（满足任一即可）**:
  1. score ≥ 8 且 issues 为空或仅含次要问题
  2. 已获取项目核心信息（技术栈、目录结构、入口文件、路由配置）中的 3 项以上
  3. 剩余轮次 ≤ 3 时，如果当前已有足够信息给出部分回答
  4. 用户目标已基本达成（即使还有次要信息缺失）

- **continue = true 的条件（需要同时满足）**:
  1. score < 7
  2. 缺失的信息是回答用户目标的核心依赖（非锦上添花）

- **禁止行为**:
  - 不要因为"还可以了解更多"而继续
  - 不要追求完美，80%信息足够就停止
  - 不要重复扫描已扫描的内容
  - 不要深入分析单个组件的内部实现（除非用户明确要求）

## 输出格式（严格 JSON）
{{
  "score": 8,
  "issues": ["问题1", "问题2"],
  "continue": false,
  "suggestion": "如果继续，建议下一步做什么；如果完成，写'已完成'"
}}

- score: 0-10 整数，10=完全解决
- issues: 发现的问题列表（空列表=无问题）
- continue: 是否继续推理
- suggestion: 下一步建议或完成说明"""


async def critique(state: AgentState, client, prompt_builder=None) -> dict:
    """Critic 核心函数 — 三问评判 + 轨迹记录

    Args:
        state: 当前 Agent 状态
        client: AsyncOpenAI 客户端
        prompt_builder: 可选的 prompt 构建闭包

    Returns:
        部分状态更新: {finished, hypothesis, answer, trajectory, iteration}
    """
    finished = state.get("finished", False)
    iteration = state.get("iteration", 0)
    answer = state.get("answer", "")

    trajectory = list(state.get("trajectory", []))
    trajectory.append({
        "thought": state.get("thought", ""),
        "action": state.get("action", {}),
        "observation": state.get("observation", {}),
    })

    # Reasoner 已经判定完成
    if finished:
        logger.info("critic: Reasoner 已判定完成 (iter=%d)", iteration)
        return {
            "finished": True,
            "hypothesis": ["Reasoner 判定完成"],
            "trajectory": trajectory,
            "iteration": iteration + 1,
        }

    # 达到最大步数 → 强制结束
    if iteration >= MAX_STEPS:
        logger.warning("critic: 达到 MAX_STEPS=%d，强制完成", MAX_STEPS)
        return {
            "finished": True,
            "hypothesis": [f"达到最大轮次限制 {MAX_STEPS}"],
            "answer": "已达到最大执行轮次限制，部分任务可能未完成。",
            "trajectory": trajectory,
            "iteration": iteration + 1,
        }

    # 收敛规则：剩余轮次 ≤ 3 时，如果已有足够信息，强制完成
    remaining_steps = MAX_STEPS - iteration
    if remaining_steps <= 3 and iteration >= 3:
        # 检查是否已有足够的工具调用结果
        valid_results = sum(1 for t in trajectory if t.get("observation", {}).get("status") == "success")
        if valid_results >= 2:
            logger.info("critic: 收敛规则触发 (iter=%d, valid_results=%d, remaining=%d)", iteration, valid_results, remaining_steps)
            return {
                "finished": True,
                "hypothesis": [f"收敛规则: 已有 {valid_results} 个有效结果，剩余轮次不足"],
                "trajectory": trajectory,
                "iteration": iteration + 1,
            }

    # 调用 LLM 评判（使用已更新的 trajectory）
    goal = state["goal"]

    if prompt_builder:
        prompt = prompt_builder(goal, trajectory, iteration)
    else:
        prompt = build_critic_prompt(goal, trajectory, iteration, MAX_STEPS)

    messages = [
        {"role": "system", "content": "你是 GT Agent 的评判器，只输出 JSON 格式"},
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
        score = result.get("score", 5)
        issues = result.get("issues", [])
        should_continue = result.get("continue", False)
        suggestion = result.get("suggestion", "")
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("critic: JSON 解析失败 (%s)，默认继续", e)
        score = 5
        issues = ["JSON 解析失败"]
        should_continue = True
        suggestion = ""

    # 构造 hypothesis（包含评判结果）
    hypothesis = [
        f"score={score}",
        *issues,
    ]

    if not should_continue:
        logger.info("critic: 判定完成 (iter=%d, score=%d): %s", iteration, score, suggestion)
        return {
            "finished": True,
            "hypothesis": hypothesis,
            "trajectory": trajectory,
            "iteration": iteration + 1,
        }
    else:
        logger.info("critic: 判定继续 (iter=%d, score=%d, issues=%s): %s",
                    iteration, score, issues, suggestion)
        return {
            "finished": False,
            "hypothesis": hypothesis,
            "trajectory": trajectory,
            "iteration": iteration + 1,
        }
