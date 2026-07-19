"""工作流上下文 - 统一管理所有工作流共享的参数"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class WorkflowContext:
    query: str = ""
    conv_id: str = ""
    context: str = ""
    skill_context: str = ""
    cap_desc: str = ""
    user_profile: str = ""
    project_name: Optional[str] = None
    project_path: Optional[str] = None
    images: List[Dict[str, Any]] = field(default_factory=list)
    has_images: bool = False
    files: List[Dict[str, Any]] = field(default_factory=list)  # 结构化文件块（text/image）
    pending_info: str = ""
    provided_project_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "conv_id": self.conv_id,
            "context": self.context,
            "skill_context": self.skill_context,
            "cap_desc": self.cap_desc,
            "user_profile": self.user_profile,
            "project_name": self.project_name,
            "project_path": self.project_path,
            "images": self.images,
            "has_images": self.has_images,
            "files": self.files,
            "pending_info": self.pending_info,
            "provided_project_path": self.provided_project_path,
        }
