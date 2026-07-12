"""文档管理能力 — 技能文档和任务清单"""

from agent.tools.document import tool_definitions, tool_handlers


class DocumentCapability:
    name = "document"
    description = """
    文档管理能力:
    - 保存/读取技能文档
    - 列出所有技能
    - 保存/读取任务清单
    - 列出所有任务
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
