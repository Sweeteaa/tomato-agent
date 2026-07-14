"""Workspace 服务 — API 层

scan_dir 委托给 agent/tools/filesystem.py:list_dir，
保留 API 端点专用的 get_workspace。
"""

from pathlib import Path
from app.config import WORKSPACE
import json


def scan_dir(path: Path, depth: int = 1) -> list:
    """扫描目录 — 委托给 agent/tools/filesystem.py:list_dir"""
    from agent.tools.filesystem import list_dir as _list
    result_str = _list(path=str(path), recursive=True, max_depth=depth)
    try:
        result = json.loads(result_str)
        items = []
        for item in result.get("items", []):
            entry = {"name": item["name"], "type": "dir" if item["type"] == "directory" else "file"}
            if item["type"] == "directory" and "children" in item and depth > 0:
                children = []
                for child in item["children"]:
                    children.append({
                        "name": child["name"],
                        "type": "dir" if child["type"] == "directory" else "file"
                    })
                entry["children"] = children
            items.append(entry)
        return items
    except (json.JSONDecodeError, KeyError):
        # fallback: 简单遍历
        items = []
        for child in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
            item = {"name": child.name, "type": "dir" if child.is_dir() else "file"}
            if child.is_dir() and depth > 0:
                item["children"] = scan_dir(child, depth - 1)
            items.append(item)
        return items


def get_workspace():
    """获取 workspace 概览 — API 端点专用"""
    if not WORKSPACE.exists():
        return {"error": "Workspace not found"}

    result = {}
    for child in WORKSPACE.iterdir():
        if child.is_dir():
            result[child.name] = scan_dir(child)
    return {"workspace": result}
