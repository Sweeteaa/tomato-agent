"""任务服务 — API 层

负责执行状态管理（Execution Task Manager），
保存 Plan 的执行状态，而非简单的待办列表。
"""

from pathlib import Path
from datetime import datetime
import json
import uuid
from app.config import WORKSPACE
from agent.exceptions import ResourceNotFoundError

PENDING_PATH = WORKSPACE / "tasks" / "pending.md"


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


def create_execution_task(plan: dict) -> dict:
    """创建执行任务，保存Plan执行状态"""
    tasks_dir = WORKSPACE / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    task_id = f"TASK{uuid.uuid4().hex[:8].upper()}"
    plan_id = plan.get("plan_id", "")
    project = plan.get("project", "")
    requirement_id = plan.get("requirement_id", "")
    goal = plan.get("goal", "")
    steps = plan.get("steps", [])

    task_content = [
        "# Execution Task",
        "",
        f"## {task_id}",
        "",
        "### 基本信息",
        f"- task_id: {task_id}",
        f"- plan_id: {plan_id}",
        f"- project: {project}",
        f"- requirement: {requirement_id}",
        f"- goal: {goal}",
        f"- status: running",
        f"- created_at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "### 执行步骤",
        "",
    ]

    for step in steps:
        step_id = step.get("id", "")
        step_type = step.get("type", "")
        step_title = step.get("title", "")
        step_file = step.get("target_file", "")
        status = step.get("status", "pending")

        checkbox = "[x]" if status == "done" else "[ ]"
        type_label = _get_step_type_label(step_type)

        task_content.append(f"{checkbox} **步骤 {step_id}** ({type_label})")
        task_content.append(f"   - {step_title}")
        if step_file:
            task_content.append(f"   - 文件: {step_file}")

    task_content.append("")

    pending_content = ""
    if PENDING_PATH.exists():
        pending_content = PENDING_PATH.read_text(encoding="utf-8")
    else:
        pending_content = "# 执行任务列表\n\n"

    new_task_section = "\n".join(task_content)
    pending_content += new_task_section

    PENDING_PATH.write_text(pending_content, encoding="utf-8")

    task_json = {
        "task_id": task_id,
        "plan_id": plan_id,
        "project": project,
        "requirement_id": requirement_id,
        "goal": goal,
        "status": "running",
        "total_steps": len(steps),
        "completed_steps": sum(1 for s in steps if s.get("status") == "done"),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    return task_json


def update_task_step(task_id: str, step_id: int, status: str):
    """更新任务步骤状态"""
    if not PENDING_PATH.exists():
        return {"status": "not_found"}

    content = PENDING_PATH.read_text(encoding="utf-8")
    lines = content.split("\n")
    new_lines = []
    in_task = False
    task_start_line = None

    for i, line in enumerate(lines):
        if line.startswith(f"## {task_id}"):
            in_task = True
            task_start_line = i
        elif in_task and line.startswith("## ") and i > task_start_line:
            in_task = False

        if in_task:
            step_pattern = f"**步骤 {step_id}**"
            if step_pattern in line:
                if status == "done":
                    if "[ ]" in line:
                        line = line.replace("[ ]", "[x]")
                elif status == "pending":
                    if "[x]" in line:
                        line = line.replace("[x]", "[ ]")
                elif status == "in_progress":
                    if "[ ]" in line:
                        line = line.replace("[ ]", "[~]")
                    elif "[x]" in line:
                        line = line.replace("[x]", "[~]")

        new_lines.append(line)

    PENDING_PATH.write_text("\n".join(new_lines), encoding="utf-8")

    return {"status": "updated", "task_id": task_id, "step_id": step_id, "status": status}


def get_task_status(task_id: str) -> dict:
    """获取任务状态"""
    if not PENDING_PATH.exists():
        return {"status": "not_found"}

    content = PENDING_PATH.read_text(encoding="utf-8")
    lines = content.split("\n")

    in_task = False
    task_info = {}
    steps = []

    for line in lines:
        if line.startswith(f"## {task_id}"):
            in_task = True
            task_info["task_id"] = task_id
        elif in_task and line.startswith("## ") and line != f"## {task_id}":
            break

        if in_task:
            if line.startswith("- task_id:"):
                task_info["task_id"] = line.split(":")[1].strip()
            elif line.startswith("- plan_id:"):
                task_info["plan_id"] = line.split(":")[1].strip()
            elif line.startswith("- project:"):
                task_info["project"] = line.split(":")[1].strip()
            elif line.startswith("- requirement:"):
                task_info["requirement_id"] = line.split(":")[1].strip()
            elif line.startswith("- goal:"):
                task_info["goal"] = line.split(":")[1].strip()
            elif line.startswith("- status:"):
                task_info["status"] = line.split(":")[1].strip()
            elif line.startswith("[ ] ") or line.startswith("[x] ") or line.startswith("[~] "):
                step_status = "done" if "[x]" in line else ("in_progress" if "[~]" in line else "pending")
                steps.append({"status": step_status, "text": line[4:].strip()})

    if not task_info:
        return {"status": "not_found"}

    task_info["total_steps"] = len(steps)
    task_info["completed_steps"] = sum(1 for s in steps if s["status"] == "done")
    task_info["steps"] = steps

    return task_info


def get_pending_tasks():
    """获取待办任务 — graph_service 内部调用"""
    if not PENDING_PATH.exists():
        return {"count": 0, "tasks": [], "content": "# 执行任务列表\n\n暂无未完成任务"}

    content = PENDING_PATH.read_text(encoding="utf-8")
    tasks = []

    lines = content.split('\n')
    current_task = None
    in_steps = False

    for line in lines:
        if line.startswith('## '):
            if current_task:
                tasks.append(current_task)
            parts = line[3:].strip()
            current_task = {
                "id": parts,
                "steps": [],
                "project": "",
                "goal": "",
            }
            in_steps = False
        elif current_task and line.startswith('- project:'):
            current_task["project"] = line.split(":")[1].strip()
        elif current_task and line.startswith('- goal:'):
            current_task["goal"] = line.split(":")[1].strip()
        elif current_task and line.startswith('### 执行步骤'):
            in_steps = True
        elif in_steps and current_task and (line.startswith('- [ ] ') or line.startswith('- [x] ') or line.startswith('- [~] ')):
            status = "done" if "[x]" in line else ("in_progress" if "[~]" in line else "pending")
            current_task["steps"].append({"text": line[6:], "status": status})

    if current_task:
        tasks.append(current_task)

    return {"count": len(tasks), "tasks": tasks, "content": content}


def complete_task(task_id: str):
    """完成任务 — API 路由调用"""
    if not PENDING_PATH.exists():
        return {"status": "not_found"}

    content = PENDING_PATH.read_text(encoding="utf-8")
    lines = content.split('\n')
    new_lines = []
    in_task = False
    task_start_line = None

    for i, line in enumerate(lines):
        if line.startswith(f"## {task_id}"):
            in_task = True
            task_start_line = i
        elif in_task and line.startswith("## ") and i > task_start_line:
            in_task = False

        if in_task:
            if line.startswith("- status:"):
                line = "- status: completed"
            elif line.startswith('- [ ] '):
                line = line.replace('- [ ] ', '- [x] ')
            elif line.startswith('- [~] '):
                line = line.replace('- [~] ', '- [x] ')

        new_lines.append(line)

    PENDING_PATH.write_text('\n'.join(new_lines), encoding="utf-8")
    return {"status": "completed", "task_id": task_id}


def delete_task(task_id: str):
    """删除任务 — API 路由调用"""
    if not PENDING_PATH.exists():
        return {"status": "not_found"}

    content = PENDING_PATH.read_text(encoding="utf-8")
    lines = content.split('\n')
    new_lines = []
    in_task = False
    task_start_line = None

    for i, line in enumerate(lines):
        if line.startswith(f"## {task_id}"):
            in_task = True
            task_start_line = i
        elif in_task and line.startswith("## ") and i > task_start_line:
            in_task = False

        if not in_task:
            new_lines.append(line)

    PENDING_PATH.write_text('\n'.join(new_lines), encoding="utf-8")
    return {"status": "deleted", "task_id": task_id}


def save_pending_task(conv_id: str, plan: list):
    """保存待办任务（兼容旧接口）"""
    tasks_dir = WORKSPACE / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if PENDING_PATH.exists():
        content = PENDING_PATH.read_text(encoding="utf-8")
    else:
        content = "# 执行任务列表\n\n"

    task_header = f"## {conv_id} | {now}\n"
    if task_header not in content:
        content += task_header
        content += "- project: \n"
        content += "- goal: \n"
        content += "### 执行步骤\n"
        for step in plan:
            step_text = step.get('step', '') or step.get('thought', '')
            if step_text:
                content += f"- [ ] {step_text}\n"
        content += "\n"

    PENDING_PATH.write_text(content, encoding="utf-8")
    return {"status": "saved", "task_id": conv_id, "steps": len(plan)}


def _get_step_type_label(step_type: str) -> str:
    """获取步骤类型标签"""
    labels = {
        "analysis": "分析",
        "modify": "修改",
        "create": "创建",
        "api": "接口",
        "test": "测试",
        "review": "审查",
    }
    return labels.get(step_type, step_type)
