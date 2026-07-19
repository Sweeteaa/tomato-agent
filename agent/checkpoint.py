"""CheckpointManager — 崩溃恢复

参考 nanobot checkpoint 设计，实现：
  - 每次 tool 执行后保存 checkpoint
  - 恢复上次中断的 messages
  - 未完成的 tool call 补一条 "Error: Task interrupted..."
"""

import asyncio
import json
import logging
from pathlib import Path

logger = logging.getLogger("gt_agent.checkpoint")


class CheckpointManager:
    """崩溃恢复管理器"""
    
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.checkpoints_dir = workspace / "checkpoints"
        self._lock = asyncio.Lock()
    
    async def save_checkpoint(
        self, 
        session_id: str, 
        messages: list[dict],
        phase: str = "tools_completed"
    ) -> None:
        """保存 checkpoint
        
        Args:
            session_id: 会话 ID
            messages: 当前 messages
            phase: 阶段标识 ("awaiting_tools" / "tools_completed")
        """
        async with self._lock:
            checkpoint_file = self._get_checkpoint_file(session_id)
            data = {
                "messages": messages,
                "phase": phase,
            }
            
            try:
                await asyncio.to_thread(self._write_json, checkpoint_file, data)
                logger.debug("checkpoint: 保存 %s, phase=%s, messages=%d", 
                           session_id, phase, len(messages))
            except Exception as e:
                logger.error("checkpoint: 保存失败: %s", e)
    
    async def restore(self, session_id: str) -> list[dict] | None:
        """恢复上次中断的 messages
        
        Args:
            session_id: 会话 ID
        
        Returns:
            恢复的 messages，或 None（无 checkpoint）
        """
        checkpoint_file = self._get_checkpoint_file(session_id)
        
        if not checkpoint_file.exists():
            return None
        
        try:
            data = await asyncio.to_thread(self._read_json, checkpoint_file)
            messages = data.get("messages", [])
            phase = data.get("phase", "")
            
            # 修复未完成的 tool calls
            messages = self._fix_interrupted(messages)
            
            logger.info("checkpoint: 恢复 %s, phase=%s, messages=%d", 
                       session_id, phase, len(messages))
            
            # 恢复后删除 checkpoint
            await asyncio.to_thread(checkpoint_file.unlink, True)
            
            return messages
            
        except Exception as e:
            logger.error("checkpoint: 恢复失败: %s", e)
            return None
    
    async def clear(self, session_id: str) -> None:
        """清除 checkpoint"""
        checkpoint_file = self._get_checkpoint_file(session_id)
        if checkpoint_file.exists():
            await asyncio.to_thread(checkpoint_file.unlink, True)
            logger.debug("checkpoint: 清除 %s", session_id)
    
    def _get_checkpoint_file(self, session_id: str) -> Path:
        """获取 checkpoint 文件路径"""
        safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_")
        return self.checkpoints_dir / f"{safe_id}.json"
    
    def _read_json(self, path: Path) -> dict:
        """同步读取 JSON"""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def _write_json(self, path: Path, data: dict) -> None:
        """同步写入 JSON"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    
    def _fix_interrupted(self, messages: list[dict]) -> list[dict]:
        """修复中断的 messages
        
        如果有 assistant tool_calls 但没有对应的 tool result，
        补一条 "Error: Task interrupted..."
        """
        if not messages:
            return messages
        
        last = messages[-1]
        
        # 如果最后是 assistant 且有 tool_calls
        if last.get("role") == "assistant" and last.get("tool_calls"):
            # 收集所有 tool_call_ids
            expected_ids = {tc.get("id") for tc in last["tool_calls"]}
            
            # 检查已有的 tool results
            received_ids = set()
            for msg in messages[:-1]:
                if msg.get("role") == "tool":
                    received_ids.add(msg.get("tool_call_id"))
            
            # 找出未完成的 tool_calls
            missing_ids = expected_ids - received_ids
            
            if missing_ids:
                logger.warning("checkpoint: 发现 %d 个未完成的 tool calls", len(missing_ids))
                # 为每个未完成的 tool_call 补一条错误消息
                for tc in last["tool_calls"]:
                    if tc.get("id") in missing_ids:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": "Error: Task interrupted (进程中断，工具执行未完成)",
                        })
        
        return messages
