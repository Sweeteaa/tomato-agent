"""能力注册中心 — 统一管理所有能力，为 Agent 提供工具列表和执行入口"""


class CapabilityRegistry:
    def __init__(self):
        self.capabilities = {}

    def register(self, capability):
        """注册一个能力"""
        self.capabilities[capability.name] = capability

    def get_capability(self, name: str):
        """获取指定能力"""
        return self.capabilities.get(name)

    def get_all_tools(self) -> list:
        """获取所有能力提供的工具定义（OpenAI function calling 格式）"""
        tools = []
        for capability in self.capabilities.values():
            tools.extend(capability.get_tools())
        return tools

    def get_all_handlers(self) -> dict:
        """获取所有工具名 → 处理函数的映射"""
        handlers = {}
        for capability in self.capabilities.values():
            handlers.update(capability.get_handlers())
        return handlers

    def execute_tool(self, tool_name: str, arguments: dict) -> str:
        """通过工具名查找所属能力并执行"""
        for capability in self.capabilities.values():
            handlers = capability.get_handlers()
            if tool_name in handlers:
                return capability.execute(tool_name, arguments)
        return f"❌ 未知工具: {tool_name}"

    def list_capabilities(self) -> list:
        """列出所有已注册能力"""
        return [
            {"name": c.name, "description": c.description.strip()}
            for c in self.capabilities.values()
        ]


def create_default_registry() -> CapabilityRegistry:
    """创建默认注册中心，注册所有内置能力"""
    from agent.capabilities.filesystem.capability import FileSystemCapability
    from agent.capabilities.memory.capability import MemoryCapability
    from agent.capabilities.document.capability import DocumentCapability

    registry = CapabilityRegistry()
    registry.register(FileSystemCapability())
    registry.register(MemoryCapability())
    registry.register(DocumentCapability())
    return registry
