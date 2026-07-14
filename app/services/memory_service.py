"""记忆服务 — API 层

重复的 CRUD 操作委托给 agent/tools/memory.py，
保留 user_profile 等独有功能。
"""

from pathlib import Path
from app.config import WORKSPACE
from agent.exceptions import ResourceNotFoundError


def list_memory():
    """列出所有记忆 — 委托给 agent/tools/memory.py"""
    from agent.tools.memory import list_memory as _list
    result = _list()
    # agent 版返回字符串，API 层需要 dict 列表
    if result.startswith("暂无"):
        return []
    items = []
    for line in result.strip().split("\n"):
        name = line.replace("📄 ", "").strip()
        if name:
            items.append({"name": name, "file": f"{name}.md"})
    return items


def get_memory(name: str):
    """读取记忆 — 委托给 agent/tools/memory.py"""
    from agent.tools.memory import read_memory
    try:
        content = read_memory(name)
        return {"name": name, "content": content}
    except ResourceNotFoundError:
        return None


def save_memory(name: str, content: str):
    """保存记忆 — 委托给 agent/tools/memory.py"""
    from agent.tools.memory import save_memory as _save
    _save(name, content)
    return {"status": "saved", "file": f"{name}.md"}


# ─── 以下为独有功能，不委托 ───

def get_user_profile():
    """获取用户画像 — graph_service 内部调用，不作为 LLM 工具"""
    profile_path = WORKSPACE / "memory" / "user_profile.md"
    if not profile_path.exists():
        return {"name": "user_profile", "content": "# 用户画像\n\n## 技术栈偏好\n\n## 常用技能\n\n## 代码风格\n\n## 其他偏好\n"}
    return {"name": "user_profile", "content": profile_path.read_text(encoding="utf-8")}


def update_profile(preferences: dict):
    """更新用户画像 — graph_service 内部调用，不作为 LLM 工具"""
    profile_path = WORKSPACE / "memory" / "user_profile.md"
    mem_dir = WORKSPACE / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)

    if profile_path.exists():
        content = profile_path.read_text(encoding="utf-8")
    else:
        content = "# 用户画像\n\n## 技术栈偏好\n\n## 常用技能\n\n## 代码风格\n\n## 其他偏好\n"

    if preferences.get("tech_stack"):
        tech_section = "## 技术栈偏好\n"
        for tech in preferences["tech_stack"]:
            if f"- {tech}" not in content:
                content = content.replace(tech_section, tech_section + f"- {tech}\n")

    if preferences.get("skills"):
        skills_section = "## 常用技能\n"
        for skill in preferences["skills"]:
            if f"- {skill}" not in content:
                content = content.replace(skills_section, skills_section + f"- {skill}\n")

    if preferences.get("code_style"):
        style_section = "## 代码风格\n"
        for style in preferences["code_style"]:
            if f"- {style}" not in content:
                content = content.replace(style_section, style_section + f"- {style}\n")

    if preferences.get("other"):
        other_section = "## 其他偏好\n"
        for item in preferences["other"]:
            if f"- {item}" not in content:
                content = content.replace(other_section, other_section + f"- {item}\n")

    profile_path.write_text(content, encoding="utf-8")
    return {"status": "updated", "file": "user_profile.md"}
