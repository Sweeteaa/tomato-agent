from pathlib import Path
from datetime import datetime
import json
from app.config import WORKSPACE


def list_tasks():
    tasks_dir = WORKSPACE / "tasks"
    if not tasks_dir.exists():
        return []
    files = sorted(tasks_dir.glob("*.md"))
    return [{"name": f.stem, "file": f.name} for f in files]


def get_task(name: str):
    file_path = WORKSPACE / "tasks" / f"{name}.md"
    if not file_path.exists():
        return None
    return {"name": name, "content": file_path.read_text(encoding="utf-8")}


def get_pending_tasks():
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
    pending_path = WORKSPACE / "tasks" / "pending.md"
    if not pending_path.exists():
        return {"status": "not_found"}
    
    content = pending_path.read_text(encoding="utf-8")
    task_header = f"## {conv_id} |"
    
    lines = content.split('\n')
    new_lines = []
    in_task = False
    skip_until = False
    
    for line in lines:
        if line.startswith(task_header):
            in_task = True
            skip_until = True
        elif skip_until and line.startswith('## '):
            in_task = False
            skip_until = False
        
        if not skip_until:
            new_lines.append(line)
    
    pending_path.write_text('\n'.join(new_lines), encoding="utf-8")
    return {"status": "deleted", "task_id": conv_id}
