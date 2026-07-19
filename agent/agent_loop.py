"""AgentLoop — Agent 编排层

参考 nanobot loop.py 设计，负责编排：
  - 会话管理（加载历史、保存 turn）
  - 上下文构建（system prompt + history + user message）
  - 并发控制（同会话串行）
  - SSE 事件流生成

核心改进（相比旧 graph_service.py）：
  - 无全局可变状态，所有状态在方法参数中传递
  - 每个 conv_id 一个 asyncio.Lock，保证同会话串行
  - SSE 回调通过 spec 注入 runner
"""

import asyncio
import logging
from pathlib import Path
from typing import AsyncGenerator, Optional

from openai import AsyncOpenAI

from agent.runner import AgentRunner
from agent.run_spec import AgentRunSpec, AgentRunResult
from agent.context_builder import ContextBuilder, BuildContext
from agent.session import SessionManager
from agent.checkpoint import CheckpointManager
from agent.registry.capability_registry import CapabilityRegistry
from agent.memory.extractor import extract_and_save_async
from agent.planner import Planner
from app.config import USE_REASONING_MODEL, REASONING_MODEL_NAME

logger = logging.getLogger("gt_agent.loop")


class AgentLoop:
    """Agent 编排层 — 管理会话、并发、上下文"""
    
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        workspace: Path,
        registry: CapabilityRegistry,
        temperature: float = 0.7,
        max_iterations: int = 10,
    ):
        self.client = client
        self.model = model
        self.workspace = workspace
        self.registry = registry
        self.temperature = temperature
        self.max_iterations = max_iterations
        
        # 子组件
        self.runner = AgentRunner(client, model, temperature)
        self.context_builder = ContextBuilder(workspace)
        self.session_mgr = SessionManager(workspace)
        self.checkpoint_mgr = CheckpointManager(workspace)
        self.planner = Planner(client, model, temperature)
        
        # 并发控制：每个 conv_id 一个锁
        self._session_locks: dict[str, asyncio.Lock] = {}
    
    async def process_message(
        self,
        query: str,
        conv_id: str,
        images: list[dict] | None = None,
        files: list[dict] | None = None,
        user_profile: str = "",
        memory_context: str = "",
        skill_context: str = "",
        project_context: str = "",
        pending_info: str = "",
    ) -> AsyncGenerator[dict, None]:
        """处理一条用户消息，yield SSE 事件
        
        流程：
          1. 获取会话锁
          2. 恢复 checkpoint（如果有）
          3. 加载历史
          4. 构建 messages
          5. 调用 runner
          6. 保存 turn
          7. 提取记忆
        """
        # 获取会话锁
        lock = self._get_lock(conv_id)
        
        async with lock:
            try:
                # 恢复 checkpoint（如果有）
                checkpoint_messages = await self.checkpoint_mgr.restore(conv_id)
                
                # 加载历史
                if checkpoint_messages:
                    history = checkpoint_messages
                    logger.info("loop: 从 checkpoint 恢复 %s, messages=%d", conv_id, len(history))
                else:
                    history = await self.session_mgr.load_history(conv_id)
                
                # 构建 system prompt
                build_ctx = BuildContext(
                    user_profile=user_profile,
                    memory_context=memory_context,
                    skill_context=skill_context,
                    project_context=project_context,
                    pending_info=pending_info,
                )
                system_prompt = self.context_builder.build_system_prompt(build_ctx)
                
                # 构建用户消息（处理图片）
                user_content = self._build_user_content(query, images, files)
                
                # 构建完整 messages
                messages = self.context_builder.build_messages(
                    system_prompt, history, user_content
                )
                
                # 准备工具
                tools = self.registry.get_all_tools()
                handlers = self.registry.get_all_handlers()
                
                # 生成执行计划
                plan = await self.planner.plan(
                    query=query,
                    tools=tools,
                    project_context=project_context,
                    memory_context=memory_context,
                )
                
                # 发送计划事件
                if plan.get("requires_planning"):
                    yield {"type": "plan", "plan": plan}

                # 判断是否启用推理模型展示思考链
                enable_thinking = (
                    USE_REASONING_MODEL
                    and bool(REASONING_MODEL_NAME)
                    and bool(plan.get("use_reasoning"))
                )
                if enable_thinking:
                    yield {"type": "status", "message": "已启用深度思考模式..."}

                # 创建 SSE 回调
                events_queue: asyncio.Queue[dict] = asyncio.Queue()

                async def on_tool_start(tool_name: str, tool_args: dict, purpose: str = ""):
                    await events_queue.put({
                        "type": "tool_start",
                        "tool": tool_name,
                        "args": tool_args,
                        "purpose": purpose,
                    })
                    await events_queue.put({
                        "type": "status",
                        "message": f"执行工具 {tool_name}" + (f"（{purpose}）" if purpose else ""),
                    })

                async def on_tool_end(tool_name: str, status: str, result_preview: str):
                    await events_queue.put({
                        "type": "tool_end",
                        "tool": tool_name,
                        "status": status,
                        "args": {},
                        "result": result_preview,
                    })

                async def on_plan_progress(step: int, total: int):
                    await events_queue.put({
                        "type": "plan_progress",
                        "step": step,
                        "total": total,
                        "message": f"计划执行中（已完成 {step} 个工具调用，计划共 {total} 步）",
                    })

                async def on_thought(reasoning: str):
                    await events_queue.put({
                        "type": "thought",
                        "content": reasoning,
                    })

                # 构建运行配置
                spec = AgentRunSpec(
                    initial_messages=messages,
                    tools=tools,
                    tool_handlers=handlers,
                    max_iterations=self.max_iterations,
                    on_tool_start=on_tool_start,
                    on_tool_end=on_tool_end,
                    on_thought=on_thought,
                    plan=plan,
                    on_plan_progress=on_plan_progress,
                    enable_thinking=enable_thinking,
                    reasoning_model=REASONING_MODEL_NAME if enable_thinking else None,
                )
                
                # 先 yield 状态事件
                yield {"type": "status", "message": "正在推理..."}
                
                # 启动 runner 任务
                runner_task = asyncio.create_task(self.runner.run(spec))
                
                # 同时消费事件队列
                while not runner_task.done():
                    try:
                        event = await asyncio.wait_for(events_queue.get(), timeout=0.1)
                        yield event
                    except asyncio.TimeoutError:
                        continue
                
                # 消费剩余事件
                while not events_queue.empty():
                    event = events_queue.get_nowait()
                    yield event
                
                # 获取结果
                result = runner_task.result()
                
                if result.error:
                    logger.error("loop: runner 错误: %s", result.error)
                    yield {"type": "status", "message": f"执行出错: {result.error}"}
                
                # 保存 turn（只保存新增的 messages）
                new_messages = result.messages[len(messages):]
                if new_messages:
                    await self.session_mgr.save_turn(conv_id, new_messages)
                
                # 清除 checkpoint
                await self.checkpoint_mgr.clear(conv_id)
                
                # 提取记忆（后台任务）
                asyncio.create_task(
                    self._extract_memory(conv_id, query, result)
                )
                
                # 输出最终回答
                if result.final_content:
                    yield {"type": "token", "content": result.final_content}
                
                # 完成事件
                yield {
                    "type": "done",
                    "response": result.final_content or "",
                    "context_used": len(history) > 0,
                    "tool_executions": self._build_tool_executions(result),
                    "plan": result.plan,
                    "plan_steps_completed": result.plan_steps_completed,
                    "plan_total_steps": len(result.plan.get("steps", [])) if result.plan else 0,
                    "plan_steps": len(result.tools_used),
                    "execution_trace": self._build_tool_executions(result),
                    "reasoning": result.reasoning,
                    "is_complete": result.stop_reason == "completed",
                    "conversation_id": conv_id,
                }
                
            except asyncio.CancelledError:
                logger.info("loop: 任务被取消 %s", conv_id)
                raise
            except Exception as e:
                logger.error("loop: 处理消息失败: %s", e, exc_info=True)
                yield {"type": "status", "message": f"处理失败: {str(e)}"}
                yield {
                    "type": "done",
                    "response": f"处理失败: {str(e)}",
                    "context_used": False,
                    "tool_executions": [],
                    "plan": [],
                    "plan_steps": 0,
                    "execution_trace": [],
                    "is_complete": False,
                    "conversation_id": conv_id,
                }
    
    def _get_lock(self, conv_id: str) -> asyncio.Lock:
        """获取会话锁"""
        if conv_id not in self._session_locks:
            self._session_locks[conv_id] = asyncio.Lock()
        return self._session_locks[conv_id]
    
    def _build_user_content(
        self, 
        query: str, 
        images: list[dict] | None, 
        files: list[dict] | None
    ) -> str | list[dict]:
        """构建用户消息内容（处理图片）"""
        parts = []
        
        # 处理文件内容
        if files:
            for f in files:
                if isinstance(f, dict) and "content" in f:
                    parts.append(f"【文件: {f.get('filename', 'unknown')}】\n{f['content']}\n")
        
        # 处理图片
        if images:
            content_blocks = []
            for img in images:
                content_blocks.append({
                    "type": "image_url",
                    "image_url": {"url": img.get("url", img.get("base64", ""))},
                })
            content_blocks.append({"type": "text", "text": query})
            
            if parts:
                # 有文件内容，合并文本
                text_parts = "\n\n".join(parts) + "\n\n" + query
                content_blocks[-1]["text"] = text_parts
            
            return content_blocks
        
        # 纯文本
        if parts:
            return "\n\n".join(parts) + "\n\n" + query
        return query
    
    async def _extract_memory(
        self, 
        conv_id: str, 
        query: str, 
        result: AgentRunResult
    ) -> None:
        """后台提取记忆"""
        try:
            trajectory = self._build_tool_executions(result)
            await asyncio.to_thread(
                extract_and_save_async,
                query,
                trajectory,
            )
        except Exception as e:
            logger.warning("loop: 记忆提取失败: %s", e)
    
    def _build_tool_executions(self, result: AgentRunResult) -> list[dict]:
        """从 result 构建工具执行轨迹"""
        trace = []
        for msg in result.messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    trace.append({
                        "thought": "",
                        "action": {
                            "tool": tc["function"]["name"],
                            "args": tc["function"]["arguments"],
                        },
                        "observation": {},
                    })
            elif msg.get("role") == "tool":
                # 找到对应的 trace 条目
                for t in reversed(trace):
                    if not t.get("observation"):
                        t["observation"] = {
                            "status": "success" if "Error" not in msg.get("content", "") else "error",
                            "result": msg.get("content", "")[:500],
                        }
                        break
        return trace
