import json
from pathlib import Path
from typing import Any

from app.config import WORKSPACE


ARTIFACTS_DIR = WORKSPACE / "artifacts"


def _ensure_task_dir(task_id: str) -> Path:
    path = ARTIFACTS_DIR / task_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_artifact(task_id: str, name: str, content: Any, as_json: bool = False) -> Path:
    task_dir = _ensure_task_dir(task_id)
    path = task_dir / name
    if as_json:
        path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        if isinstance(content, (dict, list)):
            path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            path.write_text(str(content), encoding="utf-8")
    return path


def list_artifacts(task_id: str) -> list[dict]:
    task_dir = ARTIFACTS_DIR / task_id
    if not task_dir.exists():
        return []
    results = []
    for child in sorted(task_dir.iterdir()):
        results.append({"name": child.name, "path": str(child), "size": child.stat().st_size})
    return results


def read_artifact(task_id: str, name: str) -> str:
    path = ARTIFACTS_DIR / task_id / name
    if not path.exists():
        raise FileNotFoundError(name)
    return path.read_text(encoding="utf-8")
