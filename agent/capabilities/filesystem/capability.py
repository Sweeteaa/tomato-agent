"""文件管理能力 — 统一的项目扫描和 workspace 文件操作"""

from agent.capabilities.base import BaseCapability


class FileSystemCapability(BaseCapability):
    name = "filesystem"
    description = """
    文件管理能力:
    - 读取文件（支持绝对路径和 workspace 相对路径）
    - 列出目录（支持递归扫描、绝对路径）
    - 搜索文件内容（workspace 内搜索 / 项目目录内搜索）
    - 扫描项目菜单和路由结构（scan_menu_structure）
    - 创建/覆盖/删除/追加文件（仅限 workspace 内）
    - 创建文件夹（仅限 workspace 内）

    路径规则:
    - 扫描用户项目时使用绝对路径，如 'D:/projects/xxx'
    - workspace 内操作使用相对路径，如 'skill/hello.md'
    """
    _tool_module = "agent.tools.filesystem"
