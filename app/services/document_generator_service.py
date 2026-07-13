import json
from pathlib import Path
from typing import Dict

from app.config import WORKSPACE
from app.services.artifact_service import write_artifact


def _load_project_structure(project_name: str) -> Dict:
    path = WORKSPACE / "projects" / project_name / "structure.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def generate_documents(task_id: str, requirement: Dict, target_project: str | None) -> Dict:
    # requirement is a dict; produce change-plan.md, impact-files.md, test-cases.md
    project_struct = _load_project_structure(target_project) if target_project else {}

    # requirement.md already produced by parser; produce change plan
    cp_lines = [f"# 改造建议 ({target_project or '未指定项目'})", ""]
    cp_lines.append("## 概要")
    cp_lines.append(requirement.get("summary", ""))
    cp_lines.append("")

    cp_lines.append("## 影响范围")
    pages = project_struct.get("pages", [])
    components = project_struct.get("components", [])
    if pages:
        cp_lines.append("- 可能影响页面目录或文件示例:")
        cp_lines.extend(f"  - {p}" for p in pages[:10])
    if components:
        cp_lines.append("- 可能影响公共组件:")
        cp_lines.extend(f"  - {c}" for c in components[:10])

    cp_lines.append("")
    cp_lines.append("## 建议步骤")
    cp_lines.append("1. 确认目标页面与数据接口")
    cp_lines.append("2. 在本地仓库中标注候选文件并评审")
    cp_lines.append("3. 生成变更清单与测试用例")

    write_artifact(task_id, "change-plan.md", "\n".join(cp_lines))

    impact_lines = [f"# 影响文件候选 ({target_project or '未指定项目'})", ""]
    if pages:
        impact_lines.append("## 页面候选")
        impact_lines.extend(f"- {p}" for p in pages[:50])
    else:
        impact_lines.append("- 未识别到页面文件")
    if components:
        impact_lines.append("\n## 组件候选")
        impact_lines.extend(f"- {c}" for c in components[:50])

    write_artifact(task_id, "impact-files.md", "\n".join(impact_lines))

    tests = ["# 测试用例建议", "", "## 正常流", "", "- 验证新筛选项生效", "", "## 边界与异常", "", "- 无数据时提示友好"]
    write_artifact(task_id, "test-cases.md", "\n".join(tests))

    return {"generated": ["change-plan.md", "impact-files.md", "test-cases.md"]}
