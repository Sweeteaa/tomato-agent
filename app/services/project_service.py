from pathlib import Path
from app.config import WORKSPACE


def list_projects():
    proj_dir = WORKSPACE / "projects"
    if not proj_dir.exists():
        return []
    projects = []
    for child in sorted(proj_dir.iterdir()):
        if child.is_dir():
            docs = [f.name for f in child.iterdir() if f.is_file()]
            projects.append({"name": child.name, "docs": docs})
    return projects


def get_project_doc(project: str, doc: str):
    file_path = WORKSPACE / "projects" / project / doc
    if not file_path.exists():
        return None
    return {"project": project, "doc": doc, "content": file_path.read_text(encoding="utf-8")}