"""Agent Core Nodes — 图节点入口 + 条件边

节点实现已拆分到独立文件:
  - reasoner.py:   推理节点（决定下一步 Action）
  - tool_runner.py: 工具执行节点（一次执行一个 action）
  - observation.py: 观察节点（整理工具返回为结构化观察）
  - critic.py:     评判节点（三问评判: 正确性/完整性/下一步）+ 轨迹记录

本文件保留:
  - should_use_tool / should_continue: 条件边
"""

import logging
from typing import Literal

from langgraph.graph import END

from agent.core.state import AgentState
from agent.core.reasoner import reason as reasoner_node, build_reasoner_prompt
from agent.core.tool_runner import execute_action as tool_node
from agent.core.observation import observe as observation_node, build_observation_prompt
from agent.core.critic import critique as critic_node, build_critic_prompt
from app.config import MAX_STEPS

logger = logging.getLogger("gt_agent.core.nodes")


# ─── 条件边 ───

def should_use_tool(state: AgentState) -> Literal["tool", "critic"]:
    """条件边：Reasoner 之后，是否需要执行工具？

    - action 中有 tool → 执行 tool 节点
    - finished 或无 tool → 跳过 tool+observer，直接进入 critic（含轨迹记录）
    """
    action = state.get("action", {})
    if state.get("finished", False) or not action.get("tool"):
        return "critic"
    return "tool"


def should_continue(state: AgentState) -> Literal["reasoner", END]:
    """条件边：Critic 之后，是否继续推理？

    - finished → END
    - iteration >= MAX_STEPS → END
    - 否则 → 回到 reasoner
    """
    if state.get("finished", False):
        return END
    if state.get("iteration", 0) >= MAX_STEPS:
        return END
    return "reasoner"
