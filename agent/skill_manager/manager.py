"""Skill 管理器 — 负责创建、修改、查询 Skill（经验层）

Skill 不写代码，只描述：遇到什么任务，应该怎么做，需要哪些能力。
内部通过 filesystem 工具操作文件，而不是直接操作文件系统。
"""

from pathlib import Path
from app.config import WORKSPACE


class SkillManager:
    def __init__(self):
        self.skill_dir = WORKSPACE / "skill"

    def create_skill(self, name: str, content: str) -> str:
        """创建技能文档"""
        file_path = self.skill_dir / f"{name}.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"✅ 技能保存成功: skill/{name}.md"

    def read_skill(self, name: str) -> str:
        """读取技能文档"""
        file_path = self.skill_dir / f"{name}.md"
        if not file_path.exists():
            return f"❌ 技能不存在: {name}"
        return file_path.read_text(encoding="utf-8")

    def update_skill(self, name: str, content: str) -> str:
        """更新技能文档（覆盖）"""
        return self.create_skill(name, content)

    def delete_skill(self, name: str) -> str:
        """删除技能文档"""
        file_path = self.skill_dir / f"{name}.md"
        if not file_path.exists():
            return f"❌ 技能不存在: {name}"
        file_path.unlink()
        return f"✅ 技能删除成功: {name}"

    def list_skills(self) -> list:
        """列出所有技能"""
        if not self.skill_dir.exists():
            return []
        return [f.stem for f in sorted(self.skill_dir.glob("*.md"))]

    def get_skill_context(self, query: str) -> str:
        """根据查询匹配相关技能，返回上下文"""
        results = []
        if not self.skill_dir.exists():
            return ""
        for f in self.skill_dir.glob("*.md"):
            content = f.read_text(encoding="utf-8", errors="ignore")
            if query.lower() in content.lower():
                preview = content[:500] + "..." if len(content) > 500 else content
                results.append(f"【skill/{f.name}】\n{preview}\n")
        return "\n".join(results)
