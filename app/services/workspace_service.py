from pathlib import Path
from app.config import WORKSPACE


def scan_dir(path: Path, depth: int = 1) -> list:
    items = []
    for child in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
        item = {"name": child.name, "type": "dir" if child.is_dir() else "file"}
        if child.is_dir() and depth > 0:
            item["children"] = scan_dir(child, depth - 1)
        items.append(item)
    return items


def get_workspace():
    if not WORKSPACE.exists():
        return {"error": "Workspace not found"}

    result = {}
    for child in WORKSPACE.iterdir():
        if child.is_dir():
            result[child.name] = scan_dir(child)
    return {"workspace": result}