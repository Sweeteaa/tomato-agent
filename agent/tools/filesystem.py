"""文件系统工具层 — 只负责文件操作，不包含业务逻辑"""

import os
from pathlib import Path
from app.config import WORKSPACE


def read_file(path: str) -> str:
    """读取文件内容"""
    file_path = WORKSPACE / path
    if not file_path.exists():
        return f"❌ 文件不存在: {path}"
    return file_path.read_text(encoding="utf-8")


def write_file(path: str, content: str) -> str:
    """创建或覆盖文件"""
    file_path = WORKSPACE / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return f"✅ 文件创建成功: {path}"


def delete_file(path: str) -> str:
    """删除文件"""
    file_path = WORKSPACE / path
    if not file_path.exists():
        return f"❌ 文件不存在: {path}"
    file_path.unlink()
    return f"✅ 文件删除成功: {path}"


def append_file(path: str, content: str) -> str:
    """向文件末尾追加内容"""
    file_path = WORKSPACE / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "a", encoding="utf-8") as f:
        f.write("\n" + content)
    return f"✅ 文件追加成功: {path}"


def search_file(query: str) -> str:
    """在 workspace 中搜索文件内容"""
    results = []
    for root, dirs, files in os.walk(WORKSPACE):
        for name in files:
            file_path = Path(root) / name
            if file_path.suffix in (".md", ".json", ".txt", ".py"):
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                if query.lower() in content.lower():
                    rel_path = file_path.relative_to(WORKSPACE)
                    results.append(str(rel_path))
    if not results:
        return f"未找到包含 '{query}' 的文件"
    return f"找到 {len(results)} 个匹配文件:\n" + "\n".join(results)


def list_dir(path: str = "") -> str:
    """列出目录内容"""
    dir_path = WORKSPACE / path if path else WORKSPACE
    if not dir_path.exists():
        return f"❌ 目录不存在: {path}"
    items = []
    for child in sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
        prefix = "📁 " if child.is_dir() else "📄 "
        items.append(f"{prefix}{child.name}")
    return "\n".join(items) if items else "目录为空"


def create_folder(path: str) -> str:
    """创建文件夹"""
    folder_path = WORKSPACE / path
    folder_path.mkdir(parents=True, exist_ok=True)
    return f"✅ 文件夹创建成功: {path}"


# 工具定义（OpenAI function calling 格式）
tool_definitions = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径，相对于 workspace 目录"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "创建或覆盖一个文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径，相对于 workspace 目录"},
                    "content": {"type": "string", "description": "文件内容"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "删除文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径，相对于 workspace 目录"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "append_file",
            "description": "向文件末尾追加内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径，相对于 workspace 目录"},
                    "content": {"type": "string", "description": "要追加的内容"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_file",
            "description": "在 workspace 中搜索文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出目录内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径，相对于 workspace 目录，默认为根目录"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_folder",
            "description": "创建文件夹",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件夹路径，相对于 workspace 目录"}
                },
                "required": ["path"]
            }
        }
    },
]

# 工具执行映射
tool_handlers = {
    "read_file": lambda args: read_file(args["path"]),
    "write_file": lambda args: write_file(args["path"], args["content"]),
    "delete_file": lambda args: delete_file(args["path"]),
    "append_file": lambda args: append_file(args["path"], args["content"]),
    "search_file": lambda args: search_file(args["query"]),
    "list_dir": lambda args: list_dir(args.get("path", "")),
    "create_folder": lambda args: create_folder(args["path"]),
}
