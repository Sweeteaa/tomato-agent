from pathlib import Path
from app.config import WORKSPACE

tools = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出指定目录的内容，返回真实的文件系统结构。当用户要求扫描项目、查看目录结构时，必须使用此工具获取真实结果，禁止猜测或推断目录结构",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "目录的绝对路径，如 'D:/projects/xxx'。必须是真实存在的目录路径"
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "是否递归列出子目录内容，默认 false",
                        "default": False
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "递归的最大深度，默认 5，建议设置为 5-10 以确保扫描到深层目录结构",
                        "default": 5
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取指定文件的内容，返回真实的文件内容。当用户要求查看文件内容、分析代码时，必须使用此工具获取真实内容，禁止猜测文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件的绝对路径，如 'D:/projects/xxx/src/App.vue'"
                    },
                    "max_size": {
                        "type": "integer",
                        "description": "最大读取字节数，默认 1MB",
                        "default": 1048576
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_file",
            "description": "在指定目录下搜索包含关键字的文件，返回匹配的文件列表。用于在项目中查找包含特定内容的文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键字，如 'dashboard' 或 'followup_status'"
                    },
                    "root_path": {
                        "type": "string",
                        "description": "搜索的根目录绝对路径"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回结果数，默认 20",
                        "default": 20
                    }
                },
                "required": ["keyword", "root_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scan_menu_structure",
            "description": "扫描项目中的菜单组件和路由配置文件，提取其中定义的页面路径。当用户要求分析项目结构、查找业务页面时，必须先调用此工具获取菜单和路由信息，这是定位真实页面路径的最准确方法",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "项目的绝对路径，如 'D:/projects/xxx'"
                    }
                },
                "required": ["project_path"]
            }
        }
    },
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
        if name == "list_dir":
            from app.services.filesystem_tool import list_dir
            result = list_dir(
                path=arguments["path"],
                recursive=arguments.get("recursive", False),
                max_depth=arguments.get("max_depth", 5)
            )
            import json
            return json.dumps(result, ensure_ascii=False, indent=2)
        
        elif name == "read_file":
            from app.services.filesystem_tool import read_file
            content = read_file(
                file_path=arguments["path"],
                max_size=arguments.get("max_size", 1048576)
            )
            return content
        
        elif name == "search_file":
            from app.services.filesystem_tool import search_file
            results = search_file(
                keyword=arguments["keyword"],
                root_path=arguments["root_path"],
                max_results=arguments.get("max_results", 20)
            )
            import json
            return json.dumps(results, ensure_ascii=False, indent=2)
        
        elif name == "scan_menu_structure":
            from app.services.filesystem_tool import scan_menu_structure
            results = scan_menu_structure(
                project_path=arguments["project_path"]
            )
            import json
            return json.dumps(results, ensure_ascii=False, indent=2)
        
        elif name == "save_skill":
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