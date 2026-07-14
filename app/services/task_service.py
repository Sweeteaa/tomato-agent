"""任务服务 — API 层

重复的 CRUD 操作委托给 agent/tools/document.py，
保留 pending tasks 等独有功能。
"""

from pathlib import Path
from datetime import datetime
import json
from app.config import WORKSPACE
from agent.exceptions import ResourceNotFoundError


def list_tasks():
    """列出所有任务 — 委托给 agent/tools/document.py"""
    from agent.tools.document import list_tasks as _list
    result = _list()
    if result.startswith("暂无"):
        return []
    items = []
    for line in result.strip().split("\n"):
        name = line.replace("📄 ", "").strip()
        if name:
            items.append({"name": name, "file": f"{name}.md"})
    return items


def get_task(name: str):
    """读取任务 — 委托给 agent/tools/document.py"""
    from agent.tools.document import read_task
    try:
        content = read_task(name)
        return {"name": name, "content": content}
    except ResourceNotFoundError:
        return None


# ─── 以下为独有功能，不委托 ───

def get_pending_tasks():
    """获取待办任务 — graph_service 内部调用"""
    pending_path = WORKSPACE / "tasks" / "pending.md"
    if not pending_path.exists():
        return {"count": 0, "tasks": [], "content": "# 待办任务\n\n暂无未完成任务"}

    content = pending_path.read_text(encoding="utf-8")
    tasks = []

    lines = content.split('\n')
    current_task = None

    for line in lines:
        if line.startswith('## '):
            if current_task:
                tasks.append(current_task)
            parts = line[3:].split(' | ')
            current_task = {
                "id": parts[0] if len(parts) > 0 else "",
                "created_at": parts[1] if len(parts) > 1 else "",
                "steps": []
            }
        elif line.startswith('- [ ] ') and current_task:
            current_task["steps"].append(line[6:])

    if current_task:
        tasks.append(current_task)

    return {"count": len(tasks), "tasks": tasks, "content": content}


def save_pending_task(conv_id: str, plan: list):
    """保存待办任务 — graph_service 内部调用"""
    tasks_dir = WORKSPACE / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    pending_path = tasks_dir / "pending.md"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if pending_path.exists():
        content = pending_path.read_text(encoding="utf-8")
    else:
        content = "# 待办任务\n\n"

    task_header = f"## {conv_id} | {now}\n"
    if task_header not in content:
        content += task_header
        for step in plan:
            content += f"- [ ] {step.get('step', '')}\n"
        content += "\n"

    pending_path.write_text(content, encoding="utf-8")
    return {"status": "saved", "task_id": conv_id, "steps": len(plan)}


def complete_task(conv_id: str):
    """完成任务 — API 路由调用"""
    pending_path = WORKSPACE / "tasks" / "pending.md"
    if not pending_path.exists():
        return {"status": "not_found"}

    content = pending_path.read_text(encoding="utf-8")
    task_header = f"## {conv_id} |"

    lines = content.split('\n')
    new_lines = []
    in_task = False

    for line in lines:
        if line.startswith(task_header):
            in_task = True
        elif in_task and line.startswith('## '):
            in_task = False

        if in_task and line.startswith('- [ ] '):
            new_lines.append(line.replace('- [ ] ', '- [x] '))
        else:
            new_lines.append(line)

    pending_path.write_text('\n'.join(new_lines), encoding="utf-8")
    return {"status": "completed", "task_id": conv_id}


def delete_task(conv_id: str):
    """删除任务 — API 路由调用"""
    pending_path = WORKSPACE / "tasks" / "pending.md"
    if not pending_path.exists():
        return {"status": "not_found"}

    content = pending_path.read_text(encoding="utf-8")
    task_header = f"## {conv_id} |"

    lines = content.split('\n')
    new_lines = []
    skip_until = False

    for line in lines:
        if line.startswith(task_header):
            skip_until = True
        elif skip_until and line.startswith('## '):
            skip_until = False

        if not skip_until:
            new_lines.append(line)

    pending_path.write_text('\n'.join(new_lines), encoding="utf-8")
    return {"status": "deleted", "task_id": conv_id}
