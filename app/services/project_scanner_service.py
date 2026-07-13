import json
import re
from datetime import datetime
from pathlib import Path

from app.config import SCAN_IGNORE_DIRS, WORKSPACE
from app.models.project_registry import ProjectRegistryUpdate
from app.services.project_registry_service import (
    get_registered_project_item,
    update_registered_project,
)


PROJECTS_DOCS_DIR = WORKSPACE / "projects"
PROJECT_CACHE_DIR = WORKSPACE / "project_registry" / "cache"
MAX_ITEMS_PER_SECTION = 200

ROUTE_FILE_CANDIDATES = [
    "src/router/index.ts",
    "src/router/index.js",
    "src/router/modules",
    "src/routes.ts",
    "src/routes.js",
]
PAGE_DIR_CANDIDATES = ["src/views", "src/pages", "src/view", "src/page"]
COMPONENT_DIR_CANDIDATES = ["src/components", "src/common/components", "src/component"]
API_DIR_CANDIDATES = ["src/api", "src/services"]
STATE_DIR_CANDIDATES = ["src/store", "src/stores"]
CONFIG_FILE_CANDIDATES = [
    "vite.config.ts",
    "vite.config.js",
    "webpack.config.js",
    "vue.config.js",
    ".umirc.ts",
    ".umirc.js",
    "rsbuild.config.ts",
]


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _list_files(base_dir: Path, extensions: tuple[str, ...], root: Path, max_items: int = MAX_ITEMS_PER_SECTION) -> list[str]:
    if not base_dir.exists() or not base_dir.is_dir():
        return []

    results = []
    for child in base_dir.rglob("*"):
        if any(part in SCAN_IGNORE_DIRS for part in child.parts):
            continue
        if child.is_file() and child.suffix.lower() in extensions:
            results.append(_to_rel(child, root))
        if len(results) >= max_items:
            break
    return sorted(results)


def _read_text_if_exists(root: Path, rel_path: str) -> str:
    path = root / rel_path
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def _read_package_json(project_root: Path) -> dict:
    package_json = project_root / "package.json"
    if not package_json.exists():
        return {}
    try:
        return json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _extract_routes_from_content(content: str) -> list[dict]:
    routes = []
    path_matches = re.findall(r"path\s*:\s*['\"]([^'\"]+)['\"]", content)
    name_matches = re.findall(r"name\s*:\s*['\"]([^'\"]+)['\"]", content)
    component_matches = re.findall(r"component\s*:\s*([A-Za-z0-9_./() =>]+)", content)

    max_len = min(max(len(path_matches), len(name_matches), len(component_matches)), 50)
    for index in range(max_len):
        path = path_matches[index] if index < len(path_matches) else ""
        name = name_matches[index] if index < len(name_matches) else ""
        component = component_matches[index] if index < len(component_matches) else ""
        if path or name or component:
            routes.append({"path": path, "name": name, "component": component.strip()})
    return routes


def _extract_api_symbols(content: str) -> list[str]:
    patterns = [
        r"export\s+function\s+([A-Za-z0-9_]+)",
        r"export\s+async\s+function\s+([A-Za-z0-9_]+)",
        r"export\s+const\s+([A-Za-z0-9_]+)\s*=",
        r"function\s+([A-Za-z0-9_]+)\s*\(",
    ]
    symbols = []
    for pattern in patterns:
        symbols.extend(re.findall(pattern, content))
    ordered = []
    for symbol in symbols:
        if symbol not in ordered:
            ordered.append(symbol)
    return ordered[:30]


def _detect_ui_libraries(package_data: dict) -> list[str]:
    deps = {**package_data.get("dependencies", {}), **package_data.get("devDependencies", {})}
    known = [
        "element-plus",
        "element-ui",
        "antd",
        "ant-design-vue",
        "vant",
        "naive-ui",
        "iview",
        "view-design",
        "uview-ui",
    ]
    return [name for name in known if name in deps]


def _find_existing_paths(project_root: Path, candidates: list[str]) -> list[str]:
    found = []
    for candidate in candidates:
        path = project_root / candidate
        if path.exists():
            found.append(candidate.replace("\\", "/"))
    return found


def _find_dirs_by_basename(project_root: Path, basenames: list[str]) -> list[str]:
    found = []
    src = project_root / "src"
    if not src.exists() or not src.is_dir():
        return []
    for d in src.rglob("*"):
        if d.is_dir() and d.name.lower() in set(b.lower() for b in basenames):
            try:
                rel = _to_rel(d, project_root)
            except Exception:
                rel = str(d)
            found.append(rel.replace("\\", "/"))
    return sorted(set(found))


def _build_scan_structure(project_root: Path, registry_item, max_items_per_section: int = MAX_ITEMS_PER_SECTION) -> dict:
    package_data = _read_package_json(project_root)
    scripts = package_data.get("scripts", {})
    dependencies = package_data.get("dependencies", {})
    dev_dependencies = package_data.get("devDependencies", {})

    route_files = []
    for candidate in ROUTE_FILE_CANDIDATES:
        path = project_root / candidate
        if path.is_file():
            route_files.append(candidate.replace("\\", "/"))
        elif path.is_dir():
            route_files.extend(_list_files(path, (".ts", ".js"), project_root, max_items_per_section))

    route_entries = []
    for route_file in route_files[: max_items_per_section // 10 or 20]:
        content = _read_text_if_exists(project_root, route_file)
        if not content:
            continue
        for entry in _extract_routes_from_content(content):
            route_entries.append({"file": route_file, **entry})
        if len(route_entries) >= 100:
            break

    page_files = []
    # include configured candidates and any discovered dirs named view(s)/page(s)
    page_dir_candidates = list(PAGE_DIR_CANDIDATES)
    discovered_page_dirs = _find_dirs_by_basename(project_root, ["views", "view", "pages", "page"])
    for d in discovered_page_dirs:
        if d not in page_dir_candidates:
            page_dir_candidates.append(d)
    for candidate in page_dir_candidates:
        page_files.extend(_list_files(project_root / candidate, (".vue", ".tsx", ".jsx"), project_root, max_items_per_section))

    component_files = []
    component_dir_candidates = list(COMPONENT_DIR_CANDIDATES)
    discovered_component_dirs = _find_dirs_by_basename(project_root, ["components", "component", "common", "shared"])
    for d in discovered_component_dirs:
        if d not in component_dir_candidates:
            component_dir_candidates.append(d)
    for candidate in component_dir_candidates:
        component_files.extend(_list_files(project_root / candidate, (".vue", ".tsx", ".jsx"), project_root, max_items_per_section))

    api_modules = []
    api_files = []
    for candidate in API_DIR_CANDIDATES:
        api_files.extend(_list_files(project_root / candidate, (".ts", ".js"), project_root, max_items_per_section))

    for api_file in api_files[: max_items_per_section // 4 or 50]:
        content = _read_text_if_exists(project_root, api_file)
        api_modules.append(
            {
                "path": api_file,
                "symbols": _extract_api_symbols(content),
            }
        )

    state_files = []
    for candidate in STATE_DIR_CANDIDATES:
        state_files.extend(_list_files(project_root / candidate, (".ts", ".js"), project_root, max_items_per_section))

    config_files = [candidate for candidate in CONFIG_FILE_CANDIDATES if (project_root / candidate).exists()]

    # discovered dirs to include in reported page/component dirs
    page_dirs_report = sorted(set(_find_existing_paths(project_root, PAGE_DIR_CANDIDATES) + discovered_page_dirs))
    component_dirs_report = sorted(set(_find_existing_paths(project_root, COMPONENT_DIR_CANDIDATES) + discovered_component_dirs))

    return {
        "project": registry_item.name,
        "root_path": str(project_root),
        "framework": registry_item.framework,
        "build_tool": registry_item.build_tool,
        "package_manager": registry_item.package_manager,
        "dev_command": registry_item.dev_command,
        "src_dir": registry_item.src_dir,
        "scripts": scripts,
        "dependencies_count": len(dependencies),
        "dev_dependencies_count": len(dev_dependencies),
        "ui_libraries": _detect_ui_libraries(package_data),
        "router": {
            "files": sorted(set(route_files)),
            "routes": route_entries[:100],
        },
        "pages": sorted(set(page_files))[:max_items_per_section],
        "components": sorted(set(component_files))[:max_items_per_section],
        "api_modules": api_modules,
        "api_dirs": _find_existing_paths(project_root, API_DIR_CANDIDATES),
        "state": {
            "type": registry_item.store_type,
            "files": sorted(set(state_files))[:max_items_per_section],
        },
        "component_dirs": component_dirs_report,
        "page_dirs": page_dirs_report,
        "config_files": config_files,
        "scanned_at": _now_str(),
    }


def _write_project_files(project_name: str, structure: dict):
    project_dir = PROJECTS_DOCS_DIR / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    PROJECT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    structure_path = project_dir / "structure.json"
    cache_path = PROJECT_CACHE_DIR / f"{project_name}.json"
    structure_json = json.dumps(structure, ensure_ascii=False, indent=2)
    structure_path.write_text(structure_json, encoding="utf-8")
    cache_path.write_text(structure_json, encoding="utf-8")

    overview_lines = [
        f"# {project_name} 项目概览",
        "",
        f"- 项目路径: `{structure['root_path']}`",
        f"- 框架: `{structure['framework']}`",
        f"- 构建工具: `{structure['build_tool']}`",
        f"- 包管理器: `{structure['package_manager']}`",
        f"- 启动命令: `{structure['dev_command'] or '未识别'}`",
        f"- 源码目录: `{structure['src_dir'] or '未识别'}`",
        f"- UI 组件库: `{', '.join(structure['ui_libraries']) if structure['ui_libraries'] else '未识别'}`",
        f"- 状态管理: `{structure['state']['type']}`",
        f"- 扫描时间: `{structure['scanned_at']}`",
        "",
        "## 关键目录",
        "",
        f"- 页面目录: {', '.join(f'`{item}`' for item in structure['page_dirs']) if structure['page_dirs'] else '未识别'}",
        f"- 组件目录: {', '.join(f'`{item}`' for item in structure['component_dirs']) if structure['component_dirs'] else '未识别'}",
        f"- API 目录: {', '.join(f'`{item}`' for item in structure['api_dirs']) if structure['api_dirs'] else '未识别'}",
        f"- 配置文件: {', '.join(f'`{item}`' for item in structure['config_files']) if structure['config_files'] else '未识别'}",
    ]

    route_lines = [f"# {project_name} 路由信息", ""]
    if structure["router"]["files"]:
        route_lines.extend(["## 路由文件", ""])
        route_lines.extend(f"- `{item}`" for item in structure["router"]["files"])
        route_lines.append("")
    if structure["router"]["routes"]:
        route_lines.extend(["## 路由条目", ""])
        for route in structure["router"]["routes"]:
            desc = route["path"] or "未识别 path"
            extra = []
            if route.get("name"):
                extra.append(f"name={route['name']}")
            if route.get("component"):
                extra.append(f"component={route['component']}")
            extra.append(f"file={route['file']}")
            route_lines.append(f"- `{desc}` ({', '.join(extra)})")
    else:
        route_lines.append("- 未识别到明确路由条目")

    api_lines = [f"# {project_name} API 信息", ""]
    if structure["api_modules"]:
        for module in structure["api_modules"]:
            api_lines.append(f"## `{module['path']}`")
            api_lines.append("")
            if module["symbols"]:
                api_lines.extend(f"- `{symbol}`" for symbol in module["symbols"])
            else:
                api_lines.append("- 未识别导出方法")
            api_lines.append("")
    else:
        api_lines.append("- 未识别到 API 模块")

    component_lines = [f"# {project_name} 组件信息", ""]
    if structure["components"]:
        component_lines.extend(f"- `{item}`" for item in structure["components"])
    else:
        component_lines.append("- 未识别到公共组件文件")
    component_lines.extend(["", "## 页面文件", ""])
    if structure["pages"]:
        component_lines.extend(f"- `{item}`" for item in structure["pages"])
    else:
        component_lines.append("- 未识别到页面文件")

    (project_dir / "overview.md").write_text("\n".join(overview_lines) + "\n", encoding="utf-8")
    (project_dir / "routes.md").write_text("\n".join(route_lines) + "\n", encoding="utf-8")
    (project_dir / "api.md").write_text("\n".join(api_lines) + "\n", encoding="utf-8")
    (project_dir / "components.md").write_text("\n".join(component_lines) + "\n", encoding="utf-8")


def scan_registered_project(name: str, full_scan: bool = False) -> dict:
    item = get_registered_project_item(name)
    if item is None:
        raise ValueError(f"项目不存在: {name}")

    project_root = Path(item.root_path)
    if not project_root.exists():
        raise ValueError(f"项目路径不存在: {project_root}")

    update_registered_project(
        name,
        ProjectRegistryUpdate(scan_status="scanning", last_scan_at=_now_str()),
    )

    try:
        max_items = MAX_ITEMS_PER_SECTION if not full_scan else 10000
        structure = _build_scan_structure(project_root, item, max_items_per_section=max_items)
        _write_project_files(name, structure)

        update_registered_project(
            name,
            ProjectRegistryUpdate(
                scan_status="scanned",
                last_scan_at=structure["scanned_at"],
                router_file_candidates=structure["router"]["files"],
                api_dir_candidates=structure["api_dirs"],
                component_dirs=structure["component_dirs"],
                page_dirs=structure["page_dirs"],
                module_summary=(
                    f"扫描到 {len(structure['pages'])} 个页面文件、"
                    f"{len(structure['components'])} 个组件文件、"
                    f"{len(structure['api_modules'])} 个 API 模块"
                ),
            ),
        )
        return structure
    except Exception:
        update_registered_project(
            name,
            ProjectRegistryUpdate(scan_status="failed", last_scan_at=_now_str()),
        )
        raise
