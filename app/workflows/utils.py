"""workflow_utils — 工作流共享工具函数"""

import json
import hashlib
from datetime import datetime
from pathlib import Path

from app.config import WORKSPACE


def load_project_knowledge(project_name: str) -> dict:
    knowledge_path = WORKSPACE / "projects" / project_name / "knowledge.json"
    if knowledge_path.exists():
        try:
            return json.loads(knowledge_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def list_existing_projects() -> list:
    projects_dir = WORKSPACE / "projects"
    if not projects_dir.exists():
        return []
    projects = []
    for child in projects_dir.iterdir():
        if child.is_dir():
            knowledge = load_project_knowledge(child.name)
            projects.append({
                "name": child.name,
                "has_knowledge": knowledge is not None,
                "framework": knowledge.get("framework", "") if knowledge else "",
                "page_count": len(knowledge.get("pages", [])) if knowledge else 0,
            })
    return projects


def save_document_summary(document_name: str, summary: str, project_name: str = None) -> str:
    doc_hash = hashlib.md5(document_name.encode('utf-8')).hexdigest()[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c for c in document_name if c.isalnum() or c in (' ', '_', '-')).strip()[:50]
    filename = f"{timestamp}_{doc_hash}_{safe_name}.md"
    
    if project_name:
        docs_dir = WORKSPACE / "projects" / project_name / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        save_path = docs_dir / filename
    else:
        docs_dir = WORKSPACE / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        save_path = docs_dir / filename
    
    save_path.write_text(summary, encoding="utf-8")
    return str(save_path)


def list_document_summaries(project_name: str = None) -> list:
    if project_name:
        docs_dir = WORKSPACE / "projects" / project_name / "docs"
    else:
        docs_dir = WORKSPACE / "docs"
    
    if not docs_dir.exists():
        return []
    
    summaries = []
    for file in sorted(docs_dir.iterdir(), reverse=True):
        if file.is_file() and file.suffix == '.md':
            try:
                content = file.read_text(encoding="utf-8", errors="ignore")
                summaries.append({
                    "filename": file.name,
                    "path": str(file),
                    "size": file.stat().st_size,
                    "modified": datetime.fromtimestamp(file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "preview": content[:200] + "..." if len(content) > 200 else content,
                })
            except Exception:
                pass
    
    return summaries


def find_relevant_project(query: str) -> str:
    projects = list_existing_projects()
    if not projects:
        return ""

    lower_query = query.lower()
    matched_projects = []

    for project in projects:
        score = 0
        if project["name"].lower() in lower_query:
            score += 10
        if project["framework"].lower() in lower_query:
            score += 5
        if any(kw in lower_query for kw in ["vue", "react", "angular"]):
            if project["framework"].lower().startswith(kw.split()[0]):
                score += 3
        if score > 0:
            matched_projects.append((project, score))

    if matched_projects:
        matched_projects.sort(key=lambda x: x[1], reverse=True)
        return matched_projects[0][0]["name"]

    return ""


def build_project_context(project_name: str) -> str:
    from app.services.project_registry_service import get_registered_project
    
    project_info = get_registered_project(project_name)
    knowledge = load_project_knowledge(project_name)
    
    if not knowledge and not project_info:
        return ""
    
    parts = [f"## 当前项目: {project_name}"]
    
    if project_info:
        parts.append(f"- 路径: {project_info.get('root_path', '')}")
        parts.append(f"- 框架: {project_info.get('framework', '未知')}")
        parts.append(f"- 构建工具: {project_info.get('build_tool', '未知')}")
        parts.append(f"- 包管理器: {project_info.get('package_manager', '未知')}")
    
    if knowledge:
        pages = knowledge.get('pages', [])
        components = knowledge.get('components', [])
        api_modules = knowledge.get('api_modules', [])
        
        if pages:
            page_names = [p.get('name', '') for p in pages[:10]]
            parts.append(f"\n### 页面列表 ({len(pages)}个)")
            parts.append("\n".join(f"- {name}" for name in page_names))
            if len(pages) > 10:
                parts.append(f"- ... 还有 {len(pages) - 10} 个页面")
        
        if components:
            comp_names = [c.get('name', '') for c in components[:10]]
            parts.append(f"\n### 组件列表 ({len(components)}个)")
            parts.append("\n".join(f"- {name}" for name in comp_names))
            if len(components) > 10:
                parts.append(f"- ... 还有 {len(components) - 10} 个组件")
        
        if api_modules:
            api_names = [a.get('name', '') for a in api_modules[:10]]
            parts.append(f"\n### API模块 ({len(api_modules)}个)")
            parts.append("\n".join(f"- {name}" for name in api_names))
            if len(api_modules) > 10:
                parts.append(f"- ... 还有 {len(api_modules) - 10} 个模块")
    
    return "\n".join(parts)
