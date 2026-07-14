"""项目管理工具层 — 项目注册查询和深度结构扫描

合并了 app/services/project_scanner_service.py 和 project_registry_service.py 中
LLM 可调用的功能，使 Agent 能直接查询已注册项目和执行深度项目扫描。

错误处理: 抛出 ToolError/ResourceNotFoundError 异常而非返回 ❌ 字符串
"""

import json
from pathlib import Path

from app.config import WORKSPACE
from agent.exceptions import ToolError, ResourceNotFoundError


# ─── 项目注册查询 ───

def list_registered_projects() -> str:
    """列出所有已注册的项目，返回项目名称、路径、框架等信息"""
    from app.services.project_registry_service import list_registered_projects as _list

    projects = _list()
    if not projects:
        return "暂无已注册项目。可使用项目注册 API 添加项目。"

    lines = [f"已注册 {len(projects)} 个项目:"]
    for p in projects:
        lines.append(
            f"  - {p['name']} ({p.get('framework', 'unknown')}, "
            f"{p.get('build_tool', 'unknown')}) "
            f"路径: {p['root_path']} "
            f"扫描状态: {p.get('scan_status', 'pending')}"
        )
    return "\n".join(lines)


def get_project_info(name: str) -> str:
    """获取指定项目的详细元数据

    Raises:
        ResourceNotFoundError: 项目不存在
    """
    from app.services.project_registry_service import get_registered_project as _get

    project = _get(name)
    if not project:
        raise ResourceNotFoundError("项目", name, "project")

    return json.dumps(project, ensure_ascii=False, indent=2)


# ─── 深度项目扫描 ───

def scan_project(name: str, full_scan: bool = False) -> str:
    """深度扫描已注册项目的结构

    扫描内容包括:
    - 路由文件和路由条目 (path, name, component)
    - 页面文件列表 (.vue/.tsx/.jsx)
    - 公共组件文件列表
    - API 模块和导出方法
    - 状态管理文件
    - 配置文件 (vite/webpack 等)
    - package.json 依赖和脚本

    扫描结果会写入 workspace/projects/{name}/ 目录下的 structure.json 和 .md 文件。

    Raises:
        ToolError: 项目不存在 / 扫描失败
    """
    from app.services.project_scanner_service import scan_registered_project

    try:
        structure = scan_registered_project(name, full_scan=full_scan)
        summary = (
            f"项目 {structure['project']} 扫描完成:\n"
            f"  - 框架: {structure['framework']}\n"
            f"  - 构建工具: {structure['build_tool']}\n"
            f"  - 页面文件: {len(structure['pages'])} 个\n"
            f"  - 组件文件: {len(structure['components'])} 个\n"
            f"  - API 模块: {len(structure['api_modules'])} 个\n"
            f"  - 路由条目: {len(structure['router']['routes'])} 个\n"
            f"  - UI 组件库: {', '.join(structure['ui_libraries']) or '未识别'}\n"
            f"  - 状态管理: {structure['state']['type']}\n"
            f"  - 扫描时间: {structure['scanned_at']}\n"
            f"\n详细结构已写入 workspace/projects/{name}/ 目录"
        )
        return summary
    except ValueError as e:
        raise ToolError(str(e), "scan_project")
    except Exception as e:
        raise ToolError(f"扫描失败: {e}", "scan_project")


# ─── 项目文档查询 ───

def list_project_docs() -> str:
    """列出 workspace/projects/ 目录下所有项目的文档"""
    projects_dir = WORKSPACE / "projects"
    if not projects_dir.exists():
        return "暂无项目文档。请先注册并扫描项目。"

    projects = []
    for child in sorted(projects_dir.iterdir()):
        if child.is_dir():
            docs = [f.name for f in child.iterdir() if f.is_file()]
            projects.append(f"  📁 {child.name}: {', '.join(docs)}")

    if not projects:
        return "暂无项目文档。请先注册并扫描项目。"

    return f"找到 {len(projects)} 个项目的文档:\n" + "\n".join(projects)


def get_project_doc(project: str, doc: str) -> str:
    """读取项目文档内容

    Raises:
        ResourceNotFoundError: 文档不存在
    """
    file_path = WORKSPACE / "projects" / project / doc
    if not file_path.exists():
        raise ResourceNotFoundError("文档", f"{project}/{doc}", "project")
    return file_path.read_text(encoding="utf-8")


# ─── 工具定义（OpenAI function calling 格式）───

tool_definitions = [
    {
        "type": "function",
        "function": {
            "name": "list_registered_projects",
            "description": "列出所有已注册的项目，返回项目名称、路径、框架、构建工具等信息。当用户问'有哪些项目'或需要查看项目列表时使用",
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
            "name": "get_project_info",
            "description": "获取指定项目的详细元数据，包括框架、构建工具、包管理器、路由文件、组件目录、页面目录等",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "项目名称（注册时使用的名称）"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scan_project",
            "description": "深度扫描已注册项目的代码结构。扫描路由、页面、组件、API 模块、状态管理等，结果写入 workspace/projects/ 目录。当用户要求'分析项目结构'、'扫描项目'时使用此工具",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "已注册的项目名称"
                    },
                    "full_scan": {
                        "type": "boolean",
                        "description": "是否全量扫描（不限数量），默认 false",
                        "default": False
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_project_docs",
            "description": "列出 workspace 中已扫描项目生成的文档列表",
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
            "name": "get_project_doc",
            "description": "读取项目扫描后生成的文档内容（如 structure.json, overview.md, routes.md 等）",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "项目名称"
                    },
                    "doc": {
                        "type": "string",
                        "description": "文档文件名，如 'overview.md', 'routes.md', 'structure.json'"
                    }
                },
                "required": ["project", "doc"]
            }
        }
    },
]

# ─── 工具执行映射 ───

tool_handlers = {
    "list_registered_projects": lambda args: list_registered_projects(),
    "get_project_info": lambda args: get_project_info(args["name"]),
    "scan_project": lambda args: scan_project(args["name"], full_scan=args.get("full_scan", False)),
    "list_project_docs": lambda args: list_project_docs(),
    "get_project_doc": lambda args: get_project_doc(args["project"], args["doc"]),
}
