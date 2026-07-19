"""workflow_utils — 工作流共享工具函数"""

import json
import hashlib
import logging
from datetime import datetime
from pathlib import Path

from app.config import WORKSPACE

logger = logging.getLogger("gt_agent.workflows.utils")

# 知识库存储目录（项目扫描保存到 workspace/memory/{project_name}/）
MEMORY_DIR = WORKSPACE / "memory"
PROJECTS_DIR = WORKSPACE / "projects"


def load_project_knowledge(project_name: str) -> dict:
    """加载项目知识

    优先从 workspace/memory/{project_name}/project.json 加载（项目扫描保存位置）
    回退到 workspace/projects/{project_name}/knowledge.json（旧格式兼容）
    """
    # 优先路径：workspace/memory/{project_name}/project.json
    memory_path = MEMORY_DIR / project_name / "project.json"
    if memory_path.exists():
        try:
            return json.loads(memory_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("项目知识 JSON 解析失败: %s", memory_path)

    # 回退路径：workspace/projects/{project_name}/knowledge.json（旧格式）
    knowledge_path = PROJECTS_DIR / project_name / "knowledge.json"
    if knowledge_path.exists():
        try:
            return json.loads(knowledge_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("项目知识 JSON 解析失败: %s", knowledge_path)

    return None


def list_existing_projects() -> list:
    """列出所有已知项目（合并 memory/ 和 projects/ 两个目录）"""
    seen_names = set()
    projects = []

    # 扫描 workspace/memory/ 目录（主要知识存储位置）
    if MEMORY_DIR.exists():
        for child in MEMORY_DIR.iterdir():
            if child.is_dir() and child.name not in ("episodic", "semantic"):
                knowledge = load_project_knowledge(child.name)
                if knowledge:
                    projects.append({
                        "name": child.name,
                        "has_knowledge": True,
                        "framework": knowledge.get("framework", ""),
                        "page_count": len(knowledge.get("pages", [])),
                        "source": "memory",
                    })
                    seen_names.add(child.name)

    # 扫描 workspace/projects/ 目录（旧格式 + 项目副本）
    if PROJECTS_DIR.exists():
        for child in PROJECTS_DIR.iterdir():
            if child.is_dir() and child.name not in seen_names:
                knowledge = load_project_knowledge(child.name)
                projects.append({
                    "name": child.name,
                    "has_knowledge": knowledge is not None,
                    "framework": knowledge.get("framework", "") if knowledge else "",
                    "page_count": len(knowledge.get("pages", [])) if knowledge else 0,
                    "source": "projects",
                })

    return projects


def get_last_scanned_project() -> tuple:
    """获取最近扫描的项目（按文件修改时间）

    Returns:
        (project_name, project_path) 或 (None, None)
    """
    latest_time = 0
    latest_name = None
    latest_path = None

    # 检查 workspace/memory/ 下的项目目录
    if MEMORY_DIR.exists():
        for child in MEMORY_DIR.iterdir():
            if child.is_dir() and child.name not in ("episodic", "semantic"):
                project_json = child / "project.json"
                if project_json.exists():
                    mtime = project_json.stat().st_mtime
                    if mtime > latest_time:
                        latest_time = mtime
                        latest_name = child.name
                        try:
                            data = json.loads(project_json.read_text(encoding="utf-8"))
                            latest_path = data.get("project_path", "")
                        except Exception:
                            latest_path = ""

    if latest_name:
        return latest_name, latest_path
    return None, None


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
    """根据 query 文本匹配最相关的项目"""
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


def resolve_project_for_document(query: str, conv_id: str = None, project_name: str = None) -> tuple:
    """为文档工作流解析目标项目

    按优先级尝试：
    1. query 中显式指定的项目路径
    2. conv_id 关联的项目（来自 conversation_project_memory）
    3. query 文本匹配的项目名称
    4. 最近扫描的项目（全局回退）

    Returns:
        (project_name, project_path, project_knowledge)
    """
    import re

    resolved_name = None
    resolved_path = None

    # 1. query 中显式指定的项目路径
    if query:
        if query.startswith("项目路径:"):
            rest = query[5:].strip()
            # 取第一个空白分隔的 token 作为路径，其余保留为后续 query
            tokens = rest.split(None, 1)
            resolved_path = tokens[0] if tokens else ""
            # 注意：剩余 query 不再回写（由调用方 graph_service 处理）
            resolved_name = Path(resolved_path).name if resolved_path else None
        else:
            path_match = re.search(r'(D:/[^\s]+|/[a-zA-Z]/[^\s]+|[a-zA-Z]:\\[^\s]+|/Users/[^\s]+|/home/[^\s]+)', query)
            if path_match:
                resolved_path = path_match.group(1)
                resolved_name = Path(resolved_path).name

    # 2. conv_id 关联的项目
    if not resolved_name and conv_id:
        from app.services.conversation_project_memory import get_current_project_for_conversation
        conv_name, conv_path = get_current_project_for_conversation(conv_id)
        if conv_name:
            resolved_name = conv_name
            resolved_path = conv_path

    # 3. query 文本匹配
    if not resolved_name and query:
        matched = find_relevant_project(query)
        if matched:
            resolved_name = matched

    # 4. 传入的 project_name
    if not resolved_name and project_name:
        resolved_name = project_name

    # 5. 最近扫描的项目（全局回退）
    if not resolved_name:
        last_name, last_path = get_last_scanned_project()
        if last_name:
            resolved_name = last_name
            resolved_path = last_path
            logger.info("文档工作流回退使用最近扫描项目: %s", resolved_name)

    # 加载知识
    knowledge = None
    if resolved_name:
        knowledge = load_project_knowledge(resolved_name)

    return resolved_name, resolved_path, knowledge


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
