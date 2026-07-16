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


@router.get("/select-folder")
async def select_folder_endpoint():
    import tkinter as tk
    from tkinter import filedialog
    
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    
    folder = filedialog.askdirectory(title="选择项目目录")
    
    return {"path": folder}
