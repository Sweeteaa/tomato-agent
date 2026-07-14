"""记忆管理能力"""

from agent.capabilities.base import BaseCapability


class MemoryCapability(BaseCapability):
    name = "memory"
    description = """
    记忆管理能力:
    - 保存长期记忆
    - 读取记忆
    - 列出所有记忆
    - 删除记忆
    """
    _tool_module = "agent.tools.memory"
