import json
import re
from typing import List, Dict, Any, Optional
from pathlib import Path

import logging

logger = logging.getLogger("gt_agent.code_matcher")


class CodeMatcher:
    def __init__(self):
        self._keyword_mapping = {
            "患者": ["patient", "patientId", "患者", "姓名", "年龄", "入组"],
            "病灶": ["lesion", "focus", "病灶", "结节", "肿块", "US"],
            "造影": ["ceus", "contrast", "造影", "增强", "Sonazoid"],
            "治疗": ["treatment", "therapy", "治疗", "化疗", "手术"],
            "随访": ["follow", "随访", "复查"],
            "实验室": ["lab", "laboratory", "实验室", "检查", "检验"],
            "数据": ["dashboard", "data", "统计", "看板"],
            "表单": ["form", "表单", "录入", "填写"],
            "AE": ["ae", "adverse", "不良", "事件"],
            "研究": ["study", "research", "研究", "trial"],
            "时间": ["time", "date", "时间", "日期"],
            "状态": ["status", "state", "状态"],
            "列表": ["list", "table", "列表", "表格"],
            "搜索": ["search", "query", "搜索", "查询"],
            "排序": ["sort", "order", "排序"],
            "弹窗": ["dialog", "modal", "popup", "弹窗"],
        }

        self._file_type_priority = {
            "form_page": 10,
            "list_page": 8,
            "dashboard_page": 7,
            "vue_page": 5,
            "api_module": 4,
            "store_module": 3,
            "component": 2,
        }

    def match_requirement_to_code(self, requirement: Dict[str, Any], project_knowledge: Dict[str, Any]) -> List[Dict[str, Any]]:
        matches = []

        keywords = requirement.get("keywords", [])
        target_modules = requirement.get("target_guess", [])
        req_type = requirement.get("type", "general")

        search_terms = self._expand_keywords(keywords)

        pages = project_knowledge.get("pages", [])
        components = project_knowledge.get("components", [])
        api_modules = project_knowledge.get("api_modules", [])

        all_files = []
        for page in pages:
            page["category"] = "page"
            all_files.append(page)
        for comp in components:
            comp["category"] = "component"
            all_files.append(comp)
        for api in api_modules:
            api["category"] = "api"
            all_files.append(api)

        for file_info in all_files:
            score = self._calculate_match_score(file_info, search_terms, target_modules, req_type)
            if score > 0:
                matches.append({
                    "file": file_info.get("relative_path", file_info.get("file", "")),
                    "category": file_info.get("category", "unknown"),
                    "type": file_info.get("type", "unknown"),
                    "business": file_info.get("business", ""),
                    "score": round(score, 2),
                    "reasons": self._get_match_reasons(file_info, search_terms, target_modules),
                    "features": file_info.get("features", []),
                    "related_api": file_info.get("related_api", []),
                    "imports": file_info.get("imports", []),
                })

        matches.sort(key=lambda x: x["score"], reverse=True)

        return matches[:20]

    def _expand_keywords(self, keywords: List[str]) -> List[str]:
        expanded = []
        for kw in keywords:
            lower_kw = kw.lower()
            expanded.append(lower_kw)
            if lower_kw in self._keyword_mapping:
                expanded.extend([k.lower() for k in self._keyword_mapping[lower_kw]])
        return list(set(expanded))

    def _calculate_match_score(self, file_info: Dict[str, Any], search_terms: List[str], target_modules: List[str], req_type: str) -> float:
        score = 0.0

        file_type = file_info.get("type", "")
        category = file_info.get("category", "")

        type_bonus = self._file_type_priority.get(file_type, 1)
        score += type_bonus * 0.5

        business = file_info.get("business", "").lower()
        features = file_info.get("features", [])
        features_str = " ".join(str(f).lower() for f in features)
        data_fields = file_info.get("data_fields", [])
        data_fields_str = " ".join(str(f).lower() for f in data_fields)
        methods = file_info.get("methods", [])
        methods_str = " ".join(str(m).lower() for m in methods)

        all_text = f"{business} {features_str} {data_fields_str} {methods_str}".lower()

        matched_terms = 0
        for term in search_terms:
            if term in all_text:
                matched_terms += 1
                score += 1.5

        if matched_terms == 0:
            return 0.0

        file_name = file_info.get("relative_path", file_info.get("file", "")).lower()
        for term in search_terms:
            if term in file_name:
                score += 2.0

        for target_module in target_modules:
            if target_module.lower() in business:
                score += 3.0
            for feature in features:
                if target_module.lower() in str(feature).lower():
                    score += 2.0

        type_multiplier = {
            "new_feature": 1.2,
            "field_modify": 1.1,
            "business_rule": 1.0,
            "ui_change": 0.9,
            "data_change": 1.0,
            "navigation": 0.8,
        }
        score *= type_multiplier.get(req_type, 1.0)

        return score

    def _get_match_reasons(self, file_info: Dict[str, Any], search_terms: List[str], target_modules: List[str]) -> List[str]:
        reasons = []

        business = file_info.get("business", "").lower()
        features = file_info.get("features", [])
        features_str = " ".join(str(f).lower() for f in features)
        file_name = file_info.get("relative_path", file_info.get("file", "")).lower()

        for term in search_terms:
            if term in business:
                reasons.append(f"业务描述包含关键词 '{term}'")
            if term in features_str:
                reasons.append(f"功能特性包含关键词 '{term}'")
            if term in file_name:
                reasons.append(f"文件名包含关键词 '{term}'")

        for target_module in target_modules:
            if target_module.lower() in business:
                reasons.append(f"匹配目标模块 '{target_module}'")

        if not reasons:
            reasons.append("基于功能特征匹配")

        return list(set(reasons))

    def generate_match_report(self, requirement: Dict[str, Any], matches: List[Dict[str, Any]]) -> str:
        sections = []

        sections.append(f"## {requirement['id']} — {requirement['description']}")
        sections.append(f"- 优先级: {requirement['priority']}")
        sections.append(f"- 关键词: {', '.join(requirement.get('keywords', []))}")
        sections.append(f"- 目标模块: {', '.join(requirement.get('target_guess', []))}")

        if matches:
            sections.append("\n### 匹配结果")
            for idx, match in enumerate(matches[:5], 1):
                sections.append(f"\n{idx}. **{match['file']}**")
                sections.append(f"   - 类型: {match['type']}")
                sections.append(f"   - 业务: {match['business']}")
                sections.append(f"   - 评分: {match['score']}")
                sections.append(f"   - 原因: {'; '.join(match['reasons'])}")
        else:
            sections.append("\n### 未找到匹配文件")
            sections.append("建议使用 search_file 工具搜索相关代码")

        return "\n".join(sections)

    def analyze_impact(self, all_matches: List[List[Dict[str, Any]]], requirements: List[Dict[str, Any]]) -> Dict[str, Any]:
        file_impact = {}

        for idx, matches in enumerate(all_matches):
            req = requirements[idx]
            for match in matches:
                file_path = match["file"]
                if file_path not in file_impact:
                    file_impact[file_path] = {
                        "file": file_path,
                        "type": match["type"],
                        "business": match["business"],
                        "requirements": [],
                        "total_score": 0.0,
                        "reasons": [],
                    }
                file_impact[file_path]["requirements"].append(req["id"])
                file_impact[file_path]["total_score"] += match["score"]
                file_impact[file_path]["reasons"].extend(match["reasons"])

        impact_list = sorted(file_impact.values(), key=lambda x: x["total_score"], reverse=True)

        return {
            "total_files": len(impact_list),
            "impact_files": impact_list[:30],
            "summary": self._generate_impact_summary(impact_list, requirements),
        }

    def _generate_impact_summary(self, impact_list: List[Dict[str, Any]], requirements: List[Dict[str, Any]]) -> str:
        sections = ["# 影响分析报告"]

        sections.append(f"\n## 概览")
        sections.append(f"- 受影响文件数: {len(impact_list)}")
        sections.append(f"- 需求数: {len(requirements)}")

        type_counts = {}
        for item in impact_list:
            file_type = item["type"]
            type_counts[file_type] = type_counts.get(file_type, 0) + 1

        sections.append("\n## 文件类型分布")
        for file_type, count in type_counts.items():
            sections.append(f"- {file_type}: {count} 个")

        sections.append("\n## 高影响文件")
        for idx, item in enumerate(impact_list[:10], 1):
            sections.append(f"\n{idx}. **{item['file']}**")
            sections.append(f"   - 类型: {item['type']}")
            sections.append(f"   - 业务: {item['business']}")
            sections.append(f"   - 涉及需求: {', '.join(item['requirements'])}")
            sections.append(f"   - 综合评分: {round(item['total_score'], 2)}")

        return "\n".join(sections)