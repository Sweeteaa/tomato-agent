from fastapi import APIRouter
from app.services.workspace_service import get_workspace

router = APIRouter(prefix="/api", tags=["workspace"])


@router.get("/workspace")
async def get_workspace_endpoint():
    return get_workspace()