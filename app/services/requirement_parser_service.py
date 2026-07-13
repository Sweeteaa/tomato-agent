import json
import re
from typing import Dict

from app.services.artifact_service import write_artifact


def _summarize_text(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return ""
    # title = first heading-like line
    title = lines[0]
    body = "\n".join(lines[1:6])
    return f"{title}\n\n{body}"


def parse_requirement_from_text(task_id: str, text: str) -> Dict:
    title_match = re.search(r"^#\s*(.+)$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else (text.splitlines()[0] if text else "需求")

    bullets = re.findall(r"^-\s+(.+)$", text, re.MULTILINE)
    interactions = [b for b in bullets if any(k in b.lower() for k in ("新增", "增加", "支持", "导出", "筛选", "切换"))]

    requirement = {
        "title": title,
        "summary": _summarize_text(text),
        "raw": text,
        "interactions": interactions,
        "fields": [],
        "apis": [],
        "acceptance_criteria": [],
    }

    write_artifact(task_id, "requirement.json", requirement, as_json=True)

    md_lines = [f"# {requirement['title']}", "", "## 摘要", "", requirement["summary"], "", "## 交互", ""]
    if interactions:
        md_lines.extend(f"- {i}" for i in interactions)
    else:
        md_lines.append("- 无明显交互描述")

    write_artifact(task_id, "requirement.md", "\n".join(md_lines))
    return requirement
