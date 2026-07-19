"""Agent 运行配置与结果数据类"""

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class AgentRunSpec:
    """Agent 运行配置"""
    initial_messages: list[dict]
    tools: list[dict]  # OpenAI function calling 格式
    tool_handlers: dict[str, Callable]
    max_iterations: int = 10
    tool_timeout: int = 30
    on_tool_start: Callable | None = None
    on_tool_end: Callable | None = None
    on_thought: Callable | None = None  # 推理模型思考链回调
    plan: dict | None = None  # 可选：Planner 生成的执行计划
    on_plan_progress: Callable | None = None  # 计划进度回调
    enable_thinking: bool = False  # 是否启用推理模型展示思考链
    reasoning_model: str | None = None  # 推理模型名称


@dataclass
class AgentRunResult:
    """Agent 运行结果"""
    final_content: str | None
    messages: list[dict]
    tools_used: list[str] = field(default_factory=list)
    stop_reason: str = "completed"  # "completed" / "max_iterations" / "error"
    error: str | None = None
    plan: dict | None = None
    plan_steps_completed: int = 0
    reasoning: str | None = None  # 本轮回路的思考链内容
