"""Agent 异常定义 — 工具执行错误的统一异常体系"""


class ToolError(Exception):
    """工具执行错误基类

    用于替代"返回 ❌ 错误字符串"的反模式。
    工具函数遇到错误时应抛出此异常（或其子类），
    executor_node 在 except 分支捕获并统一设置 status: "error"。

    Attributes:
        tool_name: 出错的工具名称
        detail: 人类可读的错误描述
    """

    def __init__(self, detail: str, tool_name: str = ""):
        self.tool_name = tool_name
        self.detail = detail
        super().__init__(f"[{tool_name}] {detail}" if tool_name else detail)


class FileNotFoundError(ToolError):
    """文件/目录不存在"""

    def __init__(self, path: str, tool_name: str = "filesystem"):
        super().__init__(f"文件不存在: {path}", tool_name)


class PathSecurityError(ToolError):
    """路径安全限制（遍历攻击或权限不足）"""

    def __init__(self, detail: str, tool_name: str = "filesystem"):
        super().__init__(detail, tool_name)


class ResourceNotFoundError(ToolError):
    """通用资源不存在（记忆、技能、任务、项目等）"""

    def __init__(self, resource_type: str, name: str, tool_name: str = ""):
        super().__init__(f"{resource_type}不存在: {name}", tool_name)
