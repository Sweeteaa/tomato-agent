import json
import re
from pathlib import Path
from typing import List, Dict, Any

import logging

logger = logging.getLogger("gt_agent.code_understanding")


class VueFileAnalyzer:
    def __init__(self):
        self._business_keywords = {
            "患者": ["patient", "patientId", "patient_id", "患者", "姓名", "年龄", "性别"],
            "病灶": ["lesion", "focus", "病灶", "结节", "肿块"],
            "造影": ["ceus", "contrast", "造影", "增强", "Sonazoid"],
            "治疗": ["treatment", "therapy", "治疗", "化疗", "手术"],
            "随访": ["follow", "随访", "复查"],
            "实验室": ["lab", "laboratory", "实验室", "检查", "检验"],
            "数据": ["dashboard", "data", "统计", "看板"],
            "表单": ["form", "表单", "录入", "填写"],
            "AE": ["ae", "adverse", "不良", "事件"],
            "研究": ["study", "research", "研究", "trial"],
        }

        self._component_keywords = {
            "element-ui": ["el-", "ElementUI", "element-ui"],
            "ant-design": ["a-", "Ant", "ant-design"],
            "vant": ["van-", "Vant"],
        }

    def analyze_vue_file(self, file_path: str, content: str) -> Dict[str, Any]:
        file_name = Path(file_path).name
        relative_path = file_path

        analysis = {
            "file": file_name,
            "relative_path": relative_path,
            "type": self._detect_file_type(file_name, content),
            "business": "",
            "features": [],
            "dependencies": [],
            "related_api": [],
            "imports": [],
            "data_fields": [],
            "methods": [],
            "components": [],
            "routes": [],
        }

        template_features = self._analyze_template(content)
        script_features = self._analyze_script(content)

        analysis["features"] = list(set(template_features + script_features["features"]))
        analysis["dependencies"] = script_features["dependencies"]
        analysis["related_api"] = script_features["api_calls"]
        analysis["imports"] = script_features["imports"]
        analysis["data_fields"] = script_features["data_fields"]
        analysis["methods"] = script_features["methods"]
        analysis["components"] = script_features["components"]
        analysis["routes"] = script_features["routes"]
        analysis["business"] = self._infer_business_purpose(analysis)

        return analysis

    def _detect_file_type(self, file_name: str, content: str) -> str:
        if file_name.endswith(".vue"):
            if "router-view" in content or "router-link" in content:
                return "layout_page"
            elif any(keyword in content.lower() for keyword in ["form", "表单", "录入"]):
                return "form_page"
            elif any(keyword in content.lower() for keyword in ["table", "list", "列表", "数据"]):
                return "list_page"
            elif any(keyword in content.lower() for keyword in ["chart", "graph", "统计", "看板"]):
                return "dashboard_page"
            else:
                return "vue_page"
        elif file_name.endswith((".js", ".ts")):
            if "/api/" in file_name or "api" in file_name.lower():
                return "api_module"
            elif "/store/" in file_name or "/stores/" in file_name:
                return "store_module"
            elif "/router/" in file_name:
                return "router_module"
            else:
                return "script_file"
        else:
            return "other"

    def _analyze_template(self, content: str) -> List[str]:
        features = []
        template_match = re.search(r"<template[^>]*>(.*?)</template>", content, re.DOTALL)
        if not template_match:
            return features

        template_content = template_match.group(1)

        form_patterns = [
            (r"<el-input[^>]*>", "输入框"),
            (r"<el-select[^>]*>", "下拉选择"),
            (r"<el-date-picker[^>]*>", "日期选择"),
            (r"<el-radio[^>]*>", "单选框"),
            (r"<el-checkbox[^>]*>", "复选框"),
            (r"<el-form[^>]*>", "表单"),
            (r"<el-table[^>]*>", "表格"),
            (r"<el-button[^>]*>", "按钮"),
            (r"<el-dialog[^>]*>", "弹窗"),
            (r"<el-message[^>]*>", "消息提示"),
            (r"<router-link[^>]*>", "路由链接"),
        ]

        for pattern, feature_name in form_patterns:
            if re.search(pattern, template_content):
                features.append(feature_name)

        label_pattern = r"<el-form-item[^>]*label\s*=\s*['\"]([^'\"]+)['\"]"
        labels = re.findall(label_pattern, template_content)
        features.extend(labels)

        return features

    def _analyze_script(self, content: str) -> Dict[str, Any]:
        script_match = re.search(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
        if not script_match:
            script_match = re.search(r"<script[^>]*>(.*)", content, re.DOTALL)

        script_content = script_match.group(1) if script_match else content

        result = {
            "features": [],
            "dependencies": [],
            "api_calls": [],
            "imports": [],
            "data_fields": [],
            "methods": [],
            "components": [],
            "routes": [],
        }

        import_pattern = r"import\s+(?:\{[^}]+\}\s+from\s+|(.+?)\s+from\s+)['\"]([^'\"]+)['\"]"
        imports = re.findall(import_pattern, script_content)
        for alias, path in imports:
            result["imports"].append({"alias": alias, "path": path})
            if path.startswith("element-ui") or path.startswith("@element-plus"):
                result["dependencies"].append("element-ui")
            elif path.startswith("vue-router"):
                result["dependencies"].append("vue-router")
            elif path.startswith("vuex"):
                result["dependencies"].append("vuex")
            elif "/api/" in path:
                result["dependencies"].append(path.split("/")[-1].replace(".js", "").replace(".ts", ""))

        api_call_patterns = [
            r"(?:this\.)?(\w+)\s*\(\s*\{?\s*(?:url|path)\s*[=:]\s*['\"]([^'\"]+)['\"]",
            r"(?:this\.)?(\w+)\s*\(\s*['\"]([^'\"]+)['\"]",
            r"axios\.(get|post|put|delete)\s*\(\s*['\"]([^'\"]+)['\"]",
            r"\$http\.(get|post|put|delete)\s*\(\s*['\"]([^'\"]+)['\"]",
        ]

        for pattern in api_call_patterns:
            matches = re.findall(pattern, script_content)
            for method, url in matches:
                if url.startswith("/"):
                    result["api_calls"].append(url)

        data_pattern = r"data\s*\(\s*\)\s*\{?\s*return\s*\{([^}]+)\}"
        data_match = re.search(data_pattern, script_content, re.DOTALL)
        if data_match:
            data_content = data_match.group(1)
            field_pattern = r"(\w+)\s*[:=]"
            fields = re.findall(field_pattern, data_content)
            result["data_fields"] = fields

        method_pattern = r"(?:methods\s*:\s*)?\{([^}]*)\}"
        method_match = re.search(method_pattern, script_content, re.DOTALL)
        if method_match:
            method_content = method_match.group(1)
            func_pattern = r"(\w+)\s*\(\s*[^)]*\s*\)\s*[:=]"
            methods = re.findall(func_pattern, method_content)
            result["methods"] = methods

        component_pattern = r"components\s*:\s*\{([^}]+)\}"
        component_match = re.search(component_pattern, script_content, re.DOTALL)
        if component_match:
            component_content = component_match.group(1)
            comp_pattern = r"(\w+)\s*(?:,\s*)?"
            components = re.findall(comp_pattern, component_content)
            result["components"] = [c for c in components if c.strip() and c != ","]

        route_pattern = r"path\s*[=:]\s*['\"]([^'\"]+)['\"]"
        routes = re.findall(route_pattern, script_content)
        result["routes"] = [r for r in routes if r.startswith("/")]

        for business_key, keywords in self._business_keywords.items():
            if any(kw.lower() in script_content.lower() for kw in keywords):
                result["features"].append(business_key)

        return result

    def _infer_business_purpose(self, analysis: Dict[str, Any]) -> str:
        features = analysis["features"]
        imports = analysis["imports"]

        business_hints = []
        if any("表单" in f for f in features):
            business_hints.append("数据录入")
        if any("表格" in f for f in features):
            business_hints.append("数据展示")
        if any("弹窗" in f for f in features):
            business_hints.append("交互提示")

        for business_key, keywords in self._business_keywords.items():
            if any(kw.lower() in str(features).lower() for kw in keywords):
                business_hints.append(business_key)

        if analysis["type"] == "form_page":
            business_hints.insert(0, "表单页面")
        elif analysis["type"] == "list_page":
            business_hints.insert(0, "列表页面")
        elif analysis["type"] == "dashboard_page":
            business_hints.insert(0, "数据看板")
        elif analysis["type"] == "layout_page":
            business_hints.insert(0, "布局页面")

        return "、".join(list(set(business_hints))) if business_hints else "通用页面"


class CodeUnderstandingService:
    def __init__(self):
        self._vue_analyzer = VueFileAnalyzer()

    def analyze_project_files(self, project_root: str, file_paths: List[str]) -> List[Dict[str, Any]]:
        results = []
        for file_path in file_paths:
            full_path = Path(project_root) / file_path
            if not full_path.exists():
                continue

            try:
                content = full_path.read_text(encoding="utf-8", errors="ignore")
                analysis = self._vue_analyzer.analyze_vue_file(file_path, content)
                results.append(analysis)
            except Exception as e:
                logger.warning(f"分析文件失败: {file_path}, 错误: {e}")
                results.append({
                    "file": file_path,
                    "error": str(e),
                    "type": "error",
                })

        return results

    def build_project_knowledge(self, project_root: str, scan_data: Dict[str, Any], code_index: Dict[str, Any] = None) -> Dict[str, Any]:
        knowledge = {
            "project": scan_data.get("project", ""),
            "root_path": scan_data.get("root_path", ""),
            "framework": scan_data.get("framework", ""),
            "build_tool": scan_data.get("build_tool", ""),
            "package_manager": scan_data.get("package_manager", ""),
            "dev_command": scan_data.get("dev_command", ""),
            "src_dir": scan_data.get("src_dir", ""),
            "ui_libraries": scan_data.get("ui_libraries", []),
            "scanned_at": scan_data.get("scanned_at", ""),
            "pages": [],
            "components": [],
            "api_modules": [],
            "data_flow": [],
        }

        if code_index:
            knowledge["pages"] = self._analyze_pages_from_code_index(code_index.get("pages", []))
            knowledge["components"] = self._analyze_components_from_code_index(code_index.get("components", []))
            knowledge["api_modules"] = self._analyze_api_from_code_index(code_index.get("api_modules", []))
        else:
            pages = scan_data.get("pages", [])
            components = scan_data.get("components", [])
            api_modules = scan_data.get("api_modules", [])

            if pages and isinstance(pages[0], dict) and "content" in pages[0]:
                knowledge["pages"] = self._analyze_pages_with_content(pages)
            else:
                knowledge["pages"] = self.analyze_project_files(project_root, pages)

            if components and isinstance(components[0], dict) and "content" in components[0]:
                knowledge["components"] = self._analyze_components_with_content(components)
            else:
                knowledge["components"] = self.analyze_project_files(project_root, components)

            if api_modules and isinstance(api_modules[0], dict) and "content" in api_modules[0]:
                knowledge["api_modules"] = self._analyze_api_with_content(api_modules)
            else:
                api_files = [m["path"] for m in api_modules] if api_modules else []
                knowledge["api_modules"] = self.analyze_project_files(project_root, api_files)

        knowledge["data_flow"] = self._build_data_flow(knowledge)

        return knowledge

    def _analyze_pages_with_content(self, pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = []
        for page in pages:
            file_path = page.get("path", page.get("file", ""))
            content = page.get("content", "")
            
            analysis = self._vue_analyzer.analyze_vue_file(file_path, content)
            results.append(analysis)
        return results

    def _analyze_components_with_content(self, components: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = []
        for comp in components:
            file_path = comp.get("path", comp.get("file", ""))
            content = comp.get("content", "")
            
            analysis = self._vue_analyzer.analyze_vue_file(file_path, content)
            results.append(analysis)
        return results

    def _analyze_api_with_content(self, api_modules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = []
        for api in api_modules:
            file_path = api.get("path", api.get("file", ""))
            content = api.get("content", "")
            
            analysis = {
                "file": file_path,
                "relative_path": file_path,
                "type": "api_module",
                "symbols": api.get("symbols", []),
                "business": self._infer_api_business_from_content(content),
                "methods": self._extract_api_methods(content),
            }
            results.append(analysis)
        return results

    def _infer_api_business_from_content(self, content: str) -> str:
        business_hints = []
        keyword_mapping = {
            "patient": "患者",
            "lesion": "病灶",
            "ceus": "造影",
            "treatment": "治疗",
            "follow": "随访",
            "lab": "实验室",
            "data": "数据",
            "form": "表单",
            "ae": "不良事件",
            "study": "研究",
            "list": "列表",
            "query": "查询",
            "save": "保存",
            "delete": "删除",
            "update": "更新",
            "create": "创建",
        }
        
        lower_content = content.lower()
        for keyword, hint in keyword_mapping.items():
            if keyword in lower_content:
                if hint not in business_hints:
                    business_hints.append(hint)
        
        return "、".join(business_hints) if business_hints else "通用接口"

    def _extract_api_methods(self, content: str) -> List[str]:
        patterns = [
            r"export\s+(?:async\s+)?function\s+([A-Za-z0-9_]+)",
            r"export\s+const\s+([A-Za-z0-9_]+)\s*=",
        ]
        methods = []
        for pattern in patterns:
            methods.extend(re.findall(pattern, content))
        return list(set(methods))[:20]

    def _analyze_pages_from_code_index(self, code_index_pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = []
        for page_info in code_index_pages:
            file_path = page_info["file"]
            content = page_info["content"]
            
            analysis = self._vue_analyzer.analyze_vue_file(file_path, content)
            analysis["template_components"] = page_info.get("template_components", [])
            analysis["api_calls"] = page_info.get("api_calls", [])
            analysis["title"] = page_info.get("title", "")
            
            results.append(analysis)
        return results

    def _analyze_components_from_code_index(self, code_index_components: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = []
        for comp_info in code_index_components:
            file_path = comp_info["file"]
            content = comp_info["content"]
            
            analysis = self._vue_analyzer.analyze_vue_file(file_path, content)
            analysis["template_components"] = comp_info.get("template_components", [])
            analysis["api_calls"] = comp_info.get("api_calls", [])
            
            results.append(analysis)
        return results

    def _analyze_api_from_code_index(self, code_index_apis: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = []
        for api_info in code_index_apis:
            file_path = api_info["file"]
            content = api_info["content"]
            
            analysis = {
                "file": file_path,
                "relative_path": file_path,
                "type": "api_module",
                "symbols": api_info.get("symbols", []),
                "apis": api_info.get("apis", []),
                "business": self._infer_api_business(api_info.get("apis", [])),
                "methods": [api["name"] for api in api_info.get("apis", [])],
            }
            results.append(analysis)
        return results

    def _infer_api_business(self, apis: List[Dict[str, Any]]) -> str:
        business_hints = []
        keyword_mapping = {
            "patient": "患者",
            "lesion": "病灶",
            "ceus": "造影",
            "treatment": "治疗",
            "follow": "随访",
            "lab": "实验室",
            "data": "数据",
            "form": "表单",
            "ae": "不良事件",
            "study": "研究",
            "list": "列表",
            "query": "查询",
            "save": "保存",
            "delete": "删除",
            "update": "更新",
            "create": "创建",
        }
        
        for api in apis:
            name = api.get("name", "").lower()
            url = api.get("url", "").lower()
            
            for keyword, hint in keyword_mapping.items():
                if keyword in name or keyword in url:
                    if hint not in business_hints:
                        business_hints.append(hint)
        
        return "、".join(business_hints) if business_hints else "通用接口"

    def _build_data_flow(self, knowledge: Dict[str, Any]) -> List[Dict[str, Any]]:
        data_flow = []
        for page in knowledge.get("pages", []):
            page_flow = {
                "page": page.get("relative_path", ""),
                "business": page.get("business", ""),
                "api_calls": page.get("related_api", []),
                "imports": [imp["path"] for imp in page.get("imports", [])],
            }
            data_flow.append(page_flow)
        return data_flow

    def summarize_business_capabilities(self, knowledge: Dict[str, Any]) -> str:
        sections = ["# 项目业务能力总结"]

        pages_by_business = {}
        for page in knowledge.get("pages", []):
            business = page.get("business", "未分类")
            if business not in pages_by_business:
                pages_by_business[business] = []
            pages_by_business[business].append(page)

        if pages_by_business:
            sections.append("## 业务模块")
            for business, pages in pages_by_business.items():
                sections.append(f"\n### {business}")
                for page in pages:
                    features = ", ".join(page.get("features", [])[:5])
                    sections.append(f"- **{page['file']}**: {features}")

        api_count = len(knowledge.get("api_modules", []))
        if api_count > 0:
            sections.append(f"\n## API 模块 ({api_count}个)")
            for api in knowledge.get("api_modules", []):
                methods = ", ".join(api.get("methods", [])[:5])
                sections.append(f"- **{api['file']}**: {methods}")

        components_count = len(knowledge.get("components", []))
        if components_count > 0:
            sections.append(f"\n## 公共组件 ({components_count}个)")
            for comp in knowledge.get("components", []):
                features = ", ".join(comp.get("features", [])[:3])
                sections.append(f"- **{comp['file']}**: {features}")

        return "\n".join(sections)