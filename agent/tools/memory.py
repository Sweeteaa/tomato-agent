"""记忆工具层 — 负责长期记忆的读写操作

错误处理: 抛出 ResourceNotFoundError 异常而非返回 ❌ 字符串
"""

from pathlib import Path
from app.config import WORKSPACE
from agent.exceptions import ResourceNotFoundError


def save_memory(name: str, content: str) -> str:
    """保存或更新一条长期记忆"""
    file_path = WORKSPACE / "memory" / f"{name}.md"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return f"✅ 记忆保存成功: memory/{name}.md"


def read_memory(name: str) -> str:
    """读取一条长期记忆

    Raises:
        ResourceNotFoundError: 记忆不存在
    """
    file_path = WORKSPACE / "memory" / f"{name}.md"
    if not file_path.exists():
        raise ResourceNotFoundError("记忆", name, "memory")
    return file_path.read_text(encoding="utf-8")


def list_memory() -> str:
    """列出所有记忆"""
    mem_dir = WORKSPACE / "memory"
    if not mem_dir.exists():
        return "暂无记忆"
    files = sorted(mem_dir.glob("*.md"))
    if not files:
        return "暂无记忆"
    return "\n".join(f"📄 {f.stem}" for f in files)


def delete_memory(name: str) -> str:
    """删除一条记忆

    Raises:
        ResourceNotFoundError: 记忆不存在
    """
    file_path = WORKSPACE / "memory" / f"{name}.md"
    if not file_path.exists():
        raise ResourceNotFoundError("记忆", name, "memory")
    file_path.unlink()
    return f"✅ 记忆删除成功: {name}"


# 工具定义
tool_definitions = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "保存或更新一条长期记忆到 memory 目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "记忆名称，不含扩展名"},
                    "content": {"type": "string", "description": "记忆内容，支持 Markdown 格式"}
                },
                "required": ["name", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_memory",
            "description": "读取一条长期记忆",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "记忆名称"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_memory",
            "description": "列出所有记忆",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_memory",
            "description": "删除一条记忆",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "记忆名称"}
                },
                "required": ["name"]
            }
        }
    },
]

# 工具执行映射
tool_handlers = {
    "save_memory": lambda args: save_memory(args["name"], args["content"]),
    "read_memory": lambda args: read_memory(args["name"]),
    "list_memory": lambda args: list_memory(),
    "delete_memory": lambda args: delete_memory(args["name"]),
}
