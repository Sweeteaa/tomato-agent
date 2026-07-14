"""文档管理能力 — 技能文档和任务清单"""

from agent.capabilities.base import BaseCapability


class DocumentCapability(BaseCapability):
    name = "document"
    description = """
    文档管理能力:
    - 保存/读取技能文档
    - 列出所有技能
    - 保存/读取任务清单
    - 列出所有任务
    """
    _tool_module = "agent.tools.document"
