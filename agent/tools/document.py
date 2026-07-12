"""文档工具层 — 负责技能文档和任务的读写操作"""

from pathlib import Path
from app.config import WORKSPACE


def save_skill(name: str, content: str) -> str:
    """保存技能文档到 skill 目录"""
    file_path = WORKSPACE / "skill" / f"{name}.md"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return f"✅ 技能保存成功: skill/{name}.md"


def read_skill(name: str) -> str:
    """读取技能文档"""
    file_path = WORKSPACE / "skill" / f"{name}.md"
    if not file_path.exists():
        return f"❌ 技能不存在: {name}"
    return file_path.read_text(encoding="utf-8")


def list_skills() -> str:
    """列出所有技能"""
    skill_dir = WORKSPACE / "skill"
    if not skill_dir.exists():
        return "暂无技能"
    files = sorted(skill_dir.glob("*.md"))
    if not files:
        return "暂无技能"
    return "\n".join(f"📄 {f.stem}" for f in files)


def save_task(name: str, content: str) -> str:
    """保存任务清单到 tasks 目录"""
    file_path = WORKSPACE / "tasks" / f"{name}.md"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return f"✅ 任务保存成功: tasks/{name}.md"


def read_task(name: str) -> str:
    """读取任务清单"""
    file_path = WORKSPACE / "tasks" / f"{name}.md"
    if not file_path.exists():
        return f"❌ 任务不存在: {name}"
    return file_path.read_text(encoding="utf-8")


def list_tasks() -> str:
    """列出所有任务"""
    tasks_dir = WORKSPACE / "tasks"
    if not tasks_dir.exists():
        return "暂无任务"
    files = sorted(tasks_dir.glob("*.md"))
    if not files:
        return "暂无任务"
    return "\n".join(f"📄 {f.stem}" for f in files)


# 工具定义
tool_definitions = [
    {
        "type": "function",
        "function": {
            "name": "save_skill",
            "description": "保存或更新技能文档到 skill 目录，自动生成 .md 文件。当用户要求生成技能、规范、指南等文档时，必须使用此工具",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "技能名称，不含扩展名"},
                    "content": {"type": "string", "description": "技能内容，必须包含实际内容，支持 Markdown 格式"}
                },
                "required": ["name", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_skill",
            "description": "读取技能文档",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "技能名称"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "列出所有技能",
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
            "name": "save_task",
            "description": "保存或更新任务清单到 tasks 目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "任务名称，不含扩展名"},
                    "content": {"type": "string", "description": "任务内容，支持 Markdown 格式"}
                },
                "required": ["name", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_task",
            "description": "读取任务清单",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "任务名称"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "列出所有任务",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
]

# 工具执行映射
tool_handlers = {
    "save_skill": lambda args: save_skill(args["name"], args["content"]),
    "read_skill": lambda args: read_skill(args["name"]),
    "list_skills": lambda args: list_skills(),
    "save_task": lambda args: save_task(args["name"], args["content"]),
    "read_task": lambda args: read_task(args["name"]),
    "list_tasks": lambda args: list_tasks(),
}
