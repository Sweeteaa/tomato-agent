from fastapi import APIRouter, HTTPException
from app.services.memory_service import list_memory, get_memory, save_memory, get_user_profile, update_profile

router = APIRouter(prefix="/api", tags=["memory"])


@router.get("/memory")
async def list_memory_endpoint():
    return list_memory()


@router.get("/memory/user_profile")
async def get_user_profile_endpoint():
    return get_user_profile()


@router.post("/memory/user_profile")
async def update_profile_endpoint(data: dict):
    return update_profile(data)


@router.get("/memory/{name}")
async def get_memory_endpoint(name: str):
    result = get_memory(name)
    if result is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return result


@router.post("/memory/{name}")
async def save_memory_endpoint(name: str, data: dict):
    return save_memory(name, data.get("content", ""))