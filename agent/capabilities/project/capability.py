"""项目管理能力 — 项目注册查询和深度结构扫描"""

from agent.capabilities.base import BaseCapability


class ProjectCapability(BaseCapability):
    name = "project"
    description = """
    项目管理能力:
    - 查询已注册项目列表（list_registered_projects）
    - 获取项目详细元数据（get_project_info）
    - 深度扫描项目代码结构（scan_project）
    - 查看项目扫描文档（list_project_docs / get_project_doc）

    使用场景:
    - 用户问"有哪些项目" → list_registered_projects
    - 用户要求"分析项目结构" → scan_project
    - 用户要查看项目路由/组件/页面 → scan_project 后 get_project_doc
    """
    _tool_module = "agent.tools.project"
