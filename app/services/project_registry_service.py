import json
from datetime import datetime
from pathlib import Path

from app.config import ALLOWED_PROJECT_ROOTS, PROJECTS_ROOT, WORKSPACE
from app.models.project_registry import ProjectRegistryCreate, ProjectRegistryItem, ProjectRegistryUpdate


REGISTRY_DIR = WORKSPACE / "project_registry"
REGISTRY_FILE = REGISTRY_DIR / "registry.json"


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_path(path_str: str) -> Path:
    return Path(path_str).expanduser().resolve()


def _is_allowed_path(path: Path) -> bool:
    normalized = path.resolve()
    for allowed_root in ALLOWED_PROJECT_ROOTS:
        try:
            normalized.relative_to(allowed_root.resolve())
            return True
        except ValueError:
            continue
    return False


def _ensure_registry_file():
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    if not REGISTRY_FILE.exists():
        REGISTRY_FILE.write_text(
            json.dumps({"projects": [], "updated_at": _now_str()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _read_registry() -> dict:
    _ensure_registry_file()
    try:
        return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"projects": [], "updated_at": _now_str()}


def _write_registry(projects: list[dict]):
    _ensure_registry_file()
    payload = {"projects": projects, "updated_at": _now_str()}
    REGISTRY_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_item(data: dict) -> ProjectRegistryItem:
    item = ProjectRegistryItem(**data)
    return item.model_copy(update={"root_path": str(_normalize_path(item.root_path))})


def _load_items() -> list[ProjectRegistryItem]:
    registry = _read_registry()
    items = []
    for project in registry.get("projects", []):
        try:
            items.append(_normalize_item(project))
        except Exception:
            continue
    return items


def _save_items(items: list[ProjectRegistryItem]):
    serialized = [item.model_dump() for item in sorted(items, key=lambda x: x.name.lower())]
    _write_registry(serialized)


def _package_json(project_dir: Path) -> dict:
    package_file = project_dir / "package.json"
    if not package_file.exists():
        return {}
    try:
        return json.loads(package_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _detect_package_manager(project_dir: Path) -> str:
    if (project_dir / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (project_dir / "yarn.lock").exists():
        return "yarn"
    if (project_dir / "package-lock.json").exists():
        return "npm"
    return "unknown"


def _detect_framework(package_data: dict) -> str:
    deps = {**package_data.get("dependencies", {}), **package_data.get("devDependencies", {})}
    if "vue" in deps:
        version = str(deps.get("vue", "")).lower()
        if version.startswith("^2") or version.startswith("~2") or version.startswith("2"):
            return "vue2"
        return "vue3"
    if "react" in deps:
        return "react"
    if "next" in deps:
        return "nextjs"
    if "nuxt" in deps:
        return "nuxt"
    return "unknown"


def _detect_build_tool(project_dir: Path, package_data: dict) -> str:
    deps = {**package_data.get("dependencies", {}), **package_data.get("devDependencies", {})}
    if (project_dir / "vite.config.ts").exists() or (project_dir / "vite.config.js").exists() or "vite" in deps:
        return "vite"
    if (project_dir / "webpack.config.js").exists() or "webpack" in deps:
        return "webpack"
    if (project_dir / ".umirc.ts").exists() or (project_dir / ".umirc.js").exists() or "umi" in deps:
        return "umi"
    if "rsbuild" in deps or (project_dir / "rsbuild.config.ts").exists():
        return "rsbuild"
    return "unknown"


def _detect_store_type(package_data: dict) -> str:
    deps = {**package_data.get("dependencies", {}), **package_data.get("devDependencies", {})}
    if "pinia" in deps:
        return "pinia"
    if "vuex" in deps:
        return "vuex"
    if "redux" in deps or "@reduxjs/toolkit" in deps:
        return "redux"
    if "zustand" in deps:
        return "zustand"
    return "unknown"


def _guess_dev_command(package_data: dict, package_manager: str) -> str:
    scripts = package_data.get("scripts", {})
    if "dev" in scripts:
        if package_manager == "pnpm":
            return "pnpm dev"
        if package_manager == "yarn":
            return "yarn dev"
        return "npm run dev"
    if "start" in scripts:
        if package_manager == "pnpm":
            return "pnpm start"
        if package_manager == "yarn":
            return "yarn start"
        return "npm start"
    return ""


SCAN_IGNORE_DIRS = {
    ".git",
    ".idea",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".DS_Store",
    ".Trash",
    ".fseventsd",
    ".Spotlight-V100",
    ".apdisk",
    ".AppleDouble",
}


def _is_ignored(path: Path) -> bool:
    for part in path.parts:
        if part in SCAN_IGNORE_DIRS:
            return True
    return False


def _scan_vue_files(project_dir: Path) -> dict:
    pages = []
    components = []
    router_files = []
    api_files = []
    state_files = []

    vue_patterns = ["**/*.vue", "**/*.ts", "**/*.js"]

    for pattern in vue_patterns:
        for file in sorted(project_dir.rglob(pattern)):
            if _is_ignored(file):
                continue
            if not file.is_file():
                continue

            rel_path = str(file.relative_to(project_dir)).replace("\\", "/")

            if file.suffix.lower() == ".vue":
                if "page" in rel_path.lower() or "view" in rel_path.lower():
                    pages.append(rel_path)
                else:
                    components.append(rel_path)
            elif rel_path.startswith("src/router") or rel_path.startswith("src/routes"):
                router_files.append(rel_path)
            elif rel_path.startswith("src/api") or rel_path.startswith("src/services"):
                api_files.append(rel_path)
            elif rel_path.startswith("src/store") or rel_path.startswith("src/stores"):
                state_files.append(rel_path)

    return {
        "pages": sorted(set(pages)),
        "components": sorted(set(components)),
        "router_files": sorted(set(router_files)),
        "api_files": sorted(set(api_files)),
        "state_files": sorted(set(state_files)),
    }


def _collect_existing_dirs(project_dir: Path, candidates: list[str]) -> list[str]:
    existing = []
    for candidate in candidates:
        if (project_dir / candidate).exists():
            existing.append(candidate.replace("\\", "/"))
    return existing


def _build_candidate_item(project_dir: Path) -> ProjectRegistryItem:
    package_data = _package_json(project_dir)
    package_manager = _detect_package_manager(project_dir)
    now = _now_str()

    file_scan = _scan_vue_files(project_dir)

    page_dirs = set()
    for page in file_scan["pages"]:
        page_dirs.add(page.rsplit("/", 1)[0] if "/" in page else "")
    page_dirs = sorted([d for d in page_dirs if d])

    component_dirs = set()
    for comp in file_scan["components"]:
        component_dirs.add(comp.rsplit("/", 1)[0] if "/" in comp else "")
    component_dirs = sorted([d for d in component_dirs if d])

    return ProjectRegistryItem(
        name=project_dir.name,
        root_path=str(project_dir),
        enabled=True,
        framework=_detect_framework(package_data),
        build_tool=_detect_build_tool(project_dir, package_data),
        package_manager=package_manager,
        dev_command=_guess_dev_command(package_data, package_manager),
        src_dir="src" if (project_dir / "src").exists() else "",
        router_file_candidates=file_scan["router_files"] if file_scan["router_files"] else _collect_existing_dirs(
            project_dir,
            ["src/router/index.ts", "src/router/index.js", "src/routes.ts", "src/routes.js"],
        ),
        api_dir_candidates=list(set(f.rsplit("/", 1)[0] for f in file_scan["api_files"] if "/" in f))[:10] if file_scan["api_files"] else _collect_existing_dirs(project_dir, ["src/api", "src/services"]),
        store_type=_detect_store_type(package_data),
        component_dirs=component_dirs if component_dirs else _collect_existing_dirs(project_dir, ["src/components", "src/common/components"]),
        page_dirs=page_dirs if page_dirs else _collect_existing_dirs(project_dir, ["src/views", "src/pages"]),
        module_summary=f"扫描到 {len(file_scan['pages'])} 个页面文件、{len(file_scan['components'])} 个组件文件",
        last_scan_at=now,
        scan_status="scanned",
        created_at=now,
        updated_at=now,
    )


def _looks_like_frontend_project(project_dir: Path) -> bool:
    package_data = _package_json(project_dir)
    if not package_data:
        return False
    deps = {**package_data.get("dependencies", {}), **package_data.get("devDependencies", {})}
    frontend_markers = {
        "vue",
        "react",
        "vite",
        "webpack",
        "umi",
        "next",
        "nuxt",
        "@vue/cli-service",
    }
    return bool(frontend_markers.intersection(deps.keys())) or (project_dir / "src").exists()


def list_registered_projects() -> list[dict]:
    return [item.model_dump() for item in _load_items()]


def get_registered_project(name: str) -> dict | None:
    for item in _load_items():
        if item.name == name:
            return item.model_dump()
    return None


def get_registered_project_item(name: str) -> ProjectRegistryItem | None:
    for item in _load_items():
        if item.name == name:
            return item
    return None


def create_registered_project(data: ProjectRegistryCreate) -> dict:
    root_path = _normalize_path(data.root_path)
    if not root_path.exists():
        raise ValueError(f"项目路径不存在: {root_path}")
    if not _is_allowed_path(root_path):
        raise ValueError(f"项目路径不在允许范围内: {root_path}")

    items = _load_items()
    if any(item.name == data.name for item in items):
        raise ValueError(f"项目已存在: {data.name}")

    now = _now_str()
    item = ProjectRegistryItem(
        **data.model_dump(),
        root_path=str(root_path),
        created_at=now,
        updated_at=now,
    )
    items.append(item)
    _save_items(items)
    return item.model_dump()


def update_registered_project(name: str, data: ProjectRegistryUpdate) -> dict | None:
    items = _load_items()
    for index, item in enumerate(items):
        if item.name != name:
            continue

        update_data = data.model_dump(exclude_none=True)
        if "root_path" in update_data:
            root_path = _normalize_path(update_data["root_path"])
            if not root_path.exists():
                raise ValueError(f"项目路径不存在: {root_path}")
            if not _is_allowed_path(root_path):
                raise ValueError(f"项目路径不在允许范围内: {root_path}")
            update_data["root_path"] = str(root_path)

        update_data["updated_at"] = _now_str()
        updated_item = item.model_copy(update=update_data)
        items[index] = updated_item
        _save_items(items)
        return updated_item.model_dump()
    return None


def import_projects_from_root(root_path: str | None = None, overwrite_existing: bool = False) -> dict:
    base_dir = _normalize_path(root_path) if root_path else PROJECTS_ROOT.resolve()
    if not base_dir.exists():
        raise ValueError(f"项目根目录不存在: {base_dir}")
    if not _is_allowed_path(base_dir):
        raise ValueError(f"项目根目录不在允许范围内: {base_dir}")

    items = _load_items()
    existing_map = {item.name: item for item in items}
    imported_items = []
    skipped = 0

    for child in sorted(base_dir.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or not _looks_like_frontend_project(child):
            continue

        candidate = _build_candidate_item(child)
        if candidate.name in existing_map and not overwrite_existing:
            skipped += 1
            imported_items.append(existing_map[candidate.name])
            continue

        if candidate.name in existing_map and overwrite_existing:
            preserved_created_at = existing_map[candidate.name].created_at
            candidate = candidate.model_copy(update={"created_at": preserved_created_at, "updated_at": _now_str()})
            items = [item for item in items if item.name != candidate.name]

        items.append(candidate)
        imported_items.append(candidate)

    _save_items(items)
    return {
        "imported": len(imported_items) - skipped,
        "skipped": skipped,
        "projects": [item.model_dump() for item in imported_items],
        "root_path": str(base_dir),
    }
