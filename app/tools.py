from pathlib import Path
from app.config import WORKSPACE

tools = [
    {
        "type": "function",
        "function": {
            "name": "save_skill",
            "description": "保存或更新一条技能文档到 skill 目录，自动生成 .md 文件。当用户要求生成技能、规范、指南等文档时，必须使用此工具创建包含实际内容的 .md 文件，禁止只创建空文件夹",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "技能名称，不含扩展名，如 'frontend-style-guide' 或 'api-design'"
                    },
                    "content": {
                        "type": "string",
                        "description": "技能内容，必须包含实际内容，支持 Markdown 格式"
                    }
                },
                "required": ["name", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_folder",
            "description": "创建一个新文件夹，仅用于创建纯文件夹。如果用户需要生成技能文档或知识，请使用 save_skill、save_memory 等专用工具",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件夹路径，相对于 workspace 目录，如 'skill' 或 'projects/new-project'"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "创建或覆盖一个文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径，相对于 workspace 目录，如 'skill/hello.py' 或 'memory/note.md'"
                    },
                    "content": {
                        "type": "string",
                        "description": "文件内容"
                    }
                },
                "required": ["path", "content"]
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
                    "path": {
                        "type": "string",
                        "description": "文件路径，相对于 workspace 目录"
                    },
                    "content": {
                        "type": "string",
                        "description": "要追加的内容"
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "保存或更新一条长期记忆到 memory 目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "记忆名称，不含扩展名，如 'frontend' 或 'bugs'"
                    },
                    "content": {
                        "type": "string",
                        "description": "记忆内容，支持 Markdown 格式"
                    }
                },
                "required": ["name", "content"]
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
                    "name": {
                        "type": "string",
                        "description": "任务名称，不含扩展名，如 'todo' 或 'completed'"
                    },
                    "content": {
                        "type": "string",
                        "description": "任务内容，支持 Markdown 格式"
                    }
                },
                "required": ["name", "content"]
            }
        }
    }
]


def execute_tool(name: str, arguments: dict) -> str:
    try:
        if name == "save_skill":
            file_path = WORKSPACE / "skill" / f"{arguments['name']}.md"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(arguments["content"], encoding="utf-8")
            return f"✅ 技能保存成功: skill/{arguments['name']}.md"
        
        elif name == "create_folder":
            folder_path = WORKSPACE / arguments["path"]
            folder_path.mkdir(parents=True, exist_ok=True)
            return f"✅ 文件夹创建成功: {arguments['path']}"
        
        elif name == "create_file":
            file_path = WORKSPACE / arguments["path"]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(arguments["content"], encoding="utf-8")
            return f"✅ 文件创建成功: {arguments['path']}"
        
        elif name == "append_file":
            file_path = WORKSPACE / arguments["path"]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "a", encoding="utf-8") as f:
                f.write("\n" + arguments["content"])
            return f"✅ 文件追加成功: {arguments['path']}"
        
        elif name == "save_memory":
            file_path = WORKSPACE / "memory" / f"{arguments['name']}.md"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(arguments["content"], encoding="utf-8")
            return f"✅ 记忆保存成功: memory/{arguments['name']}.md"
        
        elif name == "save_task":
            file_path = WORKSPACE / "tasks" / f"{arguments['name']}.md"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(arguments["content"], encoding="utf-8")
            return f"✅ 任务保存成功: tasks/{arguments['name']}.md"
        
        else:
            return f"❌ 未知工具: {name}"
    except Exception as e:
        return f"❌ 执行失败: {str(e)}"