"""Capability 基类 — 统一的工具注册和执行逻辑"""

from agent.exceptions import ToolError


class BaseCapability:
    """所有能力的基类，提供统一的工具注册和执行入口。

    子类只需定义：
    - name: 能力名称
    - description: 能力描述
    - _tool_module: 工具模块路径字符串（如 "agent.tools.filesystem"）
    """

    _tool_module: str = ""

    def __init__(self):
        # 延迟导入避免循环依赖
        import importlib
        module = importlib.import_module(self._tool_module)
        self.tools = module.tool_definitions
        self.handlers = module.tool_handlers

    def get_tools(self):
        return self.tools

    def get_handlers(self):
        return self.handlers

    def execute(self, tool_name: str, arguments: dict) -> str:
        handler = self.handlers.get(tool_name)
        if handler:
            return handler(arguments)
        raise ToolError(f"未知工具: {tool_name}", tool_name)
