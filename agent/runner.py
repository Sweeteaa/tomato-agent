"""AgentRunner — Agent 执行引擎

参考 nanobot runner.py 设计，用纯 asyncio 实现单循环：
  调 LLM → 执行工具 → 调 LLM → ... → 最终回答

核心改进（相比旧 LangGraph 4 节点）：
  - 每步只调 1 次 LLM（而非 3-4 次）
  - 使用原生 function calling（而非手动 JSON 解析）
  - 工具结果直传 LLM（而非经 observation 有损压缩）
  - LLM 自主决定停止（而非 critic 硬编码 heuristic）
"""

import asyncio
import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from agent.run_spec import AgentRunSpec, AgentRunResult
from agent.exceptions import ToolError

logger = logging.getLogger("gt_agent.runner")

# 常量
_MAX_EMPTY_RETRIES = 2  # 空响应最大重试次数
_MAX_LENGTH_RECOVERIES = 3  # length 截断最大恢复次数


class AgentRunner:
    """Agent 执行引擎 — 纯 asyncio 单循环"""
    
    def __init__(self, client: AsyncOpenAI, model: str, temperature: float = 0.7):
        self.client = client
        self.model = model
        self.temperature = temperature
    
    def _select_model(self, spec: AgentRunSpec) -> str:
        """根据配置选择当前使用的模型。"""
        if spec.enable_thinking and spec.reasoning_model:
            return spec.reasoning_model
        return self.model

    async def run(self, spec: AgentRunSpec) -> AgentRunResult:
        """执行 Agent 循环
        
        流程：
          1. 调 LLM（带 tools 定义）
          2. 如果有 tool_calls → 执行工具 → 追加 results → 回到 1
          3. 如果无 tool_calls → 返回最终回答
          4. 达到 max_iterations → 做最终化请求
        """
        messages = list(spec.initial_messages)
        messages = self._inject_plan_if_needed(messages, spec.plan)
        
        tools_used = []
        plan_steps_completed = 0
        empty_retries = 0
        length_recoveries = 0
        all_reasoning = []  # 收集本轮所有思考链片段
        
        for iteration in range(spec.max_iterations):
            logger.debug("runner: iteration=%d, messages=%d", iteration, len(messages))
            
            # 调 LLM
            try:
                response = await self._call_llm(messages, spec.tools, spec)
            except Exception as e:
                logger.error("runner: LLM 调用失败: %s", e)
                return AgentRunResult(
                    final_content=None,
                    messages=messages,
                    tools_used=tools_used,
                    stop_reason="error",
                    error=str(e),
                    plan=spec.plan,
                    plan_steps_completed=plan_steps_completed,
                    reasoning="\n".join(all_reasoning) if all_reasoning else None,
                )
            
            # 提取 assistant message
            choice = response.choices[0]
            assistant_msg = choice.message
            finish_reason = choice.finish_reason

            # 提取并展示推理模型思考链
            content = assistant_msg.content or ""
            reasoning_content = ""
            if spec.enable_thinking:
                reasoning_content = getattr(assistant_msg, "reasoning_content", "") or ""
                if not reasoning_content:
                    think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
                    if think_match:
                        reasoning_content = think_match.group(1).strip()
                        content = content[:think_match.start()] + content[think_match.end():]
                        content = content.strip()
                if reasoning_content:
                    all_reasoning.append(reasoning_content)
                    if spec.on_thought:
                        try:
                            await spec.on_thought(reasoning_content)
                        except Exception as e:
                            logger.warning("runner: on_thought 回调失败: %s", e)

            # 空响应处理（无内容且无工具调用）
            if not content and not assistant_msg.tool_calls:
                empty_retries += 1
                if empty_retries <= _MAX_EMPTY_RETRIES:
                    logger.warning("runner: 空响应，重试 %d/%d", empty_retries, _MAX_EMPTY_RETRIES)
                    messages.append({"role": "assistant", "content": ""})
                    continue
                else:
                    logger.warning("runner: 空响应超过重试上限")
                    break
            
            empty_retries = 0  # 重置空响应计数
            
            # 追加 assistant message 到历史
            assistant_dict = self._message_to_dict(assistant_msg)
            if content != (assistant_msg.content or "") and content:
                assistant_dict["content"] = content
            elif not content:
                assistant_dict.pop("content", None)
            messages.append(assistant_dict)
            
            # 判断是否有 tool_calls
            if not assistant_msg.tool_calls:
                # LLM 给出最终回答，结束
                logger.info("runner: 完成 (iteration=%d, finish=%s)", iteration, finish_reason)
                return AgentRunResult(
                    final_content=content or "",
                    messages=messages,
                    tools_used=tools_used,
                    stop_reason="completed",
                    plan=spec.plan,
                    plan_steps_completed=plan_steps_completed,
                    reasoning="\n".join(all_reasoning) if all_reasoning else None,
                )
            
            # 执行工具
            for tool_call in assistant_msg.tool_calls:
                tool_name = tool_call.function.name
                tool_args = self._parse_args(tool_call.function.arguments)
                
                logger.info("runner: 调用工具 %s(%s)", tool_name, 
                           json.dumps(tool_args, ensure_ascii=False)[:80])

                # 从计划中提取当前步骤的 purpose（在计数增加前，索引从 0 开始）
                purpose = ""
                if spec.plan and spec.plan.get("steps"):
                    step_index = plan_steps_completed
                    if step_index < len(spec.plan["steps"]):
                        purpose = spec.plan["steps"][step_index].get("purpose", "")
                
                # 更新计划进度
                plan_steps_completed += 1
                if spec.on_plan_progress:
                    try:
                        await spec.on_plan_progress(plan_steps_completed, len(spec.plan.get("steps", [])))
                    except Exception as e:
                        logger.warning("runner: on_plan_progress 回调失败: %s", e)
                
                # 回调：工具开始
                if spec.on_tool_start:
                    try:
                        await spec.on_tool_start(tool_name, tool_args, purpose)
                    except TypeError:
                        # 兼容旧签名（只有两个参数）
                        try:
                            await spec.on_tool_start(tool_name, tool_args)
                        except Exception as e:
                            logger.warning("runner: on_tool_start 回调失败: %s", e)
                    except Exception as e:
                        logger.warning("runner: on_tool_start 回调失败: %s", e)
                
                # 执行工具
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(spec.tool_handlers[tool_name], tool_args),
                        timeout=spec.tool_timeout,
                    )
                    status = "success"
                except asyncio.TimeoutError:
                    result = f"工具执行超时（超过 {spec.tool_timeout} 秒）"
                    status = "timeout"
                    logger.warning("runner: 工具 %s 执行超时", tool_name)
                except ToolError as e:
                    result = f"执行失败: {e.detail}"
                    status = "error"
                    logger.warning("runner: 工具 %s 执行失败: %s", tool_name, e.detail)
                except KeyError:
                    result = f"未知工具: {tool_name}"
                    status = "error"
                    logger.warning("runner: 未知工具 %s", tool_name)
                except Exception as e:
                    result = f"执行失败: {str(e)}"
                    status = "error"
                    logger.error("runner: 工具 %s 未知异常: %s", tool_name, e, exc_info=True)
                
                # 截断超大结果
                result_str = str(result)
                if len(result_str) > 10000:
                    result_str = result_str[:10000] + "\n...[已截断]"
                
                # 追加 tool result 到历史
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,
                })
                
                tools_used.append(tool_name)
                
                # 回调：工具结束
                if spec.on_tool_end:
                    try:
                        await spec.on_tool_end(tool_name, status, result_str[:500])
                    except Exception as e:
                        logger.warning("runner: on_tool_end 回调失败: %s", e)
        
        # 达到 max_iterations，做最终化请求
        logger.warning("runner: 达到 max_iterations=%d，做最终化请求", spec.max_iterations)
        return await self._finalize(messages, spec, tools_used, plan_steps_completed, all_reasoning)
    
    async def _call_llm(self, messages: list[dict], tools: list[dict], spec: AgentRunSpec) -> Any:
        """调用 LLM"""
        kwargs = {
            "model": self._select_model(spec),
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools:
            kwargs["tools"] = tools
        
        response = await self.client.chat.completions.create(**kwargs)
        return response
    
    async def _finalize(
        self, 
        messages: list[dict], 
        spec: AgentRunSpec, 
        tools_used: list[str],
        plan_steps_completed: int = 0,
        all_reasoning: list[str] | None = None,
    ) -> AgentRunResult:
        """最终化请求 — 无工具调用，让 LLM 总结"""
        # 移除 tools 参数，提示 LLM 给出最终回答
        finalize_messages = messages + [
            {"role": "user", "content": "请根据已有信息，给出最终回答。"}
        ]
        
        try:
            response = await self.client.chat.completions.create(
                model=self._select_model(spec),
                messages=finalize_messages,
                temperature=self.temperature,
            )
            content = response.choices[0].message.content or ""
            return AgentRunResult(
                final_content=content,
                messages=messages,
                tools_used=tools_used,
                stop_reason="max_iterations",
                plan=spec.plan,
                plan_steps_completed=plan_steps_completed,
                reasoning="\n".join(all_reasoning) if all_reasoning else None,
            )
        except Exception as e:
            logger.error("runner: 最终化请求失败: %s", e)
            return AgentRunResult(
                final_content=None,
                messages=messages,
                tools_used=tools_used,
                stop_reason="error",
                error=str(e),
                plan=spec.plan,
                plan_steps_completed=plan_steps_completed,
                reasoning="\n".join(all_reasoning) if all_reasoning else None,
            )
    
    def _message_to_dict(self, msg) -> dict:
        """将 ChatCompletionMessage 转为 dict"""
        result = {"role": "assistant"}
        
        if msg.content:
            result["content"] = msg.content
        
        if msg.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                }
                for tc in msg.tool_calls
            ]
        
        return result
    
    def _parse_args(self, arguments: str) -> dict:
        """解析工具参数"""
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            logger.warning("runner: 工具参数解析失败: %s", arguments[:100])
            return {}
    
    def _inject_plan_if_needed(
        self,
        messages: list[dict],
        plan: dict | None,
    ) -> list[dict]:
        """如果存在计划，将计划提示注入 messages
        
        在最后一个 user 消息之前插入计划提醒，让 LLM 在执行时参照计划。
        """
        if not plan or not plan.get("requires_planning") or not plan.get("steps"):
            return messages
        
        steps_str = "\n".join(
            f"{s.get('step', i+1)}. [{s.get('action', '')}] {s.get('purpose', '')}"
            for i, s in enumerate(plan["steps"])
        )
        
        plan_instruction = f"""【执行计划】

目标: {plan.get('goal', '')}
预期产出: {plan.get('expected_output', '')}

步骤:
{steps_str}

请参照以上计划执行。如果某一步的结果表明需要调整计划，可以灵活变通，但尽量按顺序完成各步骤。每完成一步，可以简要说明进展。"""
        
        # 在最后一个 user 消息之前插入
        if messages and messages[-1].get("role") == "user":
            new_messages = messages[:-1]
            new_messages.append({"role": "user", "content": plan_instruction})
            new_messages.append(messages[-1])
            return new_messages
        
        # 如果没有 user 消息，追加到末尾
        return messages + [{"role": "user", "content": plan_instruction}]
