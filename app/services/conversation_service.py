import json
from datetime import datetime
from app.config import WORKSPACE


def _generate_id() -> str:
    """生成日期时间格式的对话 ID"""
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def list_conversations():
    conv_dir = WORKSPACE / "conversations"
    if not conv_dir.exists():
        return []
    files = sorted(conv_dir.glob("*.json"), reverse=True)
    result = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            preview = ""
            for msg in data.get("messages", []):
                if msg["role"] == "user":
                    preview = msg["content"][:40]
                    break
            result.append({
                "id": f.stem,
                "file": f.name,
                "created_at": data.get("created_at", ""),
                "preview": preview
            })
        except (json.JSONDecodeError, KeyError):
            result.append({"id": f.stem, "file": f.name, "created_at": "", "preview": ""})
    return result


def create_conversation() -> dict:
    """创建新对话，返回对话数据"""
    conv_dir = WORKSPACE / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    
    conv_id = _generate_id()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conv_data = {
        "id": conv_id,
        "created_at": now,
        "messages": []
    }
    
    file_path = conv_dir / f"{conv_id}.json"
    file_path.write_text(json.dumps(conv_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return conv_data


def get_conversation(conv_id: str):
    file_path = WORKSPACE / "conversations" / f"{conv_id}.json"
    if not file_path.exists():
        return None
    return json.loads(file_path.read_text(encoding="utf-8"))


def save_conversation(conv_id: str, data: dict):
    conv_dir = WORKSPACE / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    file_path = conv_dir / f"{conv_id}.json"
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "saved", "file": file_path.name}


def append_conversation(
    query: str,
    response: str,
    tool_executions: list = None,
    conv_id: str = None,
    trace: list = None,
    plan: dict = None,
):
    """追加对话记录。如果 conv_id 为空则自动创建新对话。

    trace: 完整的执行轨迹（thinking/tool/result 步骤），用于历史回放
    plan:  执行计划（steps + requires_planning 等）
    """
    conv_dir = WORKSPACE / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)

    if conv_id:
        file_path = conv_dir / f"{conv_id}.json"
        if file_path.exists():
            conv_data = json.loads(file_path.read_text(encoding="utf-8"))
        else:
            conv_data = {"id": conv_id, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "messages": []}
    else:
        conv_data = create_conversation()
        file_path = conv_dir / f"{conv_data['id']}.json"

    conv_data["messages"].append({"role": "user", "content": query})
    if tool_executions:
        conv_data["messages"].append({"role": "assistant", "content": f"已执行工具操作: {json.dumps(tool_executions, ensure_ascii=False)}"})
    conv_data["messages"].append({"role": "assistant", "content": response})

    # 保存结构化思考过程，用于历史回放
    if trace or plan:
        if "thinking_records" not in conv_data:
            conv_data["thinking_records"] = []
        conv_data["thinking_records"].append({
            "plan": plan or {},
            "trace": trace or [],
        })

    file_path.write_text(json.dumps(conv_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return conv_data


def delete_conversation(conv_id: str):
    file_path = WORKSPACE / "conversations" / f"{conv_id}.json"
    if not file_path.exists():
        return None
    file_path.unlink()
    return {"status": "deleted", "id": conv_id}
