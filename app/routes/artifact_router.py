from fastapi import APIRouter, HTTPException
from app.services.artifact_service import list_artifacts, read_artifact

router = APIRouter(prefix="/api", tags=["artifacts"]) 


@router.get("/artifacts/{task_id}")
async def list_artifacts_endpoint(task_id: str):
    return list_artifacts(task_id)


@router.get("/artifacts/{task_id}/{name}")
async def get_artifact_endpoint(task_id: str, name: str):
    try:
        return {"name": name, "content": read_artifact(task_id, name)}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Artifact not found")
