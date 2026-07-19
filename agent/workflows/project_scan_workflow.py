"""Project Scan Workflow — 固定项目扫描流程 + 知识库持久化

将项目分析从通用 ReAct Agent 中分离出来，使用固定流水线：
  1. list_dir(root) → 获取目录结构
  2. read package.json → 获取技术栈信息
  3. read main.js → 获取入口文件
  4. scan_menu_structure → 获取路由和菜单
  5. read router → 获取路由配置
  6. read store → 获取状态管理
  7. scan api → 获取接口定义
  8. analyze pages → 页面能力分析（Code Understanding）
  9. generate summary → 生成项目报告
  10. save knowledge → 持久化到 workspace/memory/

状态机追踪：
  - structure_found: 目录结构已获取
  - package_found: package.json 已读取
  - entry_found: 入口文件已读取
  - router_found: 路由配置已获取
  - store_found: 状态管理已获取
  - api_found: API 接口已扫描
  - pages_analyzed: 页面能力分析完成
  - summary_ready: 报告已生成

流程收敛条件：
  - 所有关键节点完成 → 自动结束
  - 达到最大步骤(10) → 强制结束并输出已完成内容

知识库持久化：
  - workspace/memory/项目名/project.json → 项目元信息
  - workspace/memory/项目名/routes.json → 路由信息
  - workspace/memory/项目名/api.json → API 接口信息
  - workspace/memory/项目名/knowledge.json → 项目知识模型
  - workspace/memory/项目名/business_capabilities.md → 业务能力总结
  - workspace/memory/项目名/architecture.md → 架构文档
"""

import json
import logging
import asyncio
import os
from pathlib import Path
from typing import Literal

from agent.registry.capability_registry import CapabilityRegistry
from agent.tools.filesystem import list_dir, read_file, search_file, scan_menu_structure
from agent.tools.project import project_discover
from app.config import WORKSPACE
from app.services.code_understanding_service import CodeUnderstandingService

logger = logging.getLogger("gt_agent.workflows.project_scan")

MAX_SCAN_STEPS = 80
TOOL_TIMEOUT = 30
MAX_FILES_TO_ANALYZE = 25  # 限制分析的文件数量（平衡深度与速度）
MAX_FILE_CONTENT_LENGTH = 3000  # 每个文件最大读取字符数


def get_project_knowledge_dir(project_name: str) -> Path:
    """获取项目知识库目录"""
    return WORKSPACE / "memory" / project_name


def load_project_knowledge(project_name: str) -> dict:
    """加载已保存的项目知识"""
    knowledge_dir = get_project_knowledge_dir(project_name)
    if not knowledge_dir.exists():
        return None
    
    project_json = knowledge_dir / "project.json"
    if not project_json.exists():
        return None
    
    try:
        with open(project_json, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return None


def save_project_knowledge(project_name: str, data: dict, knowledge: dict = None):
    """保存项目知识到 workspace"""
    knowledge_dir = get_project_knowledge_dir(project_name)
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    
    project_json = knowledge_dir / "project.json"
    with open(project_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    routes_json = knowledge_dir / "routes.json"
    if data.get("router_info"):
        with open(routes_json, "w", encoding="utf-8") as f:
            json.dump(data.get("router_info", {}), f, ensure_ascii=False, indent=2)
    
    api_json = knowledge_dir / "api.json"
    if data.get("api_info"):
        with open(api_json, "w", encoding="utf-8") as f:
            json.dump(data.get("api_info", {}), f, ensure_ascii=False, indent=2)
    
    architecture_md = knowledge_dir / "architecture.md"
    summary = data.get("summary", "")
    if summary:
        with open(architecture_md, "w", encoding="utf-8") as f:
            f.write(summary)
    
    if knowledge:
        knowledge_json = knowledge_dir / "knowledge.json"
        with open(knowledge_json, "w", encoding="utf-8") as f:
            json.dump(knowledge, f, ensure_ascii=False, indent=2)
        
        code_understanding = CodeUnderstandingService()
        business_summary = code_understanding.summarize_business_capabilities(knowledge)
        business_md = knowledge_dir / "business_capabilities.md"
        with open(business_md, "w", encoding="utf-8") as f:
            f.write(business_summary)
    
    logger.info("项目知识已保存: %s", knowledge_dir)


def detect_project_type(project_path: str) -> str:
    """检测项目类型
    
    Returns:
        项目类型: python, node, go, java, rust, generic
    """
    root = Path(project_path)
    
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        return "python"
    if (root / "package.json").exists():
        return "node"
    if (root / "go.mod").exists():
        return "go"
    if (root / "pom.xml").exists() or (root / "build.gradle").exists():
        return "java"
    if (root / "Cargo.toml").exists():
        return "rust"
    
    return "generic"


def get_scan_paths_by_type(project_type: str, project_path: str) -> list[dict]:
    """根据项目类型返回关键扫描路径
    
    Returns:
        扫描路径列表，每个元素为 {"path": 路径, "max_depth": 深度, "phase": 阶段}
    """
    root = Path(project_path)
    
    if project_type == "python":
        # Python 项目：扫描根包目录（通常与项目名相同）
        src_dirs = []
        for item in root.iterdir():
            if item.is_dir() and not item.name.startswith(".") and item.name not in ["venv", "env", ".git", "__pycache__", "node_modules"]:
                if (item / "__init__.py").exists() or any(f.suffix == ".py" for f in item.iterdir() if f.is_file()):
                    src_dirs.append(item.name)
        
        return [
            {"path": str(root), "max_depth": 4, "phase": "profile"},
            {"path": str(root / "tests"), "max_depth": 3, "phase": "architecture"} if (root / "tests").exists() else None,
            {"path": str(root / "docs"), "max_depth": 3, "phase": "architecture"} if (root / "docs").exists() else None,
        ] + [{"path": str(root / d), "max_depth": 4, "phase": "business"} for d in src_dirs]
    
    elif project_type == "node":
        return [
            {"path": str(root), "max_depth": 3, "phase": "profile"},
            {"path": str(root / "src"), "max_depth": 4, "phase": "architecture"} if (root / "src").exists() else None,
            {"path": str(root / "app"), "max_depth": 4, "phase": "architecture"} if (root / "app").exists() else None,
            {"path": str(root / "pages"), "max_depth": 5, "phase": "business"} if (root / "pages").exists() else None,
            {"path": str(root / "components"), "max_depth": 4, "phase": "business"} if (root / "components").exists() else None,
        ]
    
    elif project_type == "go":
        return [
            {"path": str(root), "max_depth": 4, "phase": "profile"},
            {"path": str(root / "cmd"), "max_depth": 3, "phase": "architecture"} if (root / "cmd").exists() else None,
            {"path": str(root / "pkg"), "max_depth": 4, "phase": "business"} if (root / "pkg").exists() else None,
            {"path": str(root / "internal"), "max_depth": 4, "phase": "business"} if (root / "internal").exists() else None,
            {"path": str(root / "api"), "max_depth": 3, "phase": "business"} if (root / "api").exists() else None,
        ]
    
    elif project_type == "java":
        src_main = root / "src" / "main"
        return [
            {"path": str(root), "max_depth": 3, "phase": "profile"},
            {"path": str(src_main), "max_depth": 5, "phase": "architecture"} if src_main.exists() else None,
        ]
    
    elif project_type == "rust":
        return [
            {"path": str(root), "max_depth": 3, "phase": "profile"},
            {"path": str(root / "src"), "max_depth": 4, "phase": "architecture"} if (root / "src").exists() else None,
        ]
    
    else:  # generic
        return [
            {"path": str(root), "max_depth": 4, "phase": "profile"},
        ]


def collect_source_files(
    project_path: str,
    project_type: str,
    max_files: int = MAX_FILES_TO_ANALYZE,
) -> list[dict]:
    """递归收集项目中的源文件，按重要性排序
    
    优先级规则：
    1. 目录深度越浅越优先
    2. __init__.py、main、core、base、runner、loop 等核心文件优先
    3. 同深度按目录名排序（主包优先于 tests/docs）
    
    Args:
        project_path: 项目根目录
        project_type: 项目类型
        max_files: 最大文件数
    
    Returns:
        文件列表 [{"path": 相对路径, "type": 文件类型}]
    """
    root = Path(project_path)
    
    # 根据项目类型定义源文件扩展名
    source_extensions = {
        "python": [".py"],
        "node": [".js", ".ts", ".vue", ".tsx", ".jsx", ".svelte"],
        "go": [".go"],
        "java": [".java"],
        "rust": [".rs"],
        "generic": [".py", ".js", ".ts", ".java", ".go", ".rs", ".vue", ".tsx", ".jsx"],
    }.get(project_type, [".py", ".js", ".ts", ".java", ".go", ".rs", ".vue", ".tsx", ".jsx"])
    
    # 忽略的目录
    ignore_dirs = {
        "node_modules", ".git", "__pycache__", "venv", "env", ".venv",
        "dist", "build", ".next", ".nuxt", "target", "bin", "obj",
        ".cache", "coverage", ".coverage", "tests", "test",
        "scripts", "docs", "examples", "sample",
    }
    
    # 核心文件名（高优先级）
    core_names = {
        "__init__.py", "__main__.py", "main.py", "app.py", "core.py",
        "base.py", "runner.py", "loop.py", "engine.py", "manager.py",
        "registry.py", "factory.py", "context.py", "config.py",
        "main.go", "main.rs", "lib.rs", "index.js", "index.ts",
    }
    
    all_files = []
    
    for root_path, dirs, files in os.walk(project_path):
        # 过滤忽略目录
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        
        for file in files:
            if Path(file).suffix.lower() in source_extensions:
                full_path = Path(root_path) / file
                rel_path = str(full_path.relative_to(root)).replace("\\", "/")
                
                # 计算优先级分数（越小越优先）
                depth = rel_path.count("/")
                score = depth * 10  # 深度权重
                
                # 核心文件加分
                if file in core_names:
                    score -= 5
                elif file.startswith("_"):
                    score += 2  # 私有文件低优先
                
                all_files.append({
                    "path": rel_path,
                    "full_path": str(full_path),
                    "type": Path(file).suffix.lower(),
                    "_score": score,
                })
    
    # 按分数排序，取前 max_files 个
    all_files.sort(key=lambda f: f["_score"])
    result = all_files[:max_files]
    
    # 移除内部排序字段
    for f in result:
        del f["_score"]
    
    return result


class ProjectAnalysisState:
    """项目分析状态机 — 多阶段流水线（支持多项目类型）"""

    # 阶段定义
    PHASE_PROFILE = "profile"      # 阶段1: 项目画像
    PHASE_ARCHITECTURE = "architecture"  # 阶段2: 架构扫描
    PHASE_BUSINESS = "business"    # 阶段3: 业务理解
    PHASE_ANALYSIS = "analysis"    # 阶段4: 代码理解
    PHASE_DONE = "done"

    def __init__(self, project_path: str, project_type: str = "generic"):
        self.project_path = project_path
        self.project_type = project_type
        self.phase = self.PHASE_PROFILE

        # 阶段1: 项目画像
        self.structure_found = False
        self.package_found = False
        self.config_found = False

        # 阶段2: 架构扫描
        self.src_scanned = False
        self.entry_found = False
        self.router_found = False

        # 阶段3: 业务理解
        self.store_found = False
        self.api_found = False
        self.views_found = False

        # 阶段4: 代码理解
        self.pages_analyzed = False

        self.summary_ready = False

        self.results = {
            "root_structure": {},
            "package_info": {},
            "config_info": {},
            "src_structure": {},
            "entry_info": {},
            "router_info": {},
            "store_info": {},
            "api_info": {},
            "views_info": {},
            "menu_info": {},
        }

        self.step = 0

    def is_complete(self) -> bool:
        """检查是否完成扫描（收敛条件）
        
        根据项目类型设置不同的完成条件：
        - Python: structure + package + src_scanned + pages_analyzed
        - Node: structure + package + router + pages_analyzed
        - Generic: structure + pages_analyzed
        """
        if self.summary_ready:
            return True
        
        # 通用必要条件
        core_items = [self.structure_found, self.package_found]
        
        # 根据项目类型添加额外条件
        if self.project_type == "python":
            # Python 项目：不需要 router，但需要源码扫描
            type_items = [self.src_scanned]
        elif self.project_type == "node":
            # Node 项目：保持现有逻辑，router 可选
            type_items = [self.router_found]
        elif self.project_type in ["go", "java", "rust"]:
            # 编译型语言：不需要 router
            type_items = [self.src_scanned]
        else:
            # 通用：只要 structure 和 package
            type_items = []
        
        core_done = all(core_items) and all(type_items)
        
        # 代码分析完成
        analysis_done = self.pages_analyzed
        
        # 至少完成核心部分 + 代码分析
        return (core_done and analysis_done) or self.summary_ready

    def progress(self) -> float:
        """返回完成进度 (0.0-1.0)"""
        total = 9
        completed = sum([
            self.structure_found,
            self.package_found,
            self.config_found,
            self.src_scanned,
            self.entry_found,
            self.router_found,
            self.store_found,
            self.api_found,
            self.pages_analyzed,
        ])
        return completed / total

    def _collect_page_files_recursive(self, items: list) -> list:
        """递归收集嵌套结构中的页面文件路径"""
        result = []
        seen = set()
        
        def _traverse(items_list):
            for item in items_list:
                item_type = item.get("type", "")
                item_name = item.get("name", "")
                item_path = item.get("path", "")
                
                if item_type == "file" and item_name.endswith((".vue", ".tsx", ".jsx")):
                    full_path = item_path if item_path else item_name
                    if full_path not in seen:
                        seen.add(full_path)
                        result.append(full_path)
                elif item_type == "directory":
                    children = item.get("children", [])
                    if children:
                        _traverse(children)
        
        _traverse(items)
        return result

    def next_action(self) -> dict:
        """根据当前状态决定下一步动作 — 多阶段流水线（自适应项目类型）"""
        self.step += 1

        if self.summary_ready:
            return {"tool": "finish", "args": {}}

        # ── 阶段1: 项目画像 ──
        if self.phase == self.PHASE_PROFILE:
            if not self.structure_found:
                # 根目录递归扫描，深度 3 层，获取完整的嵌套结构
                return {"tool": "list_dir", "args": {"path": self.project_path, "recursive": True, "max_depth": 3}}

            if not self.package_found:
                # 根据项目类型读取配置文件
                config_files = {
                    "python": ["pyproject.toml", "requirements.txt", "setup.py"],
                    "node": ["package.json"],
                    "go": ["go.mod"],
                    "java": ["pom.xml", "build.gradle"],
                    "rust": ["Cargo.toml"],
                    "generic": ["pyproject.toml", "package.json", "go.mod", "pom.xml"],
                }.get(self.project_type, [])
                
                for config_name in config_files:
                    config_path = str(Path(self.project_path) / config_name)
                    if Path(config_path).exists():
                        return {"tool": "read_file", "args": {"path": config_path}}

            # 读取 README.md
            if not self.results.get("readme_info"):
                readme_path = str(Path(self.project_path) / "README.md")
                if Path(readme_path).exists():
                    return {"tool": "read_file", "args": {"path": readme_path}}

            # 阶段1完成，进入阶段2
            self.phase = self.PHASE_ARCHITECTURE
            # 初始化待扫描目录队列
            self._arch_scan_queue = self._build_arch_scan_queue()

        # ── 阶段2: 架构扫描 ──
        if self.phase == self.PHASE_ARCHITECTURE:
            # 逐个扫描架构目录
            if hasattr(self, '_arch_scan_queue') and self._arch_scan_queue:
                dir_info = self._arch_scan_queue.pop(0)
                return {"tool": "list_dir", "args": {
                    "path": dir_info["path"],
                    "recursive": True,
                    "max_depth": dir_info.get("max_depth", 3),
                }}

            # Python 项目不需要 router
            if self.project_type == "node" and not self.router_found:
                return {"tool": "scan_menu_structure", "args": {"project_path": self.project_path}}

            # 阶段2完成，进入阶段3
            self.phase = self.PHASE_BUSINESS

        # ── 阶段3: 业务理解 ──
        if self.phase == self.PHASE_BUSINESS:
            if self.project_type == "node":
                # 前端项目：扫描 views/pages
                if not self.views_found:
                    for dir_name in ["views", "pages", "app", "screens"]:
                        dir_path = str(Path(self.project_path) / "src" / dir_name)
                        if Path(dir_path).exists():
                            return {"tool": "list_dir", "args": {"path": dir_path, "recursive": True, "max_depth": 5}}

                if not self.store_found:
                    store_dir = str(Path(self.project_path) / "src" / "store")
                    if Path(store_dir).exists():
                        return {"tool": "list_dir", "args": {"path": store_dir, "recursive": True, "max_depth": 2}}

                if not self.api_found:
                    for dir_name in ["api", "http", "services"]:
                        dir_path = str(Path(self.project_path) / "src" / dir_name)
                        if Path(dir_path).exists():
                            return {"tool": "list_dir", "args": {"path": dir_path, "recursive": True, "max_depth": 2}}

            # 阶段3完成
            self.phase = self.PHASE_ANALYSIS

        # ── 阶段4: 代码理解（读取源文件内容）──
        if self.phase == self.PHASE_ANALYSIS:
            if not hasattr(self, "_pages_list_initialized"):
                pages_to_read = []
                
                if self.project_type == "node":
                    views_info = self.results.get("views_info", {})
                    if isinstance(views_info, dict):
                        items = views_info.get("items", [])
                        pages_to_read = self._collect_page_files_recursive(items)
                else:
                    source_files = collect_source_files(
                        self.project_path,
                        self.project_type,
                        max_files=MAX_FILES_TO_ANALYZE,
                    )
                    pages_to_read = [f["full_path"] for f in source_files]
                
                self.results["pages_to_analyze"] = pages_to_read
                self.current_page_index = 0
                self._pages_list_initialized = True
            
            pages_to_read = self.results.get("pages_to_analyze", [])
            
            if self.current_page_index < len(pages_to_read):
                page_path = pages_to_read[self.current_page_index]
                if not page_path.startswith("D:") and not page_path.startswith("/"):
                    page_path = str(Path(self.project_path) / page_path)
                self.current_page_index += 1
                return {"tool": "read_file", "args": {"path": page_path}}
            else:
                self.pages_analyzed = True
                return {"tool": "analyze_code", "args": {}}

        return {"tool": "finish", "args": {}}

    def _build_arch_scan_queue(self) -> list:
        """构建架构扫描目录队列"""
        root = Path(self.project_path)
        queue = []
        
        if self.project_type == "python":
            # Python 项目：找到主包目录（含 __init__.py 的目录）
            for item in root.iterdir():
                if item.is_dir() and not item.name.startswith(".") and item.name not in [
                    "venv", "env", ".git", "__pycache__", "node_modules", ".venv"
                ]:
                    if (item / "__init__.py").exists():
                        queue.append({"path": str(item), "max_depth": 3})
            # 补充常见目录
            for dir_name in ["tests", "docs", "scripts", "app", "src", "lib"]:
                dir_path = root / dir_name
                if dir_path.exists() and not any(q["path"] == str(dir_path) for q in queue):
                    queue.append({"path": str(dir_path), "max_depth": 2})
        
        elif self.project_type == "node":
            for dir_name in ["src", "app", "pages", "components", "lib"]:
                dir_path = root / dir_name
                if dir_path.exists():
                    queue.append({"path": str(dir_path), "max_depth": 3})
        
        elif self.project_type == "go":
            for dir_name in ["cmd", "pkg", "internal", "api"]:
                dir_path = root / dir_name
                if dir_path.exists():
                    queue.append({"path": str(dir_path), "max_depth": 3})
        
        elif self.project_type == "java":
            src_main = root / "src" / "main"
            if src_main.exists():
                queue.append({"path": str(src_main), "max_depth": 4})
        
        elif self.project_type == "rust":
            src_dir = root / "src"
            if src_dir.exists():
                queue.append({"path": str(src_dir), "max_depth": 3})
        
        else:  # generic
            for dir_name in ["src", "app", "lib", "tests"]:
                dir_path = root / dir_name
                if dir_path.exists():
                    queue.append({"path": str(dir_path), "max_depth": 3})
        
        return queue


async def run_project_scan(project_path: str, registry: CapabilityRegistry):
    """运行固定项目扫描流程
    
    Args:
        project_path: 项目绝对路径
        registry: 能力注册中心
    
    Yields:
        事件流：状态更新、工具调用、结果汇总
    """
    project_name = Path(project_path).name
    
    # 检查是否已有项目知识，如有则直接加载跳过扫描
    knowledge_json_path = WORKSPACE / "memory" / project_name / "knowledge.json"
    project_json_path = WORKSPACE / "memory" / project_name / "project.json"
    if knowledge_json_path.exists() and project_json_path.exists():
        yield {"type": "status", "message": f"发现已有项目知识，直接加载: {project_name}"}
        logger.info(f"已有项目知识，跳过扫描: {project_name}")
        try:
            existing_knowledge = json.loads(knowledge_json_path.read_text(encoding="utf-8"))
            existing_project = json.loads(project_json_path.read_text(encoding="utf-8"))
            summary = existing_project.get("summary", existing_knowledge.get("summary", "项目知识已加载"))
            yield {"type": "summary", "content": summary, "analysis_state": existing_knowledge}
            yield {
                "type": "project_scan_done",
                "response": summary,
                "project_context": {
                    "project_name": project_name,
                    "project_path": project_path,
                    "has_knowledge": True,
                }
            }
            return
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"加载已有项目知识失败，将重新扫描: {e}")
    
    # 检测项目类型
    project_type = detect_project_type(project_path)
    logger.info(f"检测到项目类型: {project_type}")
    yield {"type": "status", "message": f"检测到项目类型: {project_type}"}
    
    analysis_state = ProjectAnalysisState(project_path, project_type)
    
    yield {"type": "status", "message": f"开始扫描项目: {project_path}"}
    
    code_understanding_service = CodeUnderstandingService()
    knowledge = None
    step = 0
    
    while not analysis_state.is_complete() and step < MAX_SCAN_STEPS:
        action = analysis_state.next_action()
        step += 1
        
        if action["tool"] == "finish":
            break
        
        if action["tool"] == "analyze_code":
            yield {"type": "tool_start", "tool": "analyze_code", "args": {}}
            try:
                yield {"type": "status", "message": "正在分析页面代码，提取业务能力..."}
                
                structure = _build_scan_structure_for_knowledge(project_path, analysis_state)
                knowledge = code_understanding_service.build_project_knowledge(project_path, structure)
                
                yield {"type": "tool_end", "tool": "analyze_code", "status": "success", "result": f"分析完成，共分析 {len(knowledge.get('pages', []))} 个页面"}
                
                progress = analysis_state.progress()
                yield {"type": "status", "message": f"扫描进度: {int(progress * 100)}%"}
            except Exception as e:
                yield {"type": "tool_end", "tool": "analyze_code", "status": "error", "result": str(e)}
                logger.warning("代码分析失败: %s", e)
            continue
        
        yield {"type": "tool_start", "tool": action["tool"], "args": action["args"]}
        
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(registry.execute_tool, action["tool"], action["args"]),
                timeout=TOOL_TIMEOUT,
            )
            yield {"type": "tool_end", "tool": action["tool"], "status": "success", "result": str(result)[:500]}
            
            analysis_state = _update_analysis_state(analysis_state, action["tool"], result)
            
            progress = analysis_state.progress()
            yield {"type": "status", "message": f"扫描进度: {int(progress * 100)}%"}
            
        except asyncio.TimeoutError:
            yield {"type": "tool_end", "tool": action["tool"], "status": "timeout", "result": f"工具执行超时（{TOOL_TIMEOUT}秒）"}
            logger.warning("扫描工具 %s 超时", action["tool"])
        except Exception as e:
            yield {"type": "tool_end", "tool": action["tool"], "status": "error", "result": str(e)}
            logger.warning("扫描工具 %s 失败: %s", action["tool"], e)
    
    yield {"type": "status", "message": "扫描完成，生成项目报告..."}
    
    summary = _generate_project_summary(analysis_state, knowledge)
    analysis_state.results["summary"] = summary
    analysis_state.results["project_name"] = project_name
    analysis_state.results["project_path"] = project_path
    
    if knowledge:
        knowledge["summary"] = summary
        knowledge["project_name"] = project_name
        knowledge["project_path"] = project_path
    
    save_project_knowledge(project_name, analysis_state.results, knowledge)
    yield {"type": "status", "message": f"项目知识已保存到 workspace/documents/{project_name}/"}
    
    final_result = knowledge if knowledge else analysis_state.results
    yield {"type": "summary", "content": summary, "analysis_state": final_result}
    
    yield {
        "type": "project_scan_done",
        "response": summary,
        "project_context": {
            "project_name": project_name,
            "project_path": project_path,
            "has_knowledge": knowledge is not None,
        }
    }


def _collect_files_from_nested(items: list, base_path: Path, project_path: Path, structure_key: str) -> list:
    """递归遍历嵌套的 items 结构，收集文件内容"""
    result = []
    
    def _traverse(items_list, parent_path):
        for item in items_list:
            item_type = item.get("type", "")
            item_name = item.get("name", "")
            item_path = item.get("path", "")
            
            if not item_path:
                item_path = str(parent_path / item_name)
            
            current_path = Path(item_path)
            
            if item_type == "file":
                ext = current_path.suffix.lower()
                if structure_key == "pages" and ext in (".vue", ".tsx", ".jsx"):
                    if current_path.exists():
                        try:
                            content = current_path.read_text(encoding="utf-8", errors="ignore")
                            rel_path = str(current_path.relative_to(project_path)).replace("\\", "/")
                            result.append({
                                "path": rel_path,
                                "content": content[:5000],
                            })
                        except Exception:
                            result.append({"path": str(current_path), "content": ""})
                elif structure_key == "api_modules" and ext in (".js", ".ts"):
                    if current_path.exists():
                        try:
                            content = current_path.read_text(encoding="utf-8", errors="ignore")
                            rel_path = str(current_path.relative_to(project_path)).replace("\\", "/")
                            result.append({
                                "path": rel_path,
                                "content": content[:5000],
                                "symbols": [],
                            })
                        except Exception:
                            result.append({"path": str(current_path), "content": "", "symbols": []})
            elif item_type == "directory":
                children = item.get("children", [])
                if children:
                    _traverse(children, current_path)
    
    _traverse(items, base_path)
    return result


def _build_scan_structure_for_knowledge(project_path: str, analysis_state: ProjectAnalysisState) -> dict:
    """构建用于代码理解的扫描结构（支持多项目类型）"""
    results = analysis_state.results
    package_info = results.get("package_info", {})
    project_type = analysis_state.project_type
    project_path_obj = Path(project_path)
    
    structure = {
        "project": project_path_obj.name,
        "root_path": project_path,
        "project_type": project_type,
        "framework": "",
        "build_tool": "",
        "package_manager": "",
        "dev_command": "",
        "src_dir": "src" if project_type != "python" else project_path_obj.name,
        "ui_libraries": [],
        "pages": [],  # 页面/源文件列表
        "components": [],
        "api_modules": [],
        "router": {"files": [], "routes": []},
        "scanned_at": "",
    }
    
    # 根据项目类型填充技术栈信息
    if project_type == "node":
        deps = package_info.get("dependencies", {})
        dev_deps = package_info.get("devDependencies", {})
        
        if "vue" in deps:
            structure["framework"] = f"Vue {deps['vue']}"
        elif "react" in deps:
            structure["framework"] = f"React {deps['react']}"
        
        if "@vitejs/plugin-vue" in dev_deps or "vite" in dev_deps:
            structure["build_tool"] = "Vite"
        elif "webpack" in dev_deps:
            structure["build_tool"] = "Webpack"
        
        structure["package_manager"] = "npm" if Path(project_path / "package-lock.json").exists() else "pnpm" if Path(project_path / "pnpm-lock.yaml").exists() else "bun" if Path(project_path / "bun.lock").exists() else "unknown"
    
    elif project_type == "python":
        # 从 pyproject.toml 或 requirements.txt 提取信息
        if isinstance(package_info, str):
            content = package_info
        elif isinstance(package_info, dict):
            content = package_info.get("content", str(package_info))
        else:
            content = str(package_info)
        
        # 简单解析
        if "flask" in content.lower():
            structure["framework"] = "Flask"
        elif "django" in content.lower():
            structure["framework"] = "Django"
        elif "fastapi" in content.lower():
            structure["framework"] = "FastAPI"
        
        if "poetry" in content.lower() or "pyproject.toml" in str(package_info):
            structure["build_tool"] = "Poetry/Hatch"
        elif "setup.py" in content.lower():
            structure["build_tool"] = "Setuptools"
    
    elif project_type == "go":
        structure["framework"] = "Go"
        structure["build_tool"] = "Go Modules"
    
    elif project_type == "java":
        if "spring" in str(package_info).lower():
            structure["framework"] = "Spring Boot"
        elif "maven" in str(package_info).lower():
            structure["framework"] = "Maven"
    
    elif project_type == "rust":
        structure["framework"] = "Rust"
        structure["build_tool"] = "Cargo"
    
    # 根据项目类型收集源文件
    if project_type == "node":
        # Node 项目：收集页面和组件
        ui_libs = []
        deps = package_info.get("dependencies", {}) if isinstance(package_info, dict) else {}
        if "element-ui" in deps:
            ui_libs.append("element-ui")
        elif "@element-plus" in deps:
            ui_libs.append("element-plus")
        structure["ui_libraries"] = ui_libs
        
        pages_content = results.get("pages_content", [])
        if pages_content:
            for page in pages_content:
                structure["pages"].append({
                    "path": page["path"],
                    "content": page["content"],
                })
        else:
            views_info = results.get("views_info", {})
            if isinstance(views_info, dict):
                items = views_info.get("items", [])
                views_base_path = project_path_obj / "src" / "views"
                
                if items:
                    structure["pages"] = _collect_files_from_nested(
                        items, views_base_path, project_path_obj, "pages"
                    )
                else:
                    dirs = views_info.get("dirs", [])
                    files = views_info.get("files", [])
                    for f in files:
                        name = f.get("name", "")
                        if name.endswith((".vue", ".tsx", ".jsx")):
                            full_path = project_path_obj / "src" / "views" / name
                            if full_path.exists():
                                try:
                                    content = full_path.read_text(encoding="utf-8", errors="ignore")
                                    rel_path = f"src/views/{name}"
                                    structure["pages"].append({
                                        "path": rel_path,
                                        "content": content[:5000],
                                    })
                                except Exception:
                                    structure["pages"].append({"path": f"src/views/{name}", "content": ""})
    
    else:
        # Python/Go/Java/Rust：使用 collect_source_files 收集所有源文件
        source_files = collect_source_files(
            project_path,
            project_type,
            max_files=MAX_FILES_TO_ANALYZE,
        )
        
        pages_content = results.get("pages_content", [])
        page_content_map = {p["path"]: p["content"] for p in pages_content} if pages_content else {}
        
        for file_info in source_files:
            rel_path = file_info["path"]
            content = page_content_map.get(rel_path, "")
            
            if not content and file_info.get("full_path"):
                try:
                    full_path = Path(file_info["full_path"])
                    if full_path.exists():
                        content = full_path.read_text(encoding="utf-8", errors="ignore")[:MAX_FILE_CONTENT_LENGTH]
                except Exception:
                    content = ""
            
            structure["pages"].append({
                "path": rel_path,
                "content": content,
            })
    
    src_structure = results.get("src_structure", {})
    if isinstance(src_structure, dict):
        dirs = src_structure.get("dirs", [])
        
        if "components" in dirs:
            comp_dir = project_path_obj / "src" / "components"
            if comp_dir.exists():
                for comp_file in comp_dir.rglob("*"):
                    if comp_file.is_file() and comp_file.suffix in (".vue", ".tsx", ".jsx"):
                        rel_path = str(comp_file.relative_to(project_path_obj)).replace("\\", "/")
                        try:
                            content = comp_file.read_text(encoding="utf-8", errors="ignore")
                            structure["components"].append({
                                "path": rel_path,
                                "content": content[:5000],
                            })
                        except Exception:
                            structure["components"].append({"path": rel_path, "content": ""})
    
    api_info = results.get("api_info", {})
    if isinstance(api_info, dict):
        api_path = api_info.get("path", "")
        items = api_info.get("items", [])
        
        if api_path:
            api_base_dir = Path(api_path)
            
            if items:
                structure["api_modules"] = _collect_files_from_nested(
                    items, api_base_dir, project_path_obj, "api_modules"
                )
            else:
                for api_file in api_base_dir.rglob("*"):
                    if api_file.is_file() and api_file.suffix in (".js", ".ts"):
                        rel_path = str(api_file.relative_to(project_path_obj)).replace("\\", "/")
                        try:
                            content = api_file.read_text(encoding="utf-8", errors="ignore")
                            structure["api_modules"].append({
                                "path": rel_path,
                                "content": content[:5000],
                                "symbols": [],
                            })
                        except Exception:
                            structure["api_modules"].append({"path": rel_path, "content": "", "symbols": []})
    
    return structure


def _update_analysis_state(state: ProjectAnalysisState, tool: str, result: str) -> ProjectAnalysisState:
    """根据工具结果更新分析状态"""
    logger.info(f"工具返回: tool={tool}, result_type={type(result).__name__}, result_length={len(str(result)) if result else 0}")
    
    data = None
    content = ""
    file_path = ""
    
    if tool == "read_file":
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                if "content" in parsed and "path" in parsed:
                    data = parsed
                    content = parsed["content"]
                    file_path = parsed["path"]
                elif "name" in parsed and "dependencies" in parsed:
                    content = result
                    file_path = "package.json"
                else:
                    content = result
                    file_path = ""
            else:
                content = result
                file_path = ""
        except json.JSONDecodeError:
            content = result
            file_path = ""
        
        logger.info(f"read_file 解析: content_length={len(str(content))}, file_path={file_path}")
        
        file_name = Path(file_path).name if file_path else ""
        
        # ── 配置文件识别（按项目类型）──
        if file_name == "package.json" or (isinstance(content, str) and '"dependencies"' in content and '"name"' in content):
            try:
                pkg_data = json.loads(content) if isinstance(content, str) else content
                state.package_found = True
                state.results["package_info"] = pkg_data
                logger.info(f"已更新 package_info (node): name={pkg_data.get('name', 'unknown')}")
            except json.JSONDecodeError as e:
                logger.warning(f"解析 package.json 失败: {e}")
        elif file_name in ["pyproject.toml", "requirements.txt", "setup.py", "setup.cfg"]:
            # Python 项目配置文件
            state.package_found = True
            state.results["package_info"] = {
                "type": "python",
                "file": file_name,
                "content": content[:3000] if isinstance(content, str) else str(content),
            }
            logger.info(f"已更新 package_info (python): {file_name}")
        elif file_name in ["go.mod", "go.sum"]:
            state.package_found = True
            state.results["package_info"] = {
                "type": "go",
                "file": file_name,
                "content": content[:2000] if isinstance(content, str) else str(content),
            }
            logger.info(f"已更新 package_info (go): {file_name}")
        elif file_name in ["pom.xml", "build.gradle", "build.gradle.kts"]:
            state.package_found = True
            state.results["package_info"] = {
                "type": "java",
                "file": file_name,
                "content": content[:3000] if isinstance(content, str) else str(content),
            }
            logger.info(f"已更新 package_info (java): {file_name}")
        elif file_name in ["Cargo.toml"]:
            state.package_found = True
            state.results["package_info"] = {
                "type": "rust",
                "file": file_name,
                "content": content[:2000] if isinstance(content, str) else str(content),
            }
            logger.info(f"已更新 package_info (rust): {file_name}")
        elif file_name in ["main.js", "main.ts", "index.js", "index.ts",
                           "__init__.py", "__main__.py", "main.py", "app.py",
                           "main.go", "main.rs", "lib.rs"]:
            state.entry_found = True
            state.results["entry_info"] = {
                "path": file_path,
                "content": content[:2000] if isinstance(content, str) else str(content),
            }
            logger.info(f"已更新 entry_info: {file_path}")
        elif file_name in ["vue.config.js", "vite.config.js", "vite.config.ts",
                           ".env", "Dockerfile", "docker-compose.yml",
                           "Makefile", "tox.ini", ".flake8", "ruff.toml"]:
            state.config_found = True
            state.results["config_info"] = {
                "path": file_path,
                "content": content[:1000] if isinstance(content, str) else str(content),
            }
            logger.info(f"已更新 config_info: {file_path}")
        elif file_name.endswith((".vue", ".tsx", ".jsx")) or (
            state.project_type == "python" and file_name.endswith(".py")
        ) or (
            state.project_type in ("go", "java", "rust") and
            file_name.endswith((".go", ".java", ".rs"))
        ):
            if "pages_content" not in state.results:
                state.results["pages_content"] = []
            try:
                rel_path = str(Path(file_path).relative_to(Path(state.project_path))).replace("\\", "/")
            except ValueError:
                rel_path = file_path
            state.results["pages_content"].append({
                "path": rel_path,
                "file": file_name,
                "content": content[:MAX_FILE_CONTENT_LENGTH] if isinstance(content, str) else str(content),
            })
            logger.info(f"已保存源文件内容: {rel_path}")
        elif file_name == "README.md" or file_name == "README.rst":
            state.results["readme_info"] = {
                "path": file_path,
                "content": content[:2000] if isinstance(content, str) else str(content),
            }
            logger.info(f"已保存 README: {file_path}")
        else:
            # 其他文件也保存内容，不丢弃
            if "pages_content" not in state.results:
                state.results["pages_content"] = []
            try:
                rel_path = str(Path(file_path).relative_to(Path(state.project_path))).replace("\\", "/")
            except (ValueError, Exception):
                rel_path = file_path
            state.results["pages_content"].append({
                "path": rel_path,
                "file": file_name,
                "content": content[:MAX_FILE_CONTENT_LENGTH] if isinstance(content, str) else str(content),
            })
            logger.info(f"已保存其他文件内容: {rel_path}")
        
        return state
    
    try:
        data = json.loads(result) if isinstance(result, str) else result
    except json.JSONDecodeError:
        logger.warning(f"JSON解析失败，使用原始结果: {str(result)[:200]}")
        data = {"raw": result}
    
    logger.info(f"解析后数据: type={type(data).__name__}, keys={list(data.keys()) if isinstance(data, dict) else 'not dict'}")

    if tool == "list_dir":
        path = ""
        items = []
        dirs = []
        files = []
        
        if isinstance(data, dict):
            path = data.get("path", "")
            items = data.get("items", [])
            dirs = data.get("dirs", [])
            files = data.get("files", [])
        
        # 统一路径比较：使用正斜杠 + 小写，兼容 macOS/Linux/Windows
        def _norm(p: str) -> str:
            return str(Path(p).resolve()).replace("\\", "/").lower() if p else ""
        
        path_norm = _norm(path)
        project_root_norm = _norm(state.project_path)
        
        logger.info(f"list_dir: path={path}, project_root={state.project_path}, has_dirs={len(dirs)>0}, has_items={len(items)>0}")
        
        if path_norm == project_root_norm:
            state.structure_found = True
            state.results["root_structure"] = data
            logger.info(f"已更新 root_structure: dirs={dirs}")
        else:
            # 计算相对于项目根的路径部分
            try:
                rel = str(Path(path).resolve().relative_to(Path(state.project_path).resolve())).replace("\\", "/").lower()
            except ValueError:
                rel = ""
            
            # 源码主目录匹配
            if rel in ["src", "app", "lib", state.project_type if state.project_type != "generic" else ""]:
                # 检查是否是项目的主要源码包目录
                if not state.src_scanned:
                    state.src_scanned = True
                    state.results["src_structure"] = data
                    logger.info(f"已更新 src_structure (main): dirs={dirs}")
            elif rel.startswith("src/") or rel.startswith("app/"):
                # src 下的子目录
                sub = rel.split("/", 1)[-1] if "/" in rel else ""
                if "views" in sub or "pages" in sub or "screens" in sub:
                    state.views_found = True
                    state.results["views_info"] = data
                    logger.info(f"已更新 views_info: items={len(items)}, dirs={len(dirs)}")
                elif "store" in sub or "stores" in sub or "state" in sub:
                    state.store_found = True
                    state.results["store_info"] = data
                    logger.info(f"已更新 store_info")
                elif "api" in sub or "services" in sub or "http" in sub:
                    state.api_found = True
                    state.results["api_info"] = data
                    logger.info(f"已更新 api_info")
            else:
                # Python/Go/Java 等项目：任意子目录都算 src 扫描
                if not state.src_scanned and (dirs or items):
                    state.src_scanned = True
                    state.results[f"dir_{rel.replace('/', '_')}"] = data
                    logger.info(f"已保存子目录结构: {rel}, dirs={dirs}")

    elif tool == "scan_menu_structure":
        state.router_found = True
        state.results["menu_info"] = data
        if isinstance(data, dict) and data.get("router", {}).get("files"):
            state.results["router_info"] = data["router"]
        logger.info(f"已更新 menu_info: routes={data.get('extracted_routes', [])[:5] if isinstance(data, dict) else []}")

    return state


def _generate_project_summary(state: ProjectAnalysisState, knowledge: dict = None) -> str:
    """生成项目分析报告（支持多项目类型）"""
    info = state.results
    project_type = state.project_type

    sections = ["# 项目分析报告"]

    # ── 项目概览（按类型）──
    pkg = info.get("package_info", {})
    if pkg:
        if project_type == "node" and isinstance(pkg, dict) and "dependencies" in pkg:
            # Node 项目
            name = pkg.get("name", "未知项目")
            version = pkg.get("version", "未知版本")
            deps = pkg.get("dependencies", {})
            dev_deps = pkg.get("devDependencies", {})
            framework = router = state_mgmt = ui = "未知"
            if "vue" in deps:
                framework = f"Vue {deps['vue']}"
                if "vue-router" in deps: router = f"Vue Router {deps['vue-router']}"
                if "vuex" in deps: state_mgmt = f"Vuex {deps['vuex']}"
                if "element-ui" in deps: ui = "Element UI"
                elif "@element-plus" in deps: ui = "Element Plus"
            elif "react" in deps:
                framework = f"React {deps['react']}"
                if "react-router" in deps or "react-router-dom" in deps: router = "React Router"
                if "redux" in deps: state_mgmt = "Redux"
                if "@mui" in deps: ui = "Material UI"
            sections.append(
                f"## 项目概览\n- 名称: {name}\n- 版本: {version}\n- 类型: Node.js 前端\n"
                f"- 框架: {framework}\n- 路由: {router}\n- 状态管理: {state_mgmt}\n- UI框架: {ui}"
            )
            all_deps = {**deps, **dev_deps}
            if all_deps:
                dep_list = ", ".join([f"{k}@{v}" for k, v in list(all_deps.items())[:15]])
                if len(all_deps) > 15: dep_list += f"... (共 {len(all_deps)} 个依赖)"
                sections.append(f"## 主要依赖\n{dep_list}")
        elif project_type == "python":
            content = pkg.get("content", "") if isinstance(pkg, dict) else str(pkg)
            # 从 pyproject.toml 提取名称和版本
            import re as _re
            name_m = _re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
            ver_m = _re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            desc_m = _re.search(r'description\s*=\s*["\']([^"\']+)["\']', content)
            name = name_m.group(1) if name_m else "未知项目"
            version = ver_m.group(1) if ver_m else "未知版本"
            desc = desc_m.group(1) if desc_m else ""
            framework = "Python"
            for fw in ["Flask", "Django", "FastAPI", "Tornado", "Starlette", "Typer"]:
                if fw.lower() in content.lower():
                    framework = fw
                    break
            sections.append(
                f"## 项目概览\n- 名称: {name}\n- 版本: {version}\n- 类型: Python\n"
                f"- 框架: {framework}"
            )
            if desc:
                sections.append(f"- 描述: {desc}")
        elif project_type == "go":
            content = pkg.get("content", "") if isinstance(pkg, dict) else str(pkg)
            import re as _re
            mod_m = _re.search(r'module\s+(\S+)', content)
            go_m = _re.search(r'go\s+(\S+)', content)
            mod = mod_m.group(1) if mod_m else "未知模块"
            go_ver = go_m.group(1) if go_m else "未知版本"
            sections.append(
                f"## 项目概览\n- 模块: {mod}\n- Go 版本: {go_ver}\n- 类型: Go"
            )
        elif project_type == "rust":
            content = pkg.get("content", "") if isinstance(pkg, dict) else str(pkg)
            import re as _re
            name_m = _re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
            ver_m = _re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            name = name_m.group(1) if name_m else "未知项目"
            version = ver_m.group(1) if ver_m else "未知版本"
            sections.append(
                f"## 项目概览\n- 名称: {name}\n- 版本: {version}\n- 类型: Rust\n- 构建: Cargo"
            )
        elif project_type == "java":
            content = pkg.get("content", "") if isinstance(pkg, dict) else str(pkg)
            framework = "Java"
            if "spring" in content.lower(): framework = "Spring Boot"
            elif "maven" in content.lower(): framework = "Maven"
            sections.append(
                f"## 项目概览\n- 类型: Java\n- 框架: {framework}"
            )
        else:
            sections.append(f"## 项目概览\n- 类型: {project_type}")

    # ── 入口文件 ──
    if info.get("entry_info"):
        entry = info["entry_info"]
        sections.append(f"## 入口文件\n- 路径: {entry.get('path', '未知')}")

    # ── 根目录结构 ──
    if info.get("root_structure"):
        struct = info["root_structure"]
        if isinstance(struct, dict):
            dirs = struct.get("dirs", [])
            files = [f.get("name", f) if isinstance(f, dict) else f for f in struct.get("files", [])]
            items = struct.get("items", [])
            if items:
                dirs = [item["name"] for item in items if item.get("type") == "directory"]
                files = [item["name"] for item in items if item.get("type") == "file"]
        else:
            dirs, files = [], []
        if dirs:
            sections.append(f"## 根目录结构\n- 目录: {', '.join(dirs)}")
        if files:
            sections.append(f"## 根目录文件\n- 文件: {', '.join(files[:10])}")

    # ── 源码目录结构 ──
    if info.get("src_structure"):
        src = info["src_structure"]
        if isinstance(src, dict):
            src_dirs = src.get("dirs", [])
            if src_dirs:
                sections.append(f"## 源码目录结构\n- 子目录: {', '.join(src_dirs)}")

    # ── 业务页面/模块 ──
    if info.get("views_info"):
        views = info["views_info"]
        if isinstance(views, dict):
            views_dirs = views.get("dirs", [])
            items = views.get("items", [])
            if items:
                views_dirs = [item["name"] for item in items if item.get("type") == "directory"]
            if views_dirs:
                sections.append(f"## 业务页面模块\n- 模块: {', '.join(views_dirs[:15])}")

    # ── 路由（仅 Node 项目）──
    if info.get("menu_info") and project_type == "node":
        menu = info["menu_info"]
        routes = menu.get("extracted_routes", [])
        routers = menu.get("router", {}).get("files", [])
        if routers:
            is_dynamic = menu.get("router", {}).get("dynamic", False)
            sections.append(f"## 路由配置\n- 文件: {', '.join(routers)}\n- 动态路由: {'是' if is_dynamic else '否'}")
        if routes:
            route_list = "\n".join([f"- {r}" for r in routes[:20]])
            if len(routes) > 20: route_list += f"\n... (共 {len(routes)} 条路由)"
            sections.append(f"## 页面路由\n{route_list}")

    # ── 状态管理 ──
    if info.get("store_info"):
        store = info["store_info"]
        if isinstance(store, dict):
            store_dirs = store.get("dirs", [])
            items = store.get("items", [])
            if items:
                store_dirs = [item["name"] for item in items if item.get("type") == "directory"]
            if store_dirs:
                sections.append(f"## 状态管理\n- 模块: {', '.join(store_dirs)}")

    # ── API 接口 ──
    if info.get("api_info"):
        api = info["api_info"]
        if isinstance(api, dict):
            api_files = [f.get("name", f) if isinstance(f, dict) else f for f in api.get("files", [])]
            items = api.get("items", [])
            if items:
                api_files = [item["name"] for item in items if item.get("type") == "file"]
            if api_files:
                sections.append(f"## API 接口\n- 文件: {', '.join(api_files[:20])}")

    # ── 已分析的源文件 ──
    pages_content = info.get("pages_content", [])
    if pages_content:
        file_list = [p.get("path", p.get("file", "")) for p in pages_content[:30]]
        sections.append(f"## 已分析源文件 ({len(pages_content)} 个)\n" + "\n".join([f"- {f}" for f in file_list]))

    # ── README 摘要 ──
    if info.get("readme_info"):
        readme_content = info["readme_info"].get("content", "")
        if readme_content:
            # 取前 500 字符作为摘要
            sections.append(f"## README 摘要\n{readme_content[:500]}")

    # ── 业务能力分析（如果有 knowledge）──
    if knowledge:
        code_understanding_service = CodeUnderstandingService()
        business_summary = code_understanding_service.summarize_business_capabilities(knowledge)
        sections.append(f"\n{business_summary}")

    if not sections:
        return f"未找到项目 {state.project_path} 的有效信息"

    return "\n\n".join(sections)


def is_project_scan_query(query: str) -> bool:
    """判断是否为项目扫描请求
    
    关键词：扫描项目、分析项目、查看项目、项目结构、项目信息等
    """
    keywords = [
        "扫描项目", "分析项目", "查看项目", "项目结构", "项目信息",
        "scan project", "analyze project", "project structure",
        "项目内容", "了解项目", "项目概览", "项目报告",
        "理解项目", "为后续修改代码", "项目分析", "代码分析", "分析代码",
        "项目架构", "技术栈", "项目理解",
        "扫描代码", "查看代码", "代码结构", "功能分析", "需求分析",
        "结合代码", "结合项目"
    ]
    return any(kw in query for kw in keywords)


def extract_project_path(query: str) -> str:
    """从查询中提取项目路径

    支持：
    - macOS/Linux: /Users/xxx/Documents/xxx, /home/xxx/xxx
    - Windows: D:\\projects\\xxx, D:/projects/xxx
    - 通用绝对路径: /任意/路径/xxx
    - ~/xxx 形式

    自动清理路径末尾的非路径字符（如 )`\"'等）
    """
    import re

    # 路径中不允许出现的字符（用于截断）
    bad_chars = r"')`\]}>;,!？。、，"

    patterns = [
        # macOS/Linux 绝对路径: /开头的任意路径
        r"(/(?:Users|home|opt|usr|var|tmp|srv)/[^\s'" + re.escape(bad_chars) + r"]+)",
        # 通用绝对路径: /开头
        r"(/[a-zA-Z][^\s'" + re.escape(bad_chars) + r"]+)",
        # Windows 路径
        r"([A-Za-z]:\\[^\s'" + re.escape(bad_chars) + r"]+)",
        r"([A-Za-z]:/[^\s'" + re.escape(bad_chars) + r"]+)",
        # ~/ 开头
        r"(~/[^\s'" + re.escape(bad_chars) + r"]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, query)
        if match:
            path = match.group(1)
            # 清理末尾可能残留的标点
            path = path.rstrip(".,;:!?）)】】\"'")
            return path

    return ""