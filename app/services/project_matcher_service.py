from typing import List, Dict
from collections import Counter

from app.services.project_registry_service import list_registered_projects


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    toks = [t.lower() for t in text.replace("/", " ").replace("-", " ").split()]
    return [t.strip() for t in toks if t.strip()]


def match_projects(requirement: Dict) -> Dict:
    projects = list_registered_projects()
    req_text = " ".join([requirement.get("title", ""), requirement.get("summary", "")] )
    req_tokens = set(_tokenize(req_text))

    results = []
    for p in projects:
        score = 0.0
        reasons = []
        name_tokens = set(_tokenize(p.get("name", "")))
        overlap = req_tokens.intersection(name_tokens)
        if overlap:
            score += 0.5
            reasons.append(f"项目名匹配: {', '.join(overlap)}")

        summary = p.get("module_summary", "")
        summary_tokens = set(_tokenize(summary))
        inter = req_tokens.intersection(summary_tokens)
        if inter:
            score += 0.3
            reasons.append(f"模块摘要匹配: {', '.join(inter)}")

        dirs = "+".join(p.get("page_dirs", []) + p.get("component_dirs", []))
        dir_tokens = set(_tokenize(dirs))
        if req_tokens.intersection(dir_tokens):
            score += 0.2
            reasons.append("存在相似页面/组件目录")

        results.append({"project": p.get("name"), "score": round(score, 2), "reasons": reasons})

    results.sort(key=lambda x: x["score"], reverse=True)
    return {"recommended_projects": results[:5], "manual_selection_required": False}
