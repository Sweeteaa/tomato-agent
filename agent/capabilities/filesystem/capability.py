"""文件管理能力"""

from agent.tools.filesystem import tool_definitions, tool_handlers


class FileSystemCapability:
    name = "filesystem"
    description = """
    文件管理能力:
    - 读取文件
    - 创建/覆盖文件
    - 删除文件
    - 追加文件内容
    - 搜索文件
    - 列出目录
    - 创建文件夹
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
