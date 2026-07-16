import json
import re
from typing import List, Dict, Any, Optional
from pathlib import Path
from openai import AsyncOpenAI
import asyncio
import logging

from app.config import DASHSCOPE_API_KEY, MODEL_NAME, TEMPERATURE_CHAT, WORKSPACE

logger = logging.getLogger("gt_agent.completion_analyzer")

client = AsyncOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)


class RequirementCompletionAnalyzer:
    def __init__(self):
        self._evidence_patterns = {
            "state_binding": [
                "v-model", ":value", "this\\.", "\\.value", "data\\(", "props:",
                "useState", "useReducer", "setState", "reactive", "ref", "computed",
                "@Binding", "ng-model", "[(ngModel)]",
            ],
            "event_handler": [
                "@click", "@change", "@input", "@select", "@submit", "@click=",
                "@onClick", "@onChange", "onClick", "onChange", "handle",
                "addEventListener", "addListener", "on(", "bind(",
            ],
            "api_call": [
                "axios\\.", "fetch\\(", "$http\\.", "request\\(", "post\\(", "get\\(",
                "put\\(", "delete\\(", "ajax\\(", "send\\(",
                "http\\.", "HttpClient", "RestTemplate", "requests\\.",
            ],
            "component": [
                "import", "components:", "<", "export", "from ",
                "defineComponent", "createComponent", "extends", "class ",
                "React\\.", "Vue\\.", "@Component", "@NgModule",
            ],
            "dialog_modal": [
                "dialog", "modal", "visible", "popup", "showModal", "openModal",
                "showDialog", "hideDialog", "closeModal", "dialogVisible",
            ],
            "form_validation": [
                "el-form", "form-item", "required", "rules:", "validate",
                "Form", "form-control", "valid", "validation", "checkValidity",
            ],
            "data_save": [
                "save", "submit", "commit", "persist", "store", "saveData",
                "saveForm", "submitForm", "postData",
            ],
            "button_action": [
                "button", "btn", "click", "submit", "action", "trigger",
                "<button", "<Button", "type=\"button\"",
            ],
        }

        self._completion_status_map = {
            0: "not_started",
            10: "not_started",
            20: "not_started",
            30: "partial",
            40: "partial",
            50: "partial",
            60: "partial",
            70: "partial",
            80: "mostly_done",
            90: "mostly_done",
            100: "completed",
        }

        self._acceptance_categories = [
            {"id": "ui", "name": "UI界面", "description": "界面元素是否存在"},
            {"id": "interaction", "name": "交互逻辑", "description": "用户操作响应"},
            {"id": "data", "name": "数据处理", "description": "数据字段和存储"},
            {"id": "integration", "name": "系统集成", "description": "接口调用和外部服务"},
            {"id": "business", "name": "业务逻辑", "description": "业务规则和流程"},
            {"id": "validation", "name": "校验规则", "description": "数据验证和错误处理"},
            {"id": "navigation", "name": "页面导航", "description": "路由跳转和页面切换"},
        ]

    async def decompose_requirement(self, requirement: Dict[str, Any]) -> List[Dict[str, Any]]:
        """使用LLM将需求拆解为可验证的验收项"""
        description = requirement.get("description", "")
        req_id = requirement.get("id", "REQ000")

        prompt = f"""你是软件需求分析专家。请将以下需求拆解为可验证的验收项。

需求描述：
{description}

请输出JSON格式，包含多个验收项，每个验收项包含：
- id: 验收项ID（如 A1, A2）
- category: 验收类别（从以下选择：ui, interaction, data, integration, business, validation, navigation）
- expected: 预期的实现描述（具体、可验证）
- keywords: 相关关键词（用于代码搜索）

输出格式示例：
[
  {{
    "id": "A1",
    "category": "ui",
    "expected": "存在一个导出按钮",
    "keywords": ["export", "button"]
  }},
  {{
    "id": "A2",
    "category": "interaction",
    "expected": "点击导出按钮触发导出操作",
    "keywords": ["click", "export"]
  }}
]

注意：
1. 每个验收项必须具体、可验证，不能模糊
2. 文件存在 ≠ 功能完成，要检查实际实现
3. 关键词存在 ≠ 功能实现，要检查业务闭环
4. 至少生成3-5个验收项"""

        try:
            response = await client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            if content:
                try:
                    data = json.loads(content)
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and "acceptance_items" in data:
                        return data["acceptance_items"]
                except json.JSONDecodeError:
                    logger.warning(f"解析验收项JSON失败: {content[:200]}")

            return self._fallback_decompose(description, req_id)
        except Exception as e:
            logger.warning(f"LLM拆解需求失败: {e}")
            return self._fallback_decompose(description, req_id)

    def _fallback_decompose(self, description: str, req_id: str) -> List[Dict[str, Any]]:
        """备用：基于规则的需求拆解"""
        items = []
        item_id = 1

        description_lower = description.lower()

        if "导出" in description or "export" in description_lower:
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "ui",
                "expected": "存在导出按钮或入口",
                "keywords": ["export", "button", "btn"],
            })
            item_id += 1
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "interaction",
                "expected": "点击导出触发数据导出操作",
                "keywords": ["click", "export", "trigger"],
            })
            item_id += 1
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "integration",
                "expected": "生成并下载导出文件",
                "keywords": ["download", "blob", "file", "excel", "csv", "pdf"],
            })
            item_id += 1

        if "导入" in description or "import" in description_lower:
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "ui",
                "expected": "存在文件上传入口",
                "keywords": ["import", "upload", "file"],
            })
            item_id += 1
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "integration",
                "expected": "解析并保存导入数据",
                "keywords": ["parse", "save", "api", "post"],
            })
            item_id += 1

        if "新增" in description or "add" in description_lower or "create" in description_lower:
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "ui",
                "expected": "存在新增入口或表单",
                "keywords": ["add", "create", "new", "form"],
            })
            item_id += 1
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "data",
                "expected": "存在新增数据的字段定义",
                "keywords": ["field", "input", "data"],
            })
            item_id += 1
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "integration",
                "expected": "保存新增数据到后端",
                "keywords": ["save", "submit", "post", "api"],
            })
            item_id += 1

        if "删除" in description or "delete" in description_lower:
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "ui",
                "expected": "存在删除按钮",
                "keywords": ["delete", "remove", "button"],
            })
            item_id += 1
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "interaction",
                "expected": "点击删除触发确认或执行",
                "keywords": ["click", "confirm", "dialog"],
            })
            item_id += 1
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "integration",
                "expected": "调用删除接口",
                "keywords": ["delete", "api", "request"],
            })
            item_id += 1

        if "修改" in description or "edit" in description_lower or "update" in description_lower:
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "ui",
                "expected": "存在编辑入口或表单",
                "keywords": ["edit", "update", "form"],
            })
            item_id += 1
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "integration",
                "expected": "保存修改后的数据",
                "keywords": ["save", "submit", "put", "api"],
            })
            item_id += 1

        if "查询" in description or "search" in description_lower or "filter" in description_lower:
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "ui",
                "expected": "存在查询条件输入",
                "keywords": ["search", "query", "filter", "input"],
            })
            item_id += 1
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "interaction",
                "expected": "输入条件触发查询",
                "keywords": ["click", "search", "handle"],
            })
            item_id += 1
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "integration",
                "expected": "调用查询接口获取数据",
                "keywords": ["get", "api", "request"],
            })
            item_id += 1

        if "按钮" in description or "button" in description_lower:
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "ui",
                "expected": "存在相关按钮元素",
                "keywords": ["button", "btn", "click"],
            })
            item_id += 1

        if "点击" in description or "触发" in description or "onclick" in description_lower:
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "interaction",
                "expected": "点击后执行相应操作",
                "keywords": ["click", "trigger", "handle"],
            })
            item_id += 1

        if "字段" in description or "field" in description_lower or "输入" in description:
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "data",
                "expected": "存在相关数据字段定义",
                "keywords": ["field", "input", "v-model"],
            })
            item_id += 1

        if "保存" in description or "submit" in description_lower:
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "integration",
                "expected": "数据能够保存到后端",
                "keywords": ["save", "submit", "post", "api"],
            })
            item_id += 1

        if "弹窗" in description or "dialog" in description_lower or "modal" in description_lower:
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "ui",
                "expected": "存在弹窗组件并能正常显示",
                "keywords": ["dialog", "modal", "popup", "visible"],
            })
            item_id += 1

        if "跳转" in description or "导航" in description or "route" in description_lower:
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "navigation",
                "expected": "能够跳转到指定页面",
                "keywords": ["route", "navigate", "redirect", "push"],
            })
            item_id += 1

        if "验证" in description or "校验" in description or "valid" in description_lower:
            items.append({
                "id": f"{req_id}-A{item_id}",
                "category": "validation",
                "expected": "存在数据校验规则",
                "keywords": ["valid", "check", "required", "validate"],
            })
            item_id += 1

        if not items:
            items.append({
                "id": f"{req_id}-A1",
                "category": "business",
                "expected": "需求功能已实现",
                "keywords": [],
            })

        return items

    async def analyze_completion(
        self,
        requirement: Dict[str, Any],
        project_knowledge: Dict[str, Any],
        related_files: List[Dict[str, Any]],
        project_path: str = "",
    ) -> Dict[str, Any]:
        """分析需求完成度"""
        req_id = requirement.get("id", "REQ000")
        description = requirement.get("description", "")

        yield {"status": f"正在拆解需求 {req_id}..."}

        acceptance_items = await self.decompose_requirement(requirement)

        yield {"status": f"生成了 {len(acceptance_items)} 个验收项"}

        checked_items = []

        for item in acceptance_items:
            yield {"status": f"检查验收项: {item['expected']}"}

            item_result = await self._check_acceptance_condition(
                item, related_files, project_path, project_knowledge
            )
            checked_items.append(item_result)

        completion_rate = self._calculate_completion_rate(checked_items)
        status = self._completion_status_map.get(completion_rate, "partial")

        suggestions = self._generate_suggestions(checked_items)

        result = {
            "requirement_id": req_id,
            "requirement_description": description,
            "completion_rate": completion_rate,
            "status": status,
            "acceptance_items": checked_items,
            "implemented": [
                item for item in checked_items if item.get("status") == "done"
            ],
            "missing": [
                item for item in checked_items if item.get("status") != "done"
            ],
            "suggestions": suggestions,
            "related_files": [
                {"file": f.get("file", f.get("relative_path", "")), "score": f.get("score", 0)}
                for f in related_files[:10]
            ],
        }

        yield {"done": result}

    async def _check_acceptance_condition(
        self,
        acceptance_item: Dict[str, Any],
        related_files: List[Dict[str, Any]],
        project_path: str,
        project_knowledge: Dict[str, Any],
    ) -> Dict[str, Any]:
        """检查单个验收项是否满足"""
        expected = acceptance_item.get("expected", "")
        category = acceptance_item.get("category", "")
        keywords = acceptance_item.get("keywords", [])

        evidence_found = []
        missing_evidence = []

        for file_info in related_files[:10]:
            file_path = file_info.get("file", file_info.get("relative_path", ""))
            file_type = file_info.get("type", "")

            file_content = await self._read_file_content(file_path, project_path)
            features = file_info.get("features", [])
            data_fields = file_info.get("data_fields", [])
            methods = file_info.get("methods", [])

            if file_content:
                file_evidence = self._find_evidence_in_file(
                    file_content, expected, category, keywords
                )
                if file_evidence["found"]:
                    evidence_found.append({
                        "file": file_path,
                        "evidence": file_evidence["evidence"],
                    })
                else:
                    missing_evidence.append({
                        "file": file_path,
                        "issue": file_evidence["missing"],
                    })
            else:
                meta_evidence = self._find_evidence_in_metadata(
                    features, data_fields, methods, expected, keywords
                )
                if meta_evidence:
                    evidence_found.append({
                        "file": file_path,
                        "evidence": meta_evidence,
                    })

        status = "done" if evidence_found else "missing"
        if evidence_found and missing_evidence:
            status = "partial"

        return {
            **acceptance_item,
            "status": status,
            "evidence": evidence_found,
            "missing": missing_evidence,
        }

    async def _read_file_content(self, file_path: str, project_path: str = "") -> str:
        """读取真实源码文件内容"""
        if not file_path:
            return ""

        try:
            full_path = Path(project_path) / file_path if project_path else Path(file_path)
            if full_path.exists():
                return full_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.warning(f"读取文件 {file_path} 失败: {e}")

        return ""

    def _find_evidence_in_file(
        self,
        file_content: str,
        expected: str,
        category: str,
        keywords: List[str],
    ) -> Dict[str, Any]:
        """在文件内容中查找证据"""
        content_lower = file_content.lower()
        evidence = []
        missing = []

        patterns_for_category = self._get_patterns_for_category(category)

        for pattern_name, patterns in patterns_for_category.items():
            for pattern in patterns:
                if re.search(pattern, content_lower):
                    evidence.append(f"代码中存在{pattern_name}模式: {pattern}")
                    break

        for kw in keywords:
            if kw.lower() in content_lower:
                evidence.append(f"代码中存在关键词: {kw}")

        expected_lower = expected.lower()

        if "按钮" in expected or "button" in expected_lower:
            if "<button" in content_lower or "el-button" in content_lower:
                evidence.append("发现按钮元素")
            else:
                missing.append("未发现按钮元素")

        if "弹窗" in expected or "dialog" in expected_lower or "modal" in expected_lower:
            if "dialog" in content_lower or "modal" in content_lower:
                evidence.append("发现弹窗组件")
            else:
                missing.append("未发现弹窗组件")

        if "字段" in expected or "field" in expected_lower or "输入" in expected:
            if "v-model" in content_lower or "input" in content_lower or "field" in content_lower:
                evidence.append("发现字段绑定")
            else:
                missing.append("未发现字段绑定")

        if "保存" in expected or "submit" in expected_lower:
            if "save" in content_lower or "submit" in content_lower or "post(" in content_lower:
                evidence.append("发现保存/提交逻辑")
            else:
                missing.append("未发现保存/提交逻辑")

        if "点击" in expected or "触发" in expected:
            if "@click" in content_lower or "onclick" in content_lower or "handle" in content_lower:
                evidence.append("发现点击事件处理")
            else:
                missing.append("未发现点击事件处理")

        if "跳转" in expected or "导航" in expected:
            if "router" in content_lower or "push(" in content_lower or "navigate" in content_lower:
                evidence.append("发现路由跳转")
            else:
                missing.append("未发现路由跳转")

        if "验证" in expected or "校验" in expected:
            if "valid" in content_lower or "required" in content_lower or "rules" in content_lower:
                evidence.append("发现校验规则")
            else:
                missing.append("未发现校验规则")

        if evidence and not missing:
            return {"found": True, "evidence": "; ".join(evidence)}
        elif missing:
            return {"found": False, "evidence": "; ".join(evidence) if evidence else "", "missing": "; ".join(missing)}
        else:
            return {"found": False, "evidence": "", "missing": "未找到相关代码证据"}

    def _get_patterns_for_category(self, category: str) -> Dict[str, List[str]]:
        """根据验收类别获取对应的证据模式"""
        category_patterns = {
            "ui": {"state_binding": self._evidence_patterns["state_binding"]},
            "interaction": {"event_handler": self._evidence_patterns["event_handler"]},
            "data": {"state_binding": self._evidence_patterns["state_binding"], "data_save": self._evidence_patterns["data_save"]},
            "integration": {"api_call": self._evidence_patterns["api_call"]},
            "business": {"event_handler": self._evidence_patterns["event_handler"], "data_save": self._evidence_patterns["data_save"]},
            "validation": {"form_validation": self._evidence_patterns["form_validation"]},
            "navigation": {"event_handler": self._evidence_patterns["event_handler"], "api_call": self._evidence_patterns["api_call"]},
        }
        return category_patterns.get(category, {})

    def _find_evidence_in_metadata(
        self,
        features: List[str],
        data_fields: List[str],
        methods: List[str],
        expected: str,
        keywords: List[str],
    ) -> str:
        """在元数据中查找证据"""
        features_str = " ".join(str(f).lower() for f in features)
        data_fields_str = " ".join(str(f).lower() for f in data_fields)
        methods_str = " ".join(str(m).lower() for m in methods)

        evidence = []

        for kw in keywords:
            if kw.lower() in features_str:
                evidence.append(f"功能特性包含: {kw}")
            if kw.lower() in data_fields_str:
                evidence.append(f"数据字段包含: {kw}")
            if kw.lower() in methods_str:
                evidence.append(f"方法包含: {kw}")

        return "; ".join(evidence) if evidence else None

    def _calculate_completion_rate(self, checked_items: List[Dict[str, Any]]) -> int:
        """基于验收项计算完成度"""
        if not checked_items:
            return 0

        total = len(checked_items)
        done_count = sum(1 for item in checked_items if item.get("status") == "done")
        partial_count = sum(1 for item in checked_items if item.get("status") == "partial")

        score = (done_count * 100 + partial_count * 50) / total

        return round(score / 10) * 10

    def _generate_suggestions(self, checked_items: List[Dict[str, Any]]) -> List[str]:
        """基于缺失项生成修改建议"""
        suggestions = []
        missing_items = [item for item in checked_items if item.get("status") != "done"]

        if not missing_items:
            suggestions.append("需求已基本实现，建议进行功能测试验证")
            return suggestions

        for item in missing_items:
            expected = item.get("expected", "")
            category = item.get("category", "")

            if category == "ui":
                suggestions.append(f"需要实现界面元素: {expected}")
            elif category == "interaction":
                suggestions.append(f"需要实现交互逻辑: {expected}")
            elif category == "data":
                suggestions.append(f"需要添加数据字段或数据处理: {expected}")
            elif category == "integration":
                suggestions.append(f"需要实现接口调用或集成: {expected}")
            elif category == "validation":
                suggestions.append(f"需要添加校验规则: {expected}")
            elif category == "navigation":
                suggestions.append(f"需要实现页面跳转: {expected}")
            else:
                suggestions.append(f"需要实现: {expected}")

        suggestions.append(f"建议优先处理 {len(missing_items)} 个缺失的验收项")

        return list(set(suggestions))

    def generate_completion_report(self, analysis_result: Dict[str, Any]) -> str:
        """生成格式化的完成度报告"""
        sections = []

        sections.append(f"## {analysis_result['requirement_id']} — 需求完成度分析")

        sections.append(f"\n### 完成度评估")
        sections.append(f"- 完成率: {analysis_result['completion_rate']}%")
        sections.append(f"- 状态: {self._get_status_label(analysis_result['status'])}")

        sections.append(f"\n### 验收项检查结果")
        for item in analysis_result["acceptance_items"]:
            status_icon = "✅" if item.get("status") == "done" else ("⚠️" if item.get("status") == "partial" else "❌")
            sections.append(f"\n{status_icon} **{item['id']}** — {self._get_category_label(item['category'])}")
            sections.append(f"   - 预期: {item['expected']}")
            sections.append(f"   - 状态: {self._get_status_label(item.get('status', 'unknown'))}")

            if item.get("evidence"):
                sections.append(f"   - 证据:")
                for ev in item["evidence"]:
                    sections.append(f"     * [{ev['file']}]: {ev['evidence']}")

            if item.get("missing"):
                sections.append(f"   - 缺失:")
                for ms in item["missing"]:
                    sections.append(f"     * [{ms['file']}]: {ms['issue']}")

        if analysis_result["suggestions"]:
            sections.append("\n### 修改建议")
            for idx, suggestion in enumerate(analysis_result["suggestions"], 1):
                sections.append(f"{idx}. {suggestion}")

        return "\n".join(sections)

    def _get_status_label(self, status: str) -> str:
        """获取状态标签"""
        labels = {
            "not_started": "未开始",
            "partial": "部分实现",
            "mostly_done": "基本完成",
            "completed": "已完成",
            "done": "已完成",
            "missing": "未实现",
        }
        return labels.get(status, status)

    def _get_category_label(self, category: str) -> str:
        """获取类别标签"""
        for cat in self._acceptance_categories:
            if cat["id"] == category:
                return cat["name"]
        return category
