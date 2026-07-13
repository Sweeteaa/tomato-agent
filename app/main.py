from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path
from app.routes.workspace_router import router as workspace_router
from app.routes.conversation_router import router as conversation_router
from app.routes.memory_router import router as memory_router
from app.routes.project_router import router as project_router
from app.routes.project_registry_router import router as project_registry_router
from app.routes.task_router import router as task_router
from app.routes.file_router import router as file_router
from app.routes.chat_router import router as chat_router
from app.routes.artifact_router import router as artifact_router
from app.config import WORKSPACE

app = FastAPI(title="GT Agent", version="1.0.0")

WORKSPACE.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory="."), name="static")

app.include_router(workspace_router)
app.include_router(conversation_router)
app.include_router(memory_router)
app.include_router(project_router)
app.include_router(project_registry_router)
app.include_router(task_router)
app.include_router(file_router)
app.include_router(chat_router)
app.include_router(artifact_router)


@app.get("/", response_class=HTMLResponse)
async def root():
    index_path = Path("index.html")
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Welcome to GT Agent</h1>")


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "message": "GT Agent is running"}
