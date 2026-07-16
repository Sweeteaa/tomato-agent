"""Tool Runner — 工具执行节点

核心职责：一次只执行一个 action（从 state["action"] 读取）。

与旧 Executor 的区别：
  - Executor: 遍历整个 plan 列表，批量执行所有步骤
  - Tool Runner: 每次只执行一个 action，结果存入 observation

关键改进：
  - 使用 asyncio.to_thread 隔离同步阻塞操作，防止 event loop 冻结
  - 使用 asyncio.wait_for 设置超时（30秒），防止工具无限等待

示例:
  state["action"] = {"tool": "scan_project", "args": {"project_path": "/xxx"}}
  → 执行 registry.execute_tool("scan_project", {"project_path": "/xxx"})
  → 返回 {"observation": {"tool": "scan_project", "args": {...}, "result": "...", "status": "success"}}
"""

import json
import logging
import asyncio

from agent.core.state import AgentState
from agent.registry.capability_registry import CapabilityRegistry
from agent.exceptions import ToolError

logger = logging.getLogger("gt_agent.core.tool_runner")

TOOL_TIMEOUT = 30


async def execute_action(state: AgentState, registry: CapabilityRegistry) -> dict:
    """执行单个工具调用

    Args:
        state: 当前 Agent 状态（读取 state["action"]）
        registry: 能力注册中心

    Returns:
        部分状态更新: {"observation": {...}}
    """
    action = state.get("action", {})
    tool_name = action.get("tool", "")
    args = action.get("args", {})

    if not tool_name:
        return {"observation": {"status": "skipped", "result": "无工具调用"}}

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(registry.execute_tool, tool_name, args),
            timeout=TOOL_TIMEOUT,
        )
        observation = {
            "tool": tool_name,
            "args": args,
            "result": result,
            "status": "success",
        }
    except asyncio.TimeoutError:
        logger.warning("execute_action: 工具 %s 执行超时（%d秒）", tool_name, TOOL_TIMEOUT)
        observation = {
            "tool": tool_name,
            "args": args,
            "result": f"工具执行超时（超过 {TOOL_TIMEOUT} 秒），请缩小扫描范围或检查路径是否正确",
            "status": "timeout",
        }
    except ToolError as e:
        logger.warning("execute_action: 工具 %s 执行失败: %s", e.tool_name, e.detail)
        observation = {
            "tool": tool_name,
            "args": args,
            "result": f"执行失败: {e.detail}",
            "status": "error",
        }
    except KeyError as e:
        logger.warning("execute_action: 工具 %s 参数缺失: %s", tool_name, e)
        observation = {
            "tool": tool_name,
            "args": args,
            "result": f"参数缺失: {e}",
            "status": "error",
        }
    except Exception as e:
        logger.error("execute_action: 工具 %s 未知异常: %s", tool_name, e, exc_info=True)
        observation = {
            "tool": tool_name,
            "args": args,
            "result": f"执行失败: {str(e)}",
            "status": "error",
        }

    logger.info("execute_action: %s(%s) → %s", tool_name,
                json.dumps(args, ensure_ascii=False)[:80], observation["status"])

    return {"observation": observation}
