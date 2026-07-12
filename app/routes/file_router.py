from fastapi import APIRouter, UploadFile, File
from app.services.file_service import upload_file, search_workspace

router = APIRouter(prefix="/api", tags=["files"])


@router.post("/upload")
async def upload_file_endpoint(file: UploadFile = File(...)):
    content = await file.read()
    return upload_file(content, file.filename)


@router.get("/search")
async def search_workspace_endpoint(q: str):
    return search_workspace(q)