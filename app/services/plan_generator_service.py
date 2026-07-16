import json
import uuid
from typing import List, Dict, Any, Optional
from pathlib import Path
from openai import AsyncOpenAI
import logging

from app.config import DASHSCOPE_API_KEY, MODEL_NAME, TEMPERATURE_CHAT, WORKSPACE

logger = logging.getLogger("gt_agent.plan_generator")

client = AsyncOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)


class PlanGenerator:
    def __init__(self):
        self._step_types = [
            {"id": "analysis", "name": "分析", "description": "代码分析、定位、理解"},
            {"id": "modify", "name": "修改", "description": "修改现有代码"},
            {"id": "create", "name": "创建", "description": "新建文件或组件"},
            {"id": "api", "name": "接口", "description": "API接口开发或修改"},
            {"id": "test", "name": "测试", "description": "验证、测试功能"},
            {"id": "review", "name": "审查", "description": "代码审查、质量检查"},
        ]

    async def generate_plan(
        self,
        requirement: Dict[str, Any],
        completion_result: Dict[str, Any],
        project_knowledge: Dict[str, Any],
    ) -> Dict[str, Any]:
        """根据需求、完成度分析结果和项目知识生成执行计划"""
        plan_id = f"PLAN{uuid.uuid4().hex[:8].upper()}"
        requirement_desc = requirement.get("description", "")
        requirement_id = requirement.get("id", "REQ000")

        missing_items = completion_result.get("missing", [])
        implemented_items = completion_result.get("implemented", [])
        completion_rate = completion_result.get("completion_rate", 0)

        related_files = completion_result.get("related_files", [])
        project_name = project_knowledge.get("project_name", "")
        project_path = project_knowledge.get("project_path", "")

        missing_details = ""
        if missing_items:
            missing_details = "\n".join(
                f"- [{item.get('file', '未知文件')}]: {item.get('issue', item.get('expected', ''))}"
                for item in missing_items[:10]
            )

        related_files_str = ""
        if related_files:
            related_files_str = "\n".join(
                f"- {f.get('file', '')} (匹配度: {f.get('score', 0)})"
                for f in related_files[:10]
            )

        prompt = f"""你是软件项目执行计划专家。请根据需求分析和完成度检查结果，生成一份详细的执行计划。

## 需求信息
- 需求ID: {requirement_id}
- 需求描述: {requirement_desc}
- 当前完成度: {completion_rate}%

## 缺失项（需要实现的内容）
{missing_details if missing_details else "无"}

## 已实现项
{implemented_items[:5] if implemented_items else "无"}

## 相关文件
{related_files_str if related_files_str else "无"}

## 项目信息
- 项目名称: {project_name}
- 项目路径: {project_path}
- 技术框架: {project_knowledge.get('framework', '未知')}

## 任务要求

请生成一个结构化的执行计划，每个步骤必须具体、可执行。

## 输出格式

请输出JSON格式，包含以下字段：

{{
  "plan_id": "{plan_id}",
  "goal": "明确的目标描述",
  "project": "{project_name}",
  "requirement_id": "{requirement_id}",
  "total_steps": 步骤总数,
  "steps": [
    {{
      "id": 步骤序号,
      "type": "步骤类型(analysis/modify/create/api/test/review)",
      "title": "简短标题",
      "description": "详细描述，说明做什么、为什么做",
      "target_file": "目标文件名（如果有）",
      "expected_outcome": "预期结果",
      "dependencies": ["前置步骤ID"]
    }}
  ]
}}

## 注意事项

1. 步骤类型必须从以下选择: analysis, modify, create, api, test, review
2. 每个步骤必须有明确的目标文件（如果适用）
3. 步骤之间可以有依赖关系
4. 测试步骤必须在修改/创建步骤之后
5. 审查步骤应该在最后
6. 不要生成空步骤
7. 至少生成3-8个步骤"""

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
                    plan = json.loads(content)
                    return self._validate_plan(plan)
                except json.JSONDecodeError:
                    logger.warning(f"解析计划JSON失败: {content[:200]}")

            return self._fallback_generate_plan(requirement, completion_result, project_knowledge, plan_id)
        except Exception as e:
            logger.warning(f"LLM生成计划失败: {e}")
            return self._fallback_generate_plan(requirement, completion_result, project_knowledge, plan_id)

    def _validate_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """验证计划结构完整性"""
        if "steps" not in plan:
            plan["steps"] = []

        for idx, step in enumerate(plan["steps"]):
            if "id" not in step:
                step["id"] = idx + 1
            if "type" not in step:
                step["type"] = "analysis"
            if "dependencies" not in step:
                step["dependencies"] = []

        plan["total_steps"] = len(plan["steps"])

        return plan

    def _fallback_generate_plan(
        self,
        requirement: Dict[str, Any],
        completion_result: Dict[str, Any],
        project_knowledge: Dict[str, Any],
        plan_id: str,
    ) -> Dict[str, Any]:
        """备用：基于规则生成计划"""
        steps = []
        step_id = 1

        requirement_desc = requirement.get("description", "")
        missing_items = completion_result.get("missing", [])
        related_files = completion_result.get("related_files", [])
        project_name = project_knowledge.get("project_name", "")
        requirement_id = requirement.get("id", "REQ000")

        steps.append({
            "id": step_id,
            "type": "analysis",
            "title": "分析需求和现有代码",
            "description": f"理解需求 '{requirement_desc}'，分析相关文件结构",
            "target_file": "",
            "expected_outcome": "明确需求范围和影响文件",
            "dependencies": [],
        })
        step_id += 1

        if related_files:
            for rf in related_files[:5]:
                file_name = rf.get("file", "")
                steps.append({
                    "id": step_id,
                    "type": "analysis",
                    "title": f"分析文件 {file_name}",
                    "description": f"详细分析 {file_name} 的代码结构和逻辑",
                    "target_file": file_name,
                    "expected_outcome": "了解文件功能和修改点",
                    "dependencies": [1],
                })
                step_id += 1

        if missing_items:
            for item in missing_items[:5]:
                file_name = item.get("file", "未知文件")
                issue = item.get("issue", item.get("expected", ""))
                steps.append({
                    "id": step_id,
                    "type": "modify",
                    "title": f"修改 {file_name}",
                    "description": f"解决问题: {issue}",
                    "target_file": file_name,
                    "expected_outcome": "问题已解决",
                    "dependencies": [s["id"] for s in steps if s["type"] == "analysis"],
                })
                step_id += 1

        steps.append({
            "id": step_id,
            "type": "test",
            "title": "测试验证",
            "description": "测试修改后的功能是否正常工作",
            "target_file": "",
            "expected_outcome": "功能验证通过",
            "dependencies": [s["id"] for s in steps if s["type"] in ["modify", "create"]],
        })
        step_id += 1

        steps.append({
            "id": step_id,
            "type": "review",
            "title": "代码审查",
            "description": "审查修改内容，确保代码质量",
            "target_file": "",
            "expected_outcome": "代码审查通过",
            "dependencies": [step_id - 1],
        })

        plan = {
            "plan_id": plan_id,
            "goal": f"实现需求: {requirement_desc}",
            "project": project_name,
            "requirement_id": requirement_id,
            "total_steps": len(steps),
            "steps": steps,
        }

        return plan

    def save_plan(self, plan: Dict[str, Any]) -> str:
        """保存计划到文件"""
        plan_dir = WORKSPACE / "plans"
        plan_dir.mkdir(parents=True, exist_ok=True)

        plan_path = plan_dir / f"{plan['plan_id']}.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info(f"计划已保存: {plan_path}")
        return str(plan_path)

    def load_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """加载计划"""
        plan_path = WORKSPACE / "plans" / f"{plan_id}.json"
        if plan_path.exists():
            try:
                return json.loads(plan_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.warning(f"加载计划 {plan_id} 失败")
        return None

    def list_plans(self) -> List[Dict[str, Any]]:
        """列出所有计划"""
        plan_dir = WORKSPACE / "plans"
        if not plan_dir.exists():
            return []

        plans = []
        for file in sorted(plan_dir.iterdir(), reverse=True):
            if file.is_file() and file.suffix == ".json":
                try:
                    plan = json.loads(file.read_text(encoding="utf-8"))
                    plans.append({
                        "plan_id": plan.get("plan_id", file.stem),
                        "goal": plan.get("goal", ""),
                        "project": plan.get("project", ""),
                        "requirement_id": plan.get("requirement_id", ""),
                        "total_steps": plan.get("total_steps", 0),
                        "created_at": file.stat().st_mtime,
                    })
                except Exception as e:
                    logger.warning(f"读取计划 {file.name} 失败: {e}")

        return plans

    def generate_plan_summary(self, plan: Dict[str, Any]) -> str:
        """生成计划摘要文本"""
        lines = []
        lines.append(f"## {plan['plan_id']} — 执行计划")
        lines.append(f"\n### 目标")
        lines.append(plan.get("goal", ""))
        lines.append(f"\n### 项目: {plan.get('project', '')}")
        lines.append(f"\n### 需求ID: {plan.get('requirement_id', '')}")
        lines.append(f"\n### 步骤 ({plan.get('total_steps', 0)} 步)")

        for step in plan.get("steps", []):
            type_label = self._get_step_type_label(step.get("type", ""))
            status_icon = "⬜"
            if step.get("status") == "done":
                status_icon = "✅"
            elif step.get("status") == "in_progress":
                status_icon = "🔄"

            lines.append(f"\n{status_icon} **步骤 {step['id']}** ({type_label})")
            lines.append(f"   - 标题: {step.get('title', '')}")
            lines.append(f"   - 描述: {step.get('description', '')}")
            if step.get("target_file"):
                lines.append(f"   - 文件: {step['target_file']}")
            if step.get("dependencies"):
                lines.append(f"   - 依赖: 步骤 {', '.join(map(str, step['dependencies']))}")

        return "\n".join(lines)

    def _get_step_type_label(self, step_type: str) -> str:
        """获取步骤类型标签"""
        for st in self._step_types:
            if st["id"] == step_type:
                return st["name"]
        return step_type
