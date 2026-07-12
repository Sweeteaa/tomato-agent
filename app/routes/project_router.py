from fastapi import APIRouter, HTTPException
from app.services.project_service import list_projects, get_project_doc

router = APIRouter(prefix="/api", tags=["projects"])


@router.get("/projects")
async def list_projects_endpoint():
    return list_projects()


@router.get("/projects/{project}/{doc}")
async def get_project_doc_endpoint(project: str, doc: str):
    result = get_project_doc(project, doc)
    if result is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return result