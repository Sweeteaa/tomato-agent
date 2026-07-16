import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime

import logging

logger = logging.getLogger("gt_agent.requirement_analyzer")


class RequirementAnalyzer:
    def __init__(self):
        self._requirement_type_patterns = {
            "new_feature": [
                r"(新增|增加|添加|创建|建立|开发|实现)",
                r"(表单|页面|模块|功能|按钮|字段)",
            ],
            "ui_change": [
                r"(修改|调整|变更|更改|调整)",
                r"(位置|顺序|样式|显示|隐藏|布局)",
            ],
            "field_modify": [
                r"(增加|添加|修改|删除)",
                r"(字段|输入框|选项|下拉)",
            ],
            "business_rule": [
                r"(验证|校验|规则|条件|逻辑)",
                r"(必填|不能|必须|应该)",
            ],
            "data_change": [
                r"(排序|筛选|搜索|导出|导入)",
                r"(数据|列表|表格|查询)",
            ],
            "navigation": [
                r"(跳转|链接|路由|导航)",
            ],
        }

        self._business_keywords_map = {
            "患者": ["patient", "患者", "姓名", "年龄", "性别", "入组"],
            "病灶": ["lesion", "病灶", "结节", "肿块", "编号", "US"],
            "造影": ["ceus", "造影", "增强", "Sonazoid", "CEUS"],
            "治疗": ["treatment", "治疗", "化疗", "手术", "时间"],
            "随访": ["follow", "随访", "复查", "状态"],
            "实验室": ["lab", "实验室", "检查", "检验"],
            "数据": ["dashboard", "数据", "统计", "看板"],
            "AE": ["ae", "不良", "事件", "adverse"],
            "研究": ["study", "研究", "trial", "项目"],
        }

        self._target_module_keywords = {
            "数据看板": ["看板", "统计", "dashboard", "数据"],
            "病例表单": ["病例", "表单", "录入", "case"],
            "造影表单": ["造影", "ceus", "CEUS", "增强"],
            "治疗表单": ["治疗", "treatment"],
            "随访表单": ["随访", "follow"],
            "实验室检查": ["实验室", "检查", "检验", "lab"],
        }

    def parse_requirements(self, raw_text: str, task_id: str = "") -> Dict[str, Any]:
        requirements = []
        req_id_counter = 1

        sections = self._split_into_sections(raw_text)

        for section_name, section_content in sections:
            section_requirements = self._parse_section(section_content, section_name, req_id_counter)
            req_id_counter += len(section_requirements)
            requirements.extend(section_requirements)

        result = {
            "task_id": task_id,
            "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_requirements": len(requirements),
            "requirements": requirements,
            "sections": [s[0] for s in sections],
        }

        return result

    def _split_into_sections(self, text: str) -> List[tuple]:
        sections = []
        lines = text.splitlines()

        current_section = "未分类"
        current_content = []

        sheet_pattern = r"=== Sheet:\s*(.+?)\s*==="

        for line in lines:
            sheet_match = re.match(sheet_pattern, line)
            if sheet_match:
                if current_content:
                    sections.append((current_section, "\n".join(current_content)))
                current_section = sheet_match.group(1).strip()
                current_content = []
                continue

            if line.strip():
                current_content.append(line)

        if current_content:
            sections.append((current_section, "\n".join(current_content)))

        return sections

    def _parse_section(self, content: str, section_name: str, start_id: int) -> List[Dict[str, Any]]:
        requirements = []
        lines = content.splitlines()

        current_req_lines = []

        for line in lines:
            line = line.strip()

            if not line:
                if current_req_lines:
                    req = self._parse_single_requirement(
                        "\n".join(current_req_lines), section_name, start_id + len(requirements)
                    )
                    if req:
                        requirements.append(req)
                    current_req_lines = []
                continue

            if line.startswith("-") or line.startswith("*") or line.startswith("•"):
                if current_req_lines:
                    req = self._parse_single_requirement(
                        "\n".join(current_req_lines), section_name, start_id + len(requirements)
                    )
                    if req:
                        requirements.append(req)
                    current_req_lines = []
                current_req_lines.append(line[1:].strip())
            else:
                current_req_lines.append(line)

        if current_req_lines:
            req = self._parse_single_requirement(
                "\n".join(current_req_lines), section_name, start_id + len(requirements)
            )
            if req:
                requirements.append(req)

        return requirements

    def _parse_single_requirement(self, text: str, section_name: str, req_id: int) -> Optional[Dict[str, Any]]:
        if not text.strip():
            return None

        req_type = self._detect_requirement_type(text)
        keywords = self._extract_keywords(text)
        target_modules = self._guess_target_modules(keywords)

        requirement = {
            "id": f"REQ{req_id:03d}",
            "type": req_type,
            "section": section_name,
            "description": text.strip(),
            "keywords": keywords,
            "target_guess": target_modules,
            "priority": self._determine_priority(req_type, text),
            "impact_scope": self._estimate_impact_scope(req_type, keywords),
        }

        return requirement

    def _detect_requirement_type(self, text: str) -> str:
        lower_text = text.lower()

        for req_type, patterns in self._requirement_type_patterns.items():
            pattern_count = sum(1 for pattern in patterns if re.search(pattern, lower_text))
            if pattern_count >= 1:
                return req_type

        return "general"

    def _extract_keywords(self, text: str) -> List[str]:
        keywords = []
        lower_text = text.lower()

        for business_key, keyword_list in self._business_keywords_map.items():
            for kw in keyword_list:
                if kw.lower() in lower_text:
                    keywords.append(business_key)
                    break

        number_pattern = r"(\d+\.?\d*)"
        numbers = re.findall(number_pattern, text)
        keywords.extend(numbers)

        special_patterns = [
            r"(US-\d+)",
            r"(Sonazoid)",
            r"(CEUS)",
            r"(病灶编号)",
            r"(治疗时间)",
        ]
        for pattern in special_patterns:
            matches = re.findall(pattern, text)
            keywords.extend(matches)

        return list(set(keywords))

    def _guess_target_modules(self, keywords: List[str]) -> List[str]:
        target_modules = []
        lower_keywords = [k.lower() for k in keywords]

        for module_name, module_keywords in self._target_module_keywords.items():
            for kw in module_keywords:
                if kw.lower() in lower_keywords:
                    target_modules.append(module_name)
                    break

        return list(set(target_modules))

    def _determine_priority(self, req_type: str, text: str) -> str:
        priority_keywords = {
            "high": ["必须", "不能", "禁止", "错误", "失败", "必填"],
            "medium": ["应该", "建议", "需要", "增加", "修改"],
            "low": ["优化", "调整", "可选", "美化"],
        }

        lower_text = text.lower()

        for priority, keywords in priority_keywords.items():
            if any(kw in lower_text for kw in keywords):
                return priority

        type_priority = {
            "business_rule": "high",
            "field_modify": "medium",
            "new_feature": "high",
            "ui_change": "low",
            "data_change": "medium",
            "navigation": "medium",
            "general": "medium",
        }

        return type_priority.get(req_type, "medium")

    def _estimate_impact_scope(self, req_type: str, keywords: List[str]) -> List[str]:
        scope_map = {
            "new_feature": ["页面", "组件", "API"],
            "ui_change": ["页面", "样式"],
            "field_modify": ["表单", "API", "数据库"],
            "business_rule": ["表单", "API", "后端"],
            "data_change": ["页面", "API", "数据层"],
            "navigation": ["路由", "页面"],
            "general": ["页面"],
        }

        scope = scope_map.get(req_type, ["页面"])

        if "患者" in keywords:
            scope.append("患者模块")
        if "病灶" in keywords:
            scope.append("病灶模块")
        if "造影" in keywords:
            scope.append("造影模块")
        if "AE" in keywords:
            scope.append("AE模块")

        return list(set(scope))

    def generate_requirement_summary(self, parsed_requirements: Dict[str, Any]) -> str:
        sections = ["# 需求分析报告"]

        sections.append(f"## 概览")
        sections.append(f"- 解析时间: {parsed_requirements['parsed_at']}")
        sections.append(f"- 总需求数: {parsed_requirements['total_requirements']}")
        sections.append(f"- 涉及模块: {', '.join(parsed_requirements.get('sections', []))}")

        type_counts = {}
        priority_counts = {}
        for req in parsed_requirements["requirements"]:
            req_type = req["type"]
            priority = req["priority"]
            type_counts[req_type] = type_counts.get(req_type, 0) + 1
            priority_counts[priority] = priority_counts.get(priority, 0) + 1

        sections.append("\n## 需求分类")
        for req_type, count in type_counts.items():
            sections.append(f"- {self._get_type_label(req_type)}: {count} 条")

        sections.append("\n## 优先级分布")
        for priority, count in priority_counts.items():
            sections.append(f"- {priority.upper()}: {count} 条")

        sections.append("\n## 需求详情")
        for req in parsed_requirements["requirements"]:
            sections.append(f"\n### {req['id']} — {self._get_type_label(req['type'])}")
            sections.append(f"- **描述**: {req['description']}")
            sections.append(f"- **关键词**: {', '.join(req['keywords'])}")
            sections.append(f"- **目标模块**: {', '.join(req['target_guess'])}")
            sections.append(f"- **优先级**: {req['priority']}")
            sections.append(f"- **影响范围**: {', '.join(req['impact_scope'])}")

        return "\n".join(sections)

    def _get_type_label(self, req_type: str) -> str:
        labels = {
            "new_feature": "新增功能",
            "ui_change": "界面调整",
            "field_modify": "字段修改",
            "business_rule": "业务规则",
            "data_change": "数据变更",
            "navigation": "导航跳转",
            "general": "通用需求",
        }
        return labels.get(req_type, req_type)