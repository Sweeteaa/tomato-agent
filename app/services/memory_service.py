from pathlib import Path
from app.config import WORKSPACE


def list_memory():
    mem_dir = WORKSPACE / "memory"
    if not mem_dir.exists():
        return []
    files = sorted(mem_dir.glob("*.md"))
    return [{"name": f.stem, "file": f.name} for f in files]


def get_memory(name: str):
    file_path = WORKSPACE / "memory" / f"{name}.md"
    if not file_path.exists():
        return None
    return {"name": name, "content": file_path.read_text(encoding="utf-8")}


def save_memory(name: str, content: str):
    mem_dir = WORKSPACE / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    file_path = mem_dir / f"{name}.md"
    file_path.write_text(content, encoding="utf-8")
    return {"status": "saved", "file": file_path.name}


def get_user_profile():
    profile_path = WORKSPACE / "memory" / "user_profile.md"
    if not profile_path.exists():
        return {"name": "user_profile", "content": "# 用户画像\n\n## 技术栈偏好\n\n## 常用技能\n\n## 代码风格\n\n## 其他偏好\n"}
    return {"name": "user_profile", "content": profile_path.read_text(encoding="utf-8")}


def update_profile(preferences: dict):
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
