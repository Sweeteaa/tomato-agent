"""Agent State — 核心循环状态定义

从 Planner→Executor→Reviewer 三节点模式重构为
Reasoner→Tool→Observation→MemoryUpdate→Critic 五节点循环。
"""

from typing import TypedDict, Optional


class AgentState(TypedDict):
    # 用户目标
    goal: str

    # 当前思考过程（Reasoner 的推理链）
    thought: str

    # 当前决定（{tool: str, args: dict} 或 {answer: str}）
    action: dict

    # 工具执行结果（结构化观察，由 observation_node 产出）
    # 原始字段: tool, args, result, status
    # 观察节点增强: findings, next_step_suggestion, is_sufficient
    observation: dict

    # 历史轨迹（每步记录 thought + action + observation）
    trajectory: list

    # 当前假设（Critic 产生的判断依据）
    hypothesis: list

    # 长期记忆上下文（技能、知识库、用户画像等）
    memory_context: str

    # 是否完成
    finished: bool

    # 最终回答
    answer: str

    # 循环次数
    iteration: int

    # 会话 ID（可选）
    conv_id: Optional[str]
