from fastapi import APIRouter, HTTPException
from app.services.task_service import list_tasks, get_task, get_pending_tasks, save_pending_task, complete_task, delete_task
from app.services.requirement_parser_service import parse_requirement_from_text
from app.services.project_matcher_service import match_projects
from app.services.document_generator_service import generate_documents


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




@router.post("/tasks/requirement-analysis")
async def requirement_analysis_endpoint(data: dict):
    # data: {"task_id": "...", "text": "...", "target_project": null}
    task_id = data.get("task_id")
    text = data.get("text", "")
    if not task_id or not text:
        raise HTTPException(status_code=400, detail="task_id and text are required")

    req = parse_requirement_from_text(task_id, text)
    matches = match_projects(req)

    selected = data.get("target_project")
    docs = None
    if selected:
        docs = generate_documents(task_id, req, selected)

    return {"task_id": task_id, "requirement": req, "matches": matches, "generated": docs}