from fastapi import APIRouter, HTTPException
from app.services.task_service import list_tasks, get_task, get_pending_tasks, save_pending_task, complete_task, delete_task

router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/tasks")
async def list_tasks_endpoint():
    return list_tasks()


@router.get("/tasks/pending")
async def get_pending_tasks_endpoint():
    return get_pending_tasks()


@router.get("/tasks/{name}")
async def get_task_endpoint(name: str):
    result = get_task(name)
    if result is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.post("/tasks/pending")
async def save_pending_task_endpoint(data: dict):
    return save_pending_task(data.get("conv_id", ""), data.get("plan", []))


@router.post("/tasks/pending/{conv_id}/complete")
async def complete_task_endpoint(conv_id: str):
    return complete_task(conv_id)


@router.delete("/tasks/pending/{conv_id}")
async def delete_task_endpoint(conv_id: str):
    return delete_task(conv_id)