"""SessionManager — 会话持久化管理

参考 nanobot session 设计，实现：
  - 每个 session 一个 JSON 文件
  - 保存时清洗：跳过空 assistant、丢弃孤儿 tool result、截断超大内容
  - 加载时按 token 预算截断历史
  - 与现有 conversations/ 目录共存
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("gt_agent.session")

# 常量
_MAX_HISTORY_TOKENS = 16000  # 历史 token 预算（粗略估算），增大以保留更多上下文
_MAX_TOOL_RESULT_CHARS = 15000  # 工具结果最大字符数
_MAX_USER_MSG_CHARS = 8000  # 用户消息中文件内容保留上限
_TOKENS_PER_CHAR = 0.3  # 粗略 token 估算系数


class SessionManager:
    """会话持久化管理器"""
    
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.sessions_dir = workspace / "sessions"
        self._lock = asyncio.Lock()
    
    async def load_history(
        self, 
        session_id: str, 
        max_tokens: int = _MAX_HISTORY_TOKENS
    ) -> list[dict]:
        """加载会话历史
        
        Args:
            session_id: 会话 ID
            max_tokens: token 预算
        
        Returns:
            历史 messages 列表（标准 OpenAI 格式）
        """
        session_file = self._get_session_file(session_id)
        
        if not session_file.exists():
            logger.debug("session: 新会话 %s", session_id)
            return []
        
        try:
            data = await asyncio.to_thread(self._read_json, session_file)
            messages = data.get("messages", [])
            
            # 按 token 预算截断（从后往前保留）
            messages = self._truncate_by_tokens(messages, max_tokens)
            
            logger.debug("session: 加载历史 %s, messages=%d", session_id, len(messages))
            return messages
            
        except Exception as e:
            logger.error("session: 加载历史失败 %s: %s", session_id, e)
            return []
    
    async def save_turn(self, session_id: str, new_messages: list[dict]) -> None:
        """保存一轮对话的 messages
        
        Args:
            session_id: 会话 ID
            new_messages: 本轮新增的 messages
        """
        async with self._lock:
            session_file = self._get_session_file(session_id)
            
            # 加载现有消息
            existing = []
            if session_file.exists():
                try:
                    data = await asyncio.to_thread(self._read_json, session_file)
                    existing = data.get("messages", [])
                except Exception as e:
                    logger.warning("session: 读取现有消息失败: %s", e)
            
            # 清洗并追加新消息
            cleaned = self._clean_messages(new_messages)
            existing.extend(cleaned)
            
            # 保存
            data = {"messages": existing}
            await asyncio.to_thread(self._write_json, session_file, data)
            
            logger.debug("session: 保存 turn %s, new=%d, total=%d", 
                        session_id, len(cleaned), len(existing))
    
    async def create_session(self, conv_id: str) -> str:
        """创建新会话（如果不存在）
        
        Args:
            conv_id: 对话 ID
        
        Returns:
            session_id（与 conv_id 相同）
        """
        session_file = self._get_session_file(conv_id)
        
        if not session_file.exists():
            session_file.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._write_json, session_file, {"messages": []})
            logger.info("session: 创建新会话 %s", conv_id)
        
        return conv_id
    
    async def clear_session(self, session_id: str) -> None:
        """清空会话历史"""
        session_file = self._get_session_file(session_id)
        if session_file.exists():
            await asyncio.to_thread(self._write_json, session_file, {"messages": []})
            logger.info("session: 清空会话 %s", session_id)
    
    def _get_session_file(self, session_id: str) -> Path:
        """获取 session 文件路径"""
        # 清理 session_id 避免路径遍历
        safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_")
        return self.sessions_dir / f"{safe_id}.json"
    
    def _read_json(self, path: Path) -> dict:
        """同步读取 JSON"""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def _write_json(self, path: Path, data: dict) -> None:
        """同步写入 JSON"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _clean_messages(self, messages: list[dict]) -> list[dict]:
        """清洗 messages
        
        - 跳过空 assistant 消息
        - 截断超大 tool result
        - 丢弃孤儿 tool result
        """
        cleaned = []
        seen_tool_call_ids = set()
        
        # 第一遍：收集所有 tool_call_ids
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    seen_tool_call_ids.add(tc.get("id"))
        
        # 第二遍：清洗
        for msg in messages:
            role = msg.get("role")
            
            # 跳过空 assistant 消息
            if role == "assistant":
                content = msg.get("content")
                tool_calls = msg.get("tool_calls")
                if not content and not tool_calls:
                    continue
            
            # 丢弃孤儿 tool result
            if role == "tool":
                tool_call_id = msg.get("tool_call_id")
                if tool_call_id and tool_call_id not in seen_tool_call_ids:
                    logger.debug("session: 丢弃孤儿 tool result %s", tool_call_id)
                    continue
                
                # 截断超大 tool result
                content = msg.get("content", "")
                if len(content) > _MAX_TOOL_RESULT_CHARS:
                    msg = dict(msg)
                    msg["content"] = content[:_MAX_TOOL_RESULT_CHARS] + "\n...[已截断]"
            
            cleaned.append(msg)
        
        return cleaned
    
    def _truncate_by_tokens(self, messages: list[dict], max_tokens: int) -> list[dict]:
        """按 token 预算截断历史（从后往前保留）"""
        # 粗略估算 token 数
        def estimate_tokens(msgs: list[dict]) -> int:
            total_chars = sum(len(str(m.get("content", ""))) for m in msgs)
            return int(total_chars * _TOKENS_PER_CHAR)
        
        if estimate_tokens(messages) <= max_tokens:
            return messages
        
        # 从后往前保留
        result = []
        current_tokens = 0
        
        for msg in reversed(messages):
            msg_tokens = int(len(str(msg.get("content", ""))) * _TOKENS_PER_CHAR)
            if current_tokens + msg_tokens > max_tokens:
                break
            result.insert(0, msg)
            current_tokens += msg_tokens
        
        logger.debug("session: 截断历史 %d → %d messages", len(messages), len(result))
        return result
