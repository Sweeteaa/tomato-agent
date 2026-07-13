from fastapi import APIRouter, HTTPException

from app.models.project_registry import (
    ProjectRegistryCreate,
    ProjectRegistryImportRequest,
    ProjectRegistryUpdate,
)
from app.services.project_registry_service import (
    create_registered_project,
    get_registered_project,
    import_projects_from_root,
    list_registered_projects,
    update_registered_project,
)
from app.services.project_scanner_service import scan_registered_project

router = APIRouter(prefix="/api", tags=["project-registry"])


@router.get("/project-registry")
async def list_project_registry_endpoint():
    return list_registered_projects()


@router.post("/project-registry/import")
async def import_project_registry_endpoint(data: ProjectRegistryImportRequest):
    try:
        return import_projects_from_root(data.root_path, data.overwrite_existing)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/project-registry/{name}")
async def get_project_registry_endpoint(name: str):
    result = get_registered_project(name)
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


@router.post("/project-registry")
async def create_project_registry_endpoint(data: ProjectRegistryCreate):
    try:
        return create_registered_project(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/project-registry/{name}")
async def update_project_registry_endpoint(name: str, data: ProjectRegistryUpdate):
    try:
        result = update_registered_project(name, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


@router.post("/project-registry/{name}/scan")
async def scan_project_registry_endpoint(name: str):
    full = False
    try:
        return scan_registered_project(name, full_scan=full)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "不存在" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail)



@router.post("/project-registry/scan-all")
async def scan_all_project_registry_endpoint():
    results = {}
    projects = list_registered_projects()
    for p in projects:
        name = p.get("name")
        try:
            results[name] = {"status": "scanning"}
            structure = scan_registered_project(name, full_scan=True)
            results[name] = {"status": "scanned", "scanned_at": structure.get("scanned_at")}
        except Exception as exc:
            results[name] = {"status": "failed", "error": str(exc)}
    return results
