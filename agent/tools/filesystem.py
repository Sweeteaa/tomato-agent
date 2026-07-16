"""文件系统工具层 — 统一支持绝对路径和 workspace 相对路径

合并了原 agent/tools/filesystem.py 和 app/services/filesystem_tool.py 的功能:
- 绝对路径: 用于扫描用户项目 (D:/projects/xxx)
- 相对路径: 用于 workspace 内操作 (skill/hello.md)
- 新增 scan_menu_structure (原只在 app/tools.py 定义，registry 中不存在)
- 修复路径遍历漏洞: 所有路径 resolve 后检查是否在允许范围内
- 错误处理: 抛出 ToolError 异常而非返回 ❌ 字符串
"""

import os
import json
import re
from pathlib import Path
from app.config import WORKSPACE, SCAN_IGNORE_DIRS, SCAN_ALLOWED_EXTENSIONS
from agent.exceptions import ToolError, FileNotFoundError as FileNotFound, PathSecurityError


# ─── 安全路径解析 ───

def _resolve_path(path_str: str, restrict_to_workspace: bool = False) -> Path:
    """解析路径，支持绝对路径和 workspace 相对路径

    Args:
        path_str: 路径字符串，可为绝对路径或 workspace 相对路径
        restrict_to_workspace: 是否限制在 workspace 内 (写/删/追加操作必须限制)

    Returns:
        解析后的绝对 Path 对象

    Raises:
        PathSecurityError: 路径遍历攻击或安全限制
    """
    if not path_str:
        return WORKSPACE.resolve()

    p = Path(path_str)

    if p.is_absolute():
        resolved = p.resolve()
        if restrict_to_workspace:
            raise PathSecurityError(
                f"安全限制: 写入/删除操作只允许在 workspace 内，"
                f"提供的绝对路径 '{path_str}' 超出范围"
            )
        return resolved
    else:
        # workspace 相对路径
        resolved = (WORKSPACE / path_str).resolve()
        ws_resolved = WORKSPACE.resolve()
        resolved_str = str(resolved).replace("\\", "/").lower()
        ws_str = str(ws_resolved).replace("\\", "/").lower()
        if not resolved_str.startswith(ws_str):
            raise PathSecurityError(f"路径遍历攻击: '{path_str}' 逃出 workspace 范围")
        return resolved


def _is_ignored(path: Path) -> bool:
    """检查路径是否应被忽略（使用 config.py 中统一的 SCAN_IGNORE_DIRS）"""
    for part in path.parts:
        if part in SCAN_IGNORE_DIRS:
            return True
    return False


# ─── 读取类工具（支持绝对路径 + 相对路径）───

def read_file(path: str, max_size: int = 1048576, start_line: int = 0, end_line: int = 0) -> str:
    """读取文件内容

    支持绝对路径（如 D:/projects/xxx/src/App.vue）和 workspace 相对路径。
    读取操作不限制路径范围，但会检查文件大小防止内存溢出。

    分页读取:
    - start_line/end_line 均从 1 开始，0 表示不限制
    - 当文件过大时，可指定行范围分段读取
    - 返回 JSON 格式: {path, total_lines, start_line, end_line, content}

    Raises:
        PathSecurityError: 路径安全限制
        FileNotFound: 文件不存在
        ToolError: 不是文件 / 文件过大 / 无权限
    """
    file_path = _resolve_path(path, restrict_to_workspace=False)

    if not file_path.exists():
        raise FileNotFound(path)
    if not file_path.is_file():
        raise ToolError(f"不是文件: {path}", "read_file")

    file_size = file_path.stat().st_size

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        raise ToolError(f"无权限读取: {path}", "read_file")

    lines = content.splitlines()
    total_lines = len(lines)

    # 分页模式
    if start_line > 0 or end_line > 0:
        s = max(1, start_line) - 1  # 转为 0-based index
        e = end_line if end_line > 0 else total_lines
        e = min(e, total_lines)
        page_lines = lines[s:e]
        page_content = "\n".join(page_lines)

        result = {
            "path": str(file_path),
            "total_lines": total_lines,
            "start_line": s + 1,
            "end_line": e,
            "content": page_content,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    # 全文模式：检查大小
    if file_size > max_size:
        preview_lines = min(200, total_lines)
        result = {
            "path": str(file_path),
            "total_lines": total_lines,
            "start_line": 1,
            "end_line": preview_lines,
            "content": "\n".join(lines[:preview_lines]),
            "truncated": True,
            "message": f"文件过大（{file_size} bytes），已返回前 {preview_lines} 行。使用 start_line/end_line 参数读取更多内容。",
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    result = {
        "path": str(file_path),
        "total_lines": total_lines,
        "content": content,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


def list_dir(path: str = "", recursive: bool = False, max_depth: int = 5) -> str:
    """列出目录内容

    支持绝对路径（如 D:/projects/xxx）和 workspace 相对路径。
    - recursive=False: 简单模式，返回扁平列表
    - recursive=True: 递归模式，返回结构化 JSON

    Raises:
        PathSecurityError: 路径安全限制
        ToolError: 目录不存在 / 不是目录
    """
    dir_path = _resolve_path(path, restrict_to_workspace=False)

    if not dir_path.exists():
        raise ToolError(f"目录不存在: {path}", "list_dir")
    if not dir_path.is_dir():
        raise ToolError(f"不是目录: {path}", "list_dir")

    if recursive:
        result = _scan_directory_recursive(dir_path, max_depth)
        return json.dumps(result, ensure_ascii=False, indent=5)
    else:
        return _list_flat(dir_path)


def _list_flat(dir_path: Path) -> str:
    """简单模式: 列出当前目录内容，返回结构化 JSON"""
    try:
        children = sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
    except PermissionError:
        raise ToolError("无权限访问目录", "list_dir")

    dirs = []
    files = []
    important_files = []
    
    important_extensions = [".json", ".js", ".ts", ".vue", ".html", ".md"]
    
    for child in children:
        if _is_ignored(child):
            continue
        if child.is_dir():
            dirs.append(child.name)
        else:
            files.append({
                "name": child.name,
                "size": child.stat().st_size if child.exists() else 0,
            })
            if any(child.name.endswith(ext) for ext in important_extensions):
                important_files.append(child.name)

    result = {
        "path": str(dir_path),
        "dirs": dirs,
        "files": files,
        "important_files": important_files,
    }

    return json.dumps(result, ensure_ascii=False, indent=2)


def _scan_directory_recursive(root: Path, max_depth: int) -> dict:
    """递归扫描目录，返回嵌套结构化结果"""
    result = {
        "path": str(root),
        "name": root.name,
        "type": "directory",
        "items": _collect_nested(root, 0, max_depth),
    }
    return result


def _collect_nested(path: Path, depth: int, max_depth: int) -> list:
    """递归收集目录内容，返回嵌套列表

    每个目录的 children 是其直接子项的列表，子目录再嵌套。
    """
    if depth >= max_depth:
        return []
    try:
        items = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return []

    result = []
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
            try:
                info["size"] = item.stat().st_size
            except OSError:
                info["size"] = 0
        if item.is_dir():
            info["children"] = _collect_nested(item, depth + 1, max_depth)
        result.append(info)
    return result


def search_file(query: str = "", keyword: str = "", root_path: str = "",
                max_results: int = 20, file_extensions: str = "", context_lines: int = 3) -> str:
    """搜索文件内容，返回匹配行及上下文

    两种模式:
    1. workspace 模式: 只传 query, 在 workspace 内搜索
    2. 项目模式: 传 keyword + root_path, 在指定项目目录内搜索 (推荐用于扫描用户项目)

    项目模式增强:
    - 返回匹配行号和上下文，便于直接定位代码
    - 支持 file_extensions 过滤（如 "vue,js,ts"）
    - 支持逗号分隔的多关键词（OR 逻辑，任一匹配即返回）
    - 自动排除 .md/.json 等生成文档，优先搜索源码文件

    参数类型容错:
    - keyword/file_extensions: list → ",".join(list)
    - 所有字符串参数: None → ""

    Raises:
        ToolError: 缺少必要参数 / 路径不存在 / 不是目录
    """
    # 参数类型容错
    if keyword is None:
        keyword = ""
    if isinstance(keyword, list):
        keyword = ",".join(keyword)
    
    if file_extensions is None:
        file_extensions = ""
    if isinstance(file_extensions, list):
        file_extensions = ",".join(file_extensions)
    
    if root_path is None:
        root_path = ""
    if isinstance(root_path, list):
        root_path = root_path[0] if root_path else ""

    if keyword and root_path:
        # 项目模式 — 增强版，返回匹配行+上下文
        root = Path(root_path).resolve()
        
        if not root.exists():
            # 尝试向上查找最近的存在的目录
            candidates = []
            current = root
            while current.parent != current:
                if current.exists():
                    candidates.append(current)
                current = current.parent
            if candidates:
                root = candidates[0]
            else:
                raise ToolError(f"路径不存在: {root_path}", "search_file")
        
        if not root.is_dir():
            root = root.parent
        
        if not root.exists():
            raise ToolError(f"路径不存在: {root_path}", "search_file")

        # 解析关键词列表（逗号分隔 → OR 逻辑）
        keywords = [k.strip().lower() for k in keyword.split(",") if k.strip()]
        if not keywords:
            raise ToolError("keyword 不能为空", "search_file")

        # 解析文件扩展名过滤
        ext_filter = None
        if file_extensions:
            ext_filter = set()
            for ext in file_extensions.split(","):
                ext = ext.strip().lstrip(".")
                if ext:
                    ext_filter.add(f".{ext.lower()}")
        else:
            # 默认只搜索源码文件，排除 .md/.json/.txt 等非源码
            ext_filter = SCAN_ALLOWED_EXTENSIONS - {".md", ".json", ".txt", ".yaml", ".yml"}

        results = []
        for file_path in root.rglob("*"):
            if _is_ignored(file_path):
                continue
            if not file_path.is_file():
                continue
            if ext_filter and file_path.suffix.lower() not in ext_filter:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except (PermissionError, OSError):
                continue

            lines = content.splitlines()
            matches = []
            for i, line in enumerate(lines):
                line_lower = line.lower()
                for kw in keywords:
                    if kw in line_lower:
                        # 收集上下文
                        start = max(0, i - context_lines)
                        end = min(len(lines), i + context_lines + 1)
                        context = []
                        for j in range(start, end):
                            prefix = ">>>" if j == i else "   "
                            context.append(f"{prefix} L{j+1}: {lines[j]}")
                        matches.append({
                            "line": i + 1,
                            "keyword": kw,
                            "context": "\n".join(context),
                        })
                        break  # 同一行不重复匹配

            if matches:
                results.append({
                    "file": str(file_path),
                    "relative_path": str(file_path.relative_to(root)).replace("\\", "/"),
                    "name": file_path.name,
                    "match_count": len(matches),
                    "matches": matches[:10],  # 每个文件最多返回 10 处匹配
                })
                if len(results) >= max_results:
                    break

        if not results:
            kw_display = " | ".join(keywords)
            return f"在 {root_path} 中未找到包含 '{kw_display}' 的源码文件"
        return json.dumps(results, ensure_ascii=False, indent=2)

    elif query:
        # workspace 模式 — 简单搜索
        results = []
        for root_dir, dirs, files in os.walk(WORKSPACE):
            dirs[:] = [d for d in dirs if d not in SCAN_IGNORE_DIRS]
            for name in files:
                file_path = Path(root_dir) / name
                if file_path.suffix.lower() not in SCAN_ALLOWED_EXTENSIONS:
                    continue
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    if query.lower() in content.lower():
                        rel_path = file_path.relative_to(WORKSPACE)
                        results.append(str(rel_path))
                except (PermissionError, OSError):
                    continue

        if not results:
            return f"未找到包含 '{query}' 的文件"
        return f"找到 {len(results)} 个匹配文件:\n" + "\n".join(results)

    else:
        raise ToolError("请提供 query（workspace 搜索）或 keyword + root_path（项目搜索）", "search_file")


def scan_menu_structure(project_path: str) -> str:
    """扫描项目中的菜单组件和路由配置文件，提取页面路径

    搜索策略：
    1. 主动检查常见路由路径：src/router/index.js、src/router/index.ts、src/main.js 等
    2. 搜索文件名包含 menu/sidebar/nav/routes/router 关键词的文件
    3. 提取路由路径和组件引用信息

    Raises:
        ToolError: 项目路径不存在 / 不是目录
    """
    root = Path(project_path).resolve()
    if not root.exists():
        raise ToolError(f"项目路径不存在: {project_path}", "scan_menu_structure")
    if not root.is_dir():
        raise ToolError(f"不是目录: {project_path}", "scan_menu_structure")

    menu_files = []
    menu_keywords = ["menu", "sidebar", "nav", "navigation", "routes", "router"]

    for pattern in ["*.vue", "*.ts", "*.js"]:
        for file in root.rglob(pattern):
            if _is_ignored(file):
                continue
            filename_lower = file.name.lower()
            if any(kw in filename_lower for kw in menu_keywords):
                menu_files.append(file)

    common_router_paths = [
        root / "src" / "router" / "index.js",
        root / "src" / "router" / "index.ts",
        root / "src" / "router.js",
        root / "src" / "router.ts",
        root / "src" / "main.js",
        root / "src" / "main.ts",
        root / "router" / "index.js",
        root / "router" / "index.ts",
    ]
    for router_file in common_router_paths:
        if router_file.exists() and router_file.is_file() and router_file not in menu_files:
            menu_files.append(router_file)

    menu_info = {
        "framework": "unknown",
        "router": {
            "exists": False,
            "files": [],
            "dynamic": False,
        },
        "menu": {
            "type": "component",
            "files": [],
        },
        "menu_files": [],
        "extracted_routes": [],
        "route_file_paths": [],
        "menu_component_paths": [],
        "entry_points": [],
    }

    for file in sorted(menu_files):
        rel_path = str(file.relative_to(root)).replace("\\", "/")
        is_menu_comp = any(kw in rel_path.lower() for kw in ["menu", "sidebar", "nav"])
        is_router = any(kw in rel_path.lower() for kw in ["router", "routes"])
        is_entry = rel_path in ["src/main.js", "src/main.ts", "main.js", "main.ts"]

        try:
            content = file.read_text(encoding="utf-8", errors="ignore")
        except (PermissionError, OSError):
            continue

        routes = _extract_routes_from_content(content)
        has_dynamic_routes = any(keyword in content.lower() for keyword in ["addroute", "dynamic", "async"])

        entry = {
            "file": str(file),
            "relative_path": rel_path,
            "type": "menu_component" if is_menu_comp else ("entry_point" if is_entry else "route_config"),
            "extracted_routes": routes,
            "has_dynamic_routes": has_dynamic_routes,
        }

        if is_menu_comp:
            menu_info["menu_component_paths"].append(rel_path)
            menu_info["menu"]["files"].append(rel_path)
        elif is_entry:
            menu_info["entry_points"].append(rel_path)
        else:
            menu_info["route_file_paths"].append(rel_path)
            menu_info["router"]["files"].append(rel_path)
            menu_info["router"]["exists"] = True

        if has_dynamic_routes:
            menu_info["router"]["dynamic"] = True

        menu_info["menu_files"].append(entry)
        menu_info["extracted_routes"].extend(routes)

    menu_info["extracted_routes"] = sorted(set(menu_info["extracted_routes"]))

    if (root / "package.json").exists():
        try:
            pkg_content = (root / "package.json").read_text(encoding="utf-8", errors="ignore")
            pkg_data = json.loads(pkg_content)
            deps = {**(pkg_data.get("dependencies", {})), **(pkg_data.get("devDependencies", {}))}
            if "vue" in deps:
                menu_info["framework"] = "vue"
            elif "react" in deps:
                menu_info["framework"] = "react"
            elif "angular" in deps:
                menu_info["framework"] = "angular"
        except (json.JSONDecodeError, OSError):
            pass

    return json.dumps(menu_info, ensure_ascii=False, indent=2)


def _extract_routes_from_content(content: str) -> list[str]:
    """从文件内容中提取路由/path/url 信息"""
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
            if (match.startswith("/")
                or match.startswith("@/")
                or match.startswith("./")
                or match.startswith("../")
                or match.endswith(".vue")):
                routes.append(match)

    special_patterns = [
        r"import\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"resolve\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"require\(\s*['\"]([^'\"]+)['\"]\s*\)",
    ]

    for pattern in special_patterns:
        matches = re.findall(pattern, content)
        routes.extend(matches)

    return sorted(set(routes))


# ─── 写入类工具（仅限 workspace 内操作）───

def write_file(path: str, content: str) -> str:
    """创建或覆盖文件（仅限 workspace 内操作）

    Raises:
        PathSecurityError: 路径安全限制
    """
    file_path = _resolve_path(path, restrict_to_workspace=True)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return f"✅ 文件创建成功: {path}"


def delete_file(path: str) -> str:
    """删除文件（仅限 workspace 内操作）

    Raises:
        PathSecurityError: 路径安全限制
        FileNotFound: 文件不存在
    """
    file_path = _resolve_path(path, restrict_to_workspace=True)
    if not file_path.exists():
        raise FileNotFound(path)
    file_path.unlink()
    return f"✅ 文件删除成功: {path}"


def append_file(path: str, content: str) -> str:
    """向文件末尾追加内容（仅限 workspace 内操作）

    Raises:
        PathSecurityError: 路径安全限制
    """
    file_path = _resolve_path(path, restrict_to_workspace=True)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "a", encoding="utf-8") as f:
        f.write("\n" + content)
    return f"✅ 文件追加成功: {path}"


def create_folder(path: str) -> str:
    """创建文件夹（仅限 workspace 内操作）

    Raises:
        PathSecurityError: 路径安全限制
    """
    folder_path = _resolve_path(path, restrict_to_workspace=True)
    folder_path.mkdir(parents=True, exist_ok=True)
    return f"✅ 文件夹创建成功: {path}"


# ─── 工具定义（OpenAI function calling 格式）───
# 合并了原 agent/tools/filesystem.py 和 app/tools.py 的定义
# 统一支持绝对路径（项目扫描）和相对路径（workspace 操作）

tool_definitions = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": """读取文件内容。

适合场景：
- 用户要求查看文件内容、分析代码
- 需要精读某个文件的具体实现

不适合场景：
- 查看目录结构（应使用 list_dir）
- 搜索代码（应使用 search_file）

耗时：低

路径规则：
- 绝对路径：用于读取用户项目文件，如 'D:/projects/xxx/src/App.vue'
- 相对路径：用于 workspace 内操作，如 'skill/hello.md'

重要规则：
- 必须使用此工具获取真实内容，禁止猜测文件内容
- 大文件建议设置 max_size 限制，避免内存溢出""",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径。绝对路径如 'D:/projects/xxx/src/App.vue'；workspace 相对路径如 'skill/hello.md'"
                    },
                    "max_size": {
                        "type": "integer",
                        "description": "最大读取字节数，默认 1MB",
                        "default": 1048576
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": """列出目录内容，返回真实的文件系统结构。

适合场景：
- 用户要求扫描项目、查看目录结构
- 需要了解项目的目录组织方式
- 分析项目必须先调用此工具获取基础结构

不适合场景：
- 读取文件内容（应使用 read_file）
- 深度扫描项目结构（应使用 project_discover 或 scan_project）

耗时：低到中（视目录大小而定）

路径规则：
- 绝对路径：用于扫描用户项目，如 'D:/projects/xxx'
- 相对路径：用于 workspace 内操作，如 'skill'
- 留空：workspace 根目录

重要规则：
- 必须使用此工具获取真实结果，禁止猜测或推断目录结构
- 建议 max_depth 设置为 1-3 层，过深会导致结果过大
- 分析项目流程：list_dir(root, max_depth=5) → 判断技术栈 → 再决定是否深入""",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "目录路径。绝对路径如 'D:/projects/xxx'（扫描用户项目）；workspace 相对路径如 'skill'；留空为 workspace 根目录"
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "是否递归列出子目录内容，默认 false",
                        "default": False
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "递归的最大深度，默认 5。建议 1-3 层即可，过深会导致结果过大",
                        "default": 5
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_file",
            "description": """搜索项目源码内容，返回匹配行号和上下文代码。

适合场景：
- 定位具体业务代码（最精准的方式）
- 根据需求文档中的字段名或业务术语搜索源码
- 查找特定功能的实现位置

不适合场景：
- 查看目录结构（应使用 list_dir）
- 快速了解技术栈（应使用 project_discover）

耗时：中到高（视项目大小和搜索范围而定）

搜索模式：
- 项目模式（推荐）：传 keyword + root_path 搜索指定项目目录
- workspace 模式：只传 query，在 workspace 内搜索

重要规则：
- 使用需求文档中的字段名、业务术语、组件名作为 keyword
- 支持逗号分隔多关键词（OR逻辑），如 '研究状态,followStatus'
- 可用 file_extensions 过滤文件类型，如 'vue,js,ts'
- 默认只搜索源码文件，排除 .md/.json/.txt 等非源码文件""",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "workspace 内搜索的关键词（简单模式）"
                    },
                    "keyword": {
                        "type": "string",
                        "description": "项目内搜索的关键词（项目模式，需配合 root_path）。支持逗号分隔多关键词（OR逻辑），如 '研究状态,followStatus' 或 '病灶编号,US-1'。建议用需求文档中的字段名、业务术语、组件名作为关键词"
                    },
                    "root_path": {
                        "type": "string",
                        "description": "搜索的根目录绝对路径（项目模式，如 '/Users/xxx/projects/my-project'）"
                    },
                    "file_extensions": {
                        "type": "string",
                        "description": "过滤文件扩展名（逗号分隔），如 'vue,js,ts'。不传则默认搜索所有源码文件",
                        "default": ""
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "每个匹配行上下显示的上下文行数，默认 3",
                        "default": 3
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回文件数，默认 20",
                        "default": 20
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scan_menu_structure",
            "description": """扫描项目中的菜单组件和路由配置文件，提取其中定义的页面路径。

适合场景：
- 用户要求分析项目结构、查找业务页面
- 需要获取项目的路由配置和页面映射关系

不适合场景：
- 读取具体文件内容（应使用 read_file）
- 搜索特定代码（应使用 search_file）

耗时：中

重要规则：
- 当用户要求分析项目结构、查找业务页面时，必须先调用此工具获取菜单和路由信息
- 这是定位真实页面路径的最准确方法
- 会自动搜索 menu/sidebar/nav/routes/router 相关文件""",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "项目的绝对路径，如 'D:/projects/xxx'"
                    }
                },
                "required": ["project_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "创建或覆盖文件（仅限 workspace 目录内操作，不支持绝对路径）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径，相对于 workspace 目录，如 'skill/hello.md'"},
                    "content": {"type": "string", "description": "文件内容"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "删除文件（仅限 workspace 目录内操作，不支持绝对路径）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径，相对于 workspace 目录"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "append_file",
            "description": "向文件末尾追加内容（仅限 workspace 目录内操作，不支持绝对路径）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径，相对于 workspace 目录"},
                    "content": {"type": "string", "description": "要追加的内容"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_folder",
            "description": "创建文件夹（仅限 workspace 目录内操作，不支持绝对路径）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件夹路径，相对于 workspace 目录"}
                },
                "required": ["path"]
            }
        }
    },
]

# ─── 工具执行映射 ───

tool_handlers = {
    "read_file": lambda args: read_file(
        args.get("path", "") or args.get("file_path", "") or args.get("filename", ""),
        max_size=args.get("max_size", 1048576)
    ),
    "list_dir": lambda args: list_dir(
        path=args.get("path", "") or args.get("dir_path", "") or args.get("directory", ""),
        recursive=args.get("recursive", False),
        max_depth=args.get("max_depth", 5)
    ),
    "search_file": lambda args: search_file(
        query=args.get("query", ""),
        keyword=args.get("keyword", "") or args.get("keywords", ""),
        root_path=args.get("root_path", "") or args.get("path", "") or args.get("project_path", ""),
        max_results=args.get("max_results", 20),
        file_extensions=args.get("file_extensions", "") or args.get("extensions", ""),
        context_lines=args.get("context_lines", 3)
    ),
    "scan_menu_structure": lambda args: scan_menu_structure(
        args.get("project_path", "") or args.get("path", "") or args.get("root_path", "")
    ),
    "write_file": lambda args: write_file(
        args.get("path", "") or args.get("file_path", ""),
        args.get("content", "")
    ),
    "delete_file": lambda args: delete_file(
        args.get("path", "") or args.get("file_path", "")
    ),
    "append_file": lambda args: append_file(
        args.get("path", "") or args.get("file_path", ""),
        args.get("content", "")
    ),
    "create_folder": lambda args: create_folder(
        args.get("path", "") or args.get("folder_path", "")
    ),
}
