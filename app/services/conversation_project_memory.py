import json
from datetime import datetime
from pathlib import Path

from app.config import WORKSPACE

CONVERSATION_MEMORY_DIR = WORKSPACE / "conversation_memory"


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_memory_file(conv_id: str) -> Path:
    CONVERSATION_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    memory_file = CONVERSATION_MEMORY_DIR / f"{conv_id}.json"
    if not memory_file.exists():
        memory_file.write_text(
            json.dumps({
                "conv_id": conv_id,
                "current_project": None,
                "project_path": None,
                "updated_at": _now_str(),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return memory_file


def get_conversation_memory(conv_id: str) -> dict:
    memory_file = _ensure_memory_file(conv_id)
    try:
        return json.loads(memory_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "conv_id": conv_id,
            "current_project": None,
            "project_path": None,
            "updated_at": _now_str(),
        }


def set_conversation_project(conv_id: str, project_name: str, project_path: str):
    memory_file = _ensure_memory_file(conv_id)
    data = {
        "conv_id": conv_id,
        "current_project": project_name,
        "project_path": project_path,
        "updated_at": _now_str(),
    }
    memory_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_conversation_project(conv_id: str):
    memory_file = _ensure_memory_file(conv_id)
    data = {
        "conv_id": conv_id,
        "current_project": None,
        "project_path": None,
        "updated_at": _now_str(),
    }
    memory_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_current_project_for_conversation(conv_id: str) -> tuple[str, str] | tuple[None, None]:
    memory = get_conversation_memory(conv_id)
    return memory.get("current_project"), memory.get("project_path")
