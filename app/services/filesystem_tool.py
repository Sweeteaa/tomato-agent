from pathlib import Path


SCAN_IGNORE_DIRS = {
    ".git",
    ".idea",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "coverage",
    ".tox",
    "venv",
    ".venv",
    ".DS_Store",
    ".Trash",
    ".fseventsd",
    ".Spotlight-V100",
    ".apdisk",
    ".AppleDouble",
}

SCAN_ALLOWED_EXTENSIONS = {
    ".vue",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".txt",
    ".html",
    ".css",
    ".scss",
    ".less",
    ".py",
    ".yaml",
    ".yml",
}


def _normalize_path(path_str: str) -> Path:
    return Path(path_str).expanduser().resolve()


def _is_ignored(path: Path) -> bool:
    for part in path.parts:
        if part in SCAN_IGNORE_DIRS:
            return True
    return False


def scan_directory(root_path: str, depth: int = 3, include_files: bool = True) -> dict:
    root = _normalize_path(root_path)
    if not root.exists():
        raise ValueError(f"路径不存在: {root_path}")
    if not root.is_dir():
        raise ValueError(f"不是目录: {root_path}")

    result = {
        "root": str(root),
        "name": root.name,
        "type": "directory",
        "children": [],
        "files": [],
        "directories": [],
    }

    def walk(path: Path, current_depth: int):
        if current_depth > depth:
            return

        try:
            items = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return

        for item in items:
            if _is_ignored(item):
                continue

            if item.is_dir():
                dir_info = {
                    "name": item.name,
                    "type": "directory",
                    "path": str(item),
                    "children": [],
                    "files": [],
                }
                result["directories"].append(str(item.relative_to(root)))
                if current_depth < depth:
                    sub_result = walk(item, current_depth + 1)
                    if sub_result:
                        dir_info["children"] = sub_result["children"]
                        dir_info["files"] = sub_result["files"]
                result["children"].append(dir_info)
            elif include_files and item.suffix.lower() in SCAN_ALLOWED_EXTENSIONS:
                file_info = {
                    "name": item.name,
                    "type": "file",
                    "path": str(item),
                    "relative_path": str(item.relative_to(root)),
                    "extension": item.suffix.lower(),
                    "size": item.stat().st_size if item.exists() else 0,
                }
                result["files"].append(file_info)

    walk(root, 0)

    return result


def scan_vue_pages(project_path: str) -> list[dict]:
    root = _normalize_path(project_path)
    if not root.exists():
        raise ValueError(f"项目路径不存在: {project_path}")

    pages = []
    patterns = ["**/*.vue", "**/*.ts", "**/*.js"]

    for pattern in patterns:
        for file in sorted(root.rglob(pattern)):
            if _is_ignored(file):
                continue
            if file.suffix.lower() not in {".vue", ".ts", ".js"}:
                continue

            pages.append({
                "file": str(file),
                "relative_path": str(file.relative_to(root)),
                "name": file.stem,
                "extension": file.suffix.lower(),
                "size": file.stat().st_size if file.exists() else 0,
            })

    return sorted(pages, key=lambda x: x["relative_path"])


def read_file(file_path: str, max_size: int = 1024 * 1024) -> str:
    path = _normalize_path(file_path)
    if not path.exists():
        raise ValueError(f"文件不存在: {file_path}")
    if not path.is_file():
        raise ValueError(f"不是文件: {file_path}")

    file_size = path.stat().st_size
    if file_size > max_size:
        raise ValueError(f"文件过大（{file_size} bytes），最大支持 {max_size} bytes")

    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def search_file(keyword: str, root_path: str, max_results: int = 20) -> list[dict]:
    root = _normalize_path(root_path)
    if not root.exists():
        raise ValueError(f"路径不存在: {root_path}")

    results = []
    keyword_lower = keyword.lower()

    for file in root.rglob("*"):
        if _is_ignored(file):
            continue
        if not file.is_file():
            continue
        if file.suffix.lower() not in SCAN_ALLOWED_EXTENSIONS:
            continue

        try:
            content = file.read_text(encoding="utf-8", errors="ignore")
            if keyword_lower in content.lower():
                results.append({
                    "file": str(file),
                    "relative_path": str(file.relative_to(root)),
                    "name": file.name,
                })
                if len(results) >= max_results:
                    return results
        except (PermissionError, OSError):
            continue

    return results


def list_dir(path: str, recursive: bool = False, max_depth: int = 5) -> dict:
    root = _normalize_path(path)
    if not root.exists():
        return {"error": f"路径不存在: {path}"}
    if not root.is_dir():
        return {"error": f"不是目录: {path}"}

    result = {
        "path": str(root),
        "name": root.name,
        "type": "directory",
        "items": [],
    }

    def collect(path: Path, current_depth: int):
        if current_depth > max_depth:
            return

        try:
            items = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return

        for item in items:
            if _is_ignored(item):
                continue

            info = {
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "path": str(item),
            }

            if item.is_file():
                info["extension"] = item.suffix.lower()
                info["size"] = item.stat().st_size if item.exists() else 0
                info["relative_path"] = str(item.relative_to(root))

            if item.is_dir():
                info["relative_path"] = str(item.relative_to(root))
                if recursive and current_depth < max_depth:
                    sub_items = []

                    def collect_sub(sub_path: Path, sub_depth: int):
                        if sub_depth > max_depth:
                            return

                        try:
                            sub_dir_items = sorted(sub_path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
                        except PermissionError:
                            return

                        for sub_item in sub_dir_items:
                            if _is_ignored(sub_item):
                                continue

                            sub_info = {
                                "name": sub_item.name,
                                "type": "directory" if sub_item.is_dir() else "file",
                                "path": str(sub_item),
                            }
                            if sub_item.is_file():
                                sub_info["extension"] = sub_item.suffix.lower()
                                sub_info["size"] = sub_item.stat().st_size if sub_item.exists() else 0
                            sub_items.append(sub_info)
                            if sub_item.is_dir() and sub_depth < max_depth:
                                collect_sub(sub_item, sub_depth + 1)

                    collect_sub(item, current_depth + 1)
                    info["children"] = sub_items

            result["items"].append(info)

    collect(root, 0)

    return result


def scan_menu_structure(project_path: str) -> dict:
    root = _normalize_path(project_path)
    if not root.exists():
        raise ValueError(f"项目路径不存在: {project_path}")

    menu_files = []
    menu_keywords = ["menu", "sidebar", "nav", "navigation", "routes", "router"]
    
    for file in root.rglob("*.vue"):
        if _is_ignored(file):
            continue
        filename_lower = file.name.lower()
        if any(kw in filename_lower for kw in menu_keywords):
            menu_files.append(file)
    
    for file in root.rglob("*.ts"):
        if _is_ignored(file):
            continue
        filename_lower = file.name.lower()
        if any(kw in filename_lower for kw in menu_keywords):
            menu_files.append(file)
    
    for file in root.rglob("*.js"):
        if _is_ignored(file):
            continue
        filename_lower = file.name.lower()
        if any(kw in filename_lower for kw in menu_keywords):
            menu_files.append(file)

    menu_info = {
        "menu_files": [],
        "extracted_routes": [],
        "route_file_paths": [],
        "menu_component_paths": [],
    }

    for file in sorted(menu_files):
        rel_path = str(file.relative_to(root)).replace("\\", "/")
        is_menu_comp = "menu" in rel_path.lower() or "sidebar" in rel_path.lower() or "nav" in rel_path.lower()
        
        try:
            content = file.read_text(encoding="utf-8", errors="ignore")
        except (PermissionError, OSError):
            continue

        routes = extract_routes_from_content(content)
        
        entry = {
            "file": str(file),
            "relative_path": rel_path,
            "type": "menu_component" if is_menu_comp else "route_config",
            "extracted_routes": routes,
        }
        
        if is_menu_comp:
            menu_info["menu_component_paths"].append(rel_path)
        else:
            menu_info["route_file_paths"].append(rel_path)
        
        menu_info["menu_files"].append(entry)
        menu_info["extracted_routes"].extend(routes)

    menu_info["extracted_routes"] = sorted(set(menu_info["extracted_routes"]))
    
    return menu_info


def extract_routes_from_content(content: str) -> list[str]:
    import re
    
    routes = []
    
    url_patterns = [
        r"(?<![a-zA-Z])url\s*[=:]\s*['\"]([^'\"]+)['\"]",
        r"(?<![a-zA-Z])path\s*[=:]\s*['\"]([^'\"]+)['\"]",
        r"(?<![a-zA-Z])component\s*[=:]\s*['\"]([^'\"]+)['\"]",
        r"import\s+.*from\s+['\"]([^'\"]+)['\"]",
        r"(?<![a-zA-Z])href\s*[=:]\s*['\"]([^'\"]+)['\"]",
        r"(?<![a-zA-Z])router-link[^>]*to\s*=\s*['\"]([^'\"]+)['\"]",
    ]
    
    for pattern in url_patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            if match.startswith("/"):
                routes.append(match)
            elif match.startswith("@/"):
                routes.append(match)
            elif match.startswith("./") or match.startswith("../"):
                routes.append(match)
            elif match.endswith(".vue"):
                routes.append(match)
    
    special_patterns = [
        r"import\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"resolve\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"require\(\s*['\"]([^'\"]+)['\"]\s*\)",
    ]
    
    for pattern in special_patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            routes.append(match)
    
    return sorted(set(routes))