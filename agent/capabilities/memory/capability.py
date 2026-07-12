"""记忆管理能力"""

from agent.tools.memory import tool_definitions, tool_handlers


class MemoryCapability:
    name = "memory"
    description = """
    记忆管理能力:
    - 保存长期记忆
    - 读取记忆
    - 列出所有记忆
    - 删除记忆
    """

    def __init__(self):
        self.tools = tool_definitions
        self.handlers = tool_handlers

    def get_tools(self):
        return self.tools

    def get_handlers(self):
        return self.handlers

    def execute(self, tool_name: str, arguments: dict) -> str:
        handler = self.handlers.get(tool_name)
        if handler:
            return handler(arguments)
        return f"❌ 未知工具: {tool_name}"
