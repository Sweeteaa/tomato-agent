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
  10. save knowledge → 持久化到 workspace/projects/

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
  - workspace/projects/项目名/project.json → 项目元信息
  - workspace/projects/项目名/routes.json → 路由信息
  - workspace/projects/项目名/api.json → API 接口信息
  - workspace/projects/项目名/knowledge.json → 项目知识模型
  - workspace/projects/项目名/business_capabilities.md → 业务能力总结
  - workspace/projects/项目名/architecture.md → 架构文档
"""

import json
import logging
import asyncio
import os
from pathlib import Path
from typing import Literal

from agent.core.state import AgentState
from agent.registry.capability_registry import CapabilityRegistry
from agent.tools.filesystem import list_dir, read_file, search_file, scan_menu_structure
from agent.tools.project import project_discover
from app.config import WORKSPACE
from app.services.code_understanding_service import CodeUnderstandingService

logger = logging.getLogger("gt_agent.workflows.project_scan")

MAX_SCAN_STEPS = 15
TOOL_TIMEOUT = 30


def get_project_knowledge_dir(project_name: str) -> Path:
    """获取项目知识库目录"""
    return WORKSPACE / "projects" / project_name


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


class ProjectAnalysisState:
    """项目分析状态机 — 三阶段流水线"""

    # 阶段定义
    PHASE_PROFILE = "profile"      # 阶段1: 项目画像
    PHASE_ARCHITECTURE = "architecture"  # 阶段2: 架构扫描
    PHASE_BUSINESS = "business"    # 阶段3: 业务理解
    PHASE_ANALYSIS = "analysis"    # 阶段4: 代码理解
    PHASE_DONE = "done"

    def __init__(self, project_path: str):
        self.project_path = project_path
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
        """检查是否完成扫描（收敛条件）— 必须完成代码理解步骤"""
        core_items = [
            self.structure_found,
            self.package_found,
            self.router_found,
        ]
        secondary_items = [
            self.entry_found,
            self.store_found,
            self.api_found,
            self.src_scanned,
        ]
        core_done = all(core_items)
        secondary_done = sum(secondary_items) >= 2
        analysis_done = self.pages_analyzed
        return (core_done and secondary_done and analysis_done) or self.summary_ready

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
        """根据当前状态决定下一步动作 — 三阶段流水线"""
        self.step += 1

        if self.summary_ready:
            return {"tool": "finish", "args": {}}

        # ── 阶段1: 项目画像 ──
        if self.phase == self.PHASE_PROFILE:
            if not self.structure_found:
                return {"tool": "list_dir", "args": {"path": self.project_path, "recursive": False, "max_depth": 2}}

            if not self.package_found:
                pkg_path = str(Path(self.project_path) / "package.json")
                if Path(pkg_path).exists():
                    return {"tool": "read_file", "args": {"path": pkg_path}}

            if not self.config_found:
                for config_name in ["vue.config.js", "vite.config.js", "vite.config.ts", ".env"]:
                    config_path = str(Path(self.project_path) / config_name)
                    if Path(config_path).exists():
                        return {"tool": "read_file", "args": {"path": config_path, "start_line": 1, "end_line": 50}}

            # 阶段1完成，进入阶段2
            self.phase = self.PHASE_ARCHITECTURE

        # ── 阶段2: 架构扫描 ──
        if self.phase == self.PHASE_ARCHITECTURE:
            if not self.src_scanned:
                src_dir = str(Path(self.project_path) / "src")
                if Path(src_dir).exists():
                    return {"tool": "list_dir", "args": {"path": src_dir, "recursive": False, "max_depth": 1}}

            if not self.entry_found:
                for entry_name in ["src/main.js", "src/main.ts", "src/index.js", "src/index.ts"]:
                    entry_path = str(Path(self.project_path) / entry_name)
                    if Path(entry_path).exists():
                        return {"tool": "read_file", "args": {"path": entry_path, "start_line": 1, "end_line": 50}}

            if not self.router_found:
                return {"tool": "scan_menu_structure", "args": {"project_path": self.project_path}}

            # 阶段2完成，进入阶段3
            self.phase = self.PHASE_BUSINESS

        # ── 阶段3: 业务理解 ──
        if self.phase == self.PHASE_BUSINESS:
            if not self.views_found:
                views_dir = str(Path(self.project_path) / "src" / "views")
                if Path(views_dir).exists():
                    return {"tool": "list_dir", "args": {"path": views_dir, "recursive": True, "max_depth": 5}}
                pages_dir = str(Path(self.project_path) / "src" / "pages")
                if Path(pages_dir).exists():
                    return {"tool": "list_dir", "args": {"path": pages_dir, "recursive": True, "max_depth": 5}}

            if not self.store_found:
                store_dir = str(Path(self.project_path) / "src" / "store")
                if Path(store_dir).exists():
                    return {"tool": "list_dir", "args": {"path": store_dir, "recursive": True, "max_depth": 2}}

            if not self.api_found:
                api_dir = str(Path(self.project_path) / "src" / "api")
                if Path(api_dir).exists():
                    return {"tool": "list_dir", "args": {"path": api_dir, "recursive": True, "max_depth": 2}}
                http_dir = str(Path(self.project_path) / "src" / "http")
                if Path(http_dir).exists():
                    return {"tool": "list_dir", "args": {"path": http_dir, "recursive": True, "max_depth": 2}}
                services_dir = str(Path(self.project_path) / "src" / "services")
                if Path(services_dir).exists():
                    return {"tool": "list_dir", "args": {"path": services_dir, "recursive": True, "max_depth": 2}}

            self.phase = self.PHASE_ANALYSIS

        # ── 阶段4: 代码理解（读取页面文件内容）──
        if self.phase == self.PHASE_ANALYSIS:
            if not hasattr(self, "_pages_list_initialized"):
                pages_to_read = []
                views_info = self.results.get("views_info", {})
                if isinstance(views_info, dict):
                    items = views_info.get("items", [])
                    pages_to_read = self._collect_page_files_recursive(items)
                
                self.results["pages_to_analyze"] = pages_to_read
                self.current_page_index = 0
                self._pages_list_initialized = True
            
            pages_to_read = self.results.get("pages_to_analyze", [])
            
            if self.current_page_index < len(pages_to_read):
                page_path = pages_to_read[self.current_page_index]
                if not page_path.startswith("D:") and not page_path.startswith("/"):
                    page_path = str(Path(self.project_path) / page_path)
                current_idx = self.current_page_index
                self.current_page_index += 1
                return {"tool": "read_file", "args": {"path": page_path}}
            else:
                self.pages_analyzed = True
                return {"tool": "analyze_code", "args": {}}

        return {"tool": "finish", "args": {}}


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
    knowledge_json_path = WORKSPACE / "projects" / project_name / "knowledge.json"
    project_json_path = WORKSPACE / "projects" / project_name / "project.json"
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
    
    analysis_state = ProjectAnalysisState(project_path)
    
    yield {"type": "status", "message": f"开始扫描项目: {project_path}"}
    
    code_understanding_service = CodeUnderstandingService()
    knowledge = None
    
    MAX_SCAN_STEPS = 50
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
    yield {"type": "status", "message": f"项目知识已保存到 workspace/projects/{project_name}/"}
    
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
    """构建用于代码理解的扫描结构"""
    results = analysis_state.results
    package_info = results.get("package_info", {})
    project_path_obj = Path(project_path)
    
    structure = {
        "project": project_path_obj.name,
        "root_path": project_path,
        "framework": "",
        "build_tool": "",
        "package_manager": "",
        "dev_command": "",
        "src_dir": "src",
        "ui_libraries": [],
        "pages": [],
        "components": [],
        "api_modules": [],
        "router": {"files": [], "routes": []},
        "scanned_at": "",
    }
    
    deps = package_info.get("dependencies", {})
    if "vue" in deps:
        structure["framework"] = f"Vue {deps['vue']}"
    elif "react" in deps:
        structure["framework"] = f"React {deps['react']}"
    
    ui_libs = []
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
        
        if file_name == "package.json" or (isinstance(content, str) and '"dependencies"' in content and '"name"' in content):
            try:
                pkg_data = json.loads(content) if isinstance(content, str) else content
                state.package_found = True
                state.results["package_info"] = pkg_data
                logger.info(f"已更新 package_info: name={pkg_data.get('name', 'unknown')}")
            except json.JSONDecodeError as e:
                logger.warning(f"解析 package.json 失败: {e}")
        elif file_name in ["main.js", "main.ts", "index.js", "index.ts"]:
            state.entry_found = True
            state.results["entry_info"] = {
                "path": file_path,
                "content": content[:2000] if isinstance(content, str) else str(content),
            }
            logger.info(f"已更新 entry_info: {file_path}")
        elif file_name in ["vue.config.js", "vite.config.js", "vite.config.ts", ".env"]:
            state.config_found = True
            state.results["config_info"] = {
                "path": file_path,
                "content": content[:1000] if isinstance(content, str) else str(content),
            }
            logger.info(f"已更新 config_info: {file_path}")
        elif file_name.endswith((".vue", ".tsx", ".jsx")):
            if "pages_content" not in state.results:
                state.results["pages_content"] = []
            rel_path = str(Path(file_path).relative_to(Path(state.project_path))).replace("\\", "/")
            state.results["pages_content"].append({
                "path": rel_path,
                "file": file_name,
                "content": content[:5000] if isinstance(content, str) else str(content),
            })
            logger.info(f"已保存页面内容: {rel_path}")
        else:
            logger.warning(f"未识别的文件类型: {file_name}")
        
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
        
        path_lower = path.lower() if isinstance(path, str) else ""
        project_root = str(Path(state.project_path).resolve()).lower()
        project_root_with_sep = project_root + "\\"
        
        logger.info(f"list_dir: path={path}, project_root={project_root}, has_dirs={len(dirs)>0}, has_items={len(items)>0}")
        
        if path_lower == project_root:
            state.structure_found = True
            state.results["root_structure"] = data
            logger.info(f"已更新 root_structure: dirs={dirs}")
        elif path_lower == project_root_with_sep + "src" or (project_root_with_sep in path_lower and path_lower.endswith("\\src")):
            state.src_scanned = True
            state.results["src_structure"] = data
            logger.info(f"已更新 src_structure: dirs={dirs}")
        elif project_root_with_sep in path_lower and "src" in path_lower and ("views" in path_lower or "pages" in path_lower):
            state.views_found = True
            state.results["views_info"] = data
            logger.info(f"已更新 views_info: items={len(items)}, dirs={len(dirs)}")
        elif project_root_with_sep in path_lower and "src" in path_lower and "store" in path_lower:
            state.store_found = True
            state.results["store_info"] = data
            logger.info(f"已更新 store_info")
        elif project_root_with_sep in path_lower and "src" in path_lower and ("api" in path_lower or "services" in path_lower or "http" in path_lower):
            state.api_found = True
            state.results["api_info"] = data
            logger.info(f"已更新 api_info")

    elif tool == "scan_menu_structure":
        state.router_found = True
        state.results["menu_info"] = data
        if isinstance(data, dict) and data.get("router", {}).get("files"):
            state.results["router_info"] = data["router"]
        logger.info(f"已更新 menu_info: routes={data.get('extracted_routes', [])[:5] if isinstance(data, dict) else []}")

    return state


def _generate_project_summary(state: ProjectAnalysisState, knowledge: dict = None) -> str:
    """生成项目分析报告"""
    info = state.results

    sections = ["# 项目分析报告"]

    if info.get("package_info"):
        pkg = info["package_info"]
        name = pkg.get("name", "未知项目")
        version = pkg.get("version", "未知版本")
        deps = pkg.get("dependencies", {})
        dev_deps = pkg.get("devDependencies", {})

        framework = "未知"
        router = "未知"
        state_mgmt = "未知"
        ui = "未知"

        if "vue" in deps:
            framework = f"Vue {deps['vue']}"
            if "vue-router" in deps:
                router = f"Vue Router {deps['vue-router']}"
            if "vuex" in deps:
                state_mgmt = f"Vuex {deps['vuex']}"
            if "element-ui" in deps:
                ui = "Element UI"
            elif "@element-plus" in deps:
                ui = "Element Plus"
        elif "react" in deps:
            framework = f"React {deps['react']}"
            if "react-router" in deps or "react-router-dom" in deps:
                router = "React Router"
            if "redux" in deps:
                state_mgmt = "Redux"
            if "@mui" in deps:
                ui = "Material UI"

        sections.append(f"## 项目概览\n- 名称: {name}\n- 版本: {version}\n- 框架: {framework}\n- 路由: {router}\n- 状态管理: {state_mgmt}\n- UI框架: {ui}")

        all_deps = {**deps, **dev_deps}
        if all_deps:
            dep_list = ", ".join([f"{k}@{v}" for k, v in list(all_deps.items())[:15]])
            if len(all_deps) > 15:
                dep_list += f"... (共 {len(all_deps)} 个依赖)"
            sections.append(f"## 主要依赖\n{dep_list}")

    if info.get("entry_info"):
        entry = info["entry_info"]
        sections.append(f"## 入口文件\n- 路径: {entry.get('path', '未知')}")

    if info.get("root_structure"):
        struct = info["root_structure"]
        # 兼容新旧格式
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

    if info.get("src_structure"):
        src = info["src_structure"]
        if isinstance(src, dict):
            src_dirs = src.get("dirs", [])
            if src_dirs:
                sections.append(f"## src 目录结构\n- 子目录: {', '.join(src_dirs)}")

    if info.get("views_info"):
        views = info["views_info"]
        if isinstance(views, dict):
            views_dirs = views.get("dirs", [])
            views_files = [f.get("name", f) if isinstance(f, dict) else f for f in views.get("files", [])]
            items = views.get("items", [])
            if items:
                views_dirs = [item["name"] for item in items if item.get("type") == "directory"]
                views_files = [item["name"] for item in items if item.get("type") == "file"]
            if views_dirs:
                sections.append(f"## 业务页面模块\n- 模块: {', '.join(views_dirs[:15])}")
            if views_files:
                sections.append(f"## 页面文件\n- 文件: {', '.join(views_files[:10])}")

    if info.get("menu_info"):
        menu = info["menu_info"]
        routes = menu.get("extracted_routes", [])
        routers = menu.get("router", {}).get("files", [])
        menus = menu.get("menu", {}).get("files", [])
        is_dynamic = menu.get("router", {}).get("dynamic", False)

        if routers:
            sections.append(f"## 路由配置\n- 文件: {', '.join(routers)}\n- 动态路由: {'是' if is_dynamic else '否'}")
        if routes:
            route_list = "\n".join([f"- {r}" for r in routes[:20]])
            if len(routes) > 20:
                route_list += f"\n... (共 {len(routes)} 条路由)"
            sections.append(f"## 页面路由\n{route_list}")
        if menus:
            sections.append(f"## 菜单组件\n{', '.join(menus)}")

    if info.get("store_info"):
        store = info["store_info"]
        if isinstance(store, dict):
            store_dirs = store.get("dirs", [])
            store_files = [f.get("name", f) if isinstance(f, dict) else f for f in store.get("files", [])]
            items = store.get("items", [])
            if items:
                store_dirs = [item["name"] for item in items if item.get("type") == "directory"]
                store_files = [item["name"] for item in items if item.get("type") == "file"]
            if store_dirs:
                sections.append(f"## 状态管理\n- 模块: {', '.join(store_dirs)}")
            if store_files:
                sections.append(f"## Store 文件\n- 文件: {', '.join(store_files)}")

    if info.get("api_info"):
        api = info["api_info"]
        if isinstance(api, dict):
            api_dirs = api.get("dirs", [])
            api_files = [f.get("name", f) if isinstance(f, dict) else f for f in api.get("files", [])]
            items = api.get("items", [])
            if items:
                api_dirs = [item["name"] for item in items if item.get("type") == "directory"]
                api_files = [item["name"] for item in items if item.get("type") == "file"]
            if api_files:
                sections.append(f"## API 接口\n- 文件: {', '.join(api_files[:20])}")

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
    - Windows: D:\\projects\\xxx
    - Windows: D:/projects/xxx
    - macOS/Linux: /projects/xxx
    - macOS/Linux: ~/projects/xxx

    自动清理路径末尾的非路径字符（如 )`"'等）
    """
    import re

    # 路径中不允许出现的字符（用于截断）
    bad_chars = r"')`\]}>;,!？。、，"

    patterns = [
        r"(D:\\projects\\[^\s'" + re.escape(bad_chars) + r"]+)",
        r"(D:/projects/[^/\s'" + re.escape(bad_chars) + r"]+)",
        r"(/projects/[^/\s'" + re.escape(bad_chars) + r"]+)",
        r"(~/projects/[^/\s'" + re.escape(bad_chars) + r"]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, query)
        if match:
            path = match.group(1)
            # 清理末尾可能残留的标点
            path = path.rstrip(".,;:!?）)】】\"'")
            return path

    return ""