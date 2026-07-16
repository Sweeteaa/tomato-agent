"""RequirementWorkflow - 需求分析工作流"""

import asyncio
from typing import Dict, Any

from app.workflows.context import WorkflowContext
from app.services.requirement_analyzer_service import RequirementAnalyzer
from app.services.code_matcher_service import CodeMatcher
from app.services.completion_analyzer_service import RequirementCompletionAnalyzer
from app.services.plan_generator_service import PlanGenerator
from app.services.task_service import create_execution_task
from app.services.graph_service import _load_project_knowledge, _save_document_summary


class RequirementWorkflow:
    @staticmethod
    async def run(ctx: WorkflowContext):
        """执行需求分析工作流"""
        yield {"type": "status", "message": "正在解析需求文档..."}
        parsed_requirements = RequirementAnalyzer().parse_requirements(ctx.query, ctx.conv_id or "")

        yield {"type": "status", "message": f"解析出 {parsed_requirements['total_requirements']} 条需求"}

        project_knowledge = None
        target_project = ctx.project_name
        all_matches = []

        if target_project:
            project_knowledge = _load_project_knowledge(target_project)

        if project_knowledge:
            yield {"type": "status", "message": "正在进行需求代码匹配..."}
            for req in parsed_requirements["requirements"]:
                matches = CodeMatcher().match_requirement_to_code(req, project_knowledge)
                all_matches.append(matches)

            impact_analysis = CodeMatcher().analyze_impact(all_matches, parsed_requirements["requirements"])
            impact_summary = impact_analysis["summary"]
            requirement_summary = RequirementAnalyzer().generate_requirement_summary(parsed_requirements)

            yield {"type": "status", "message": "正在进行需求完成度分析..."}
            completion_reports = []
            completion_analyzer = RequirementCompletionAnalyzer()
            for idx, req in enumerate(parsed_requirements["requirements"]):
                req_matches = all_matches[idx] if idx < len(all_matches) else []
                async for evt in completion_analyzer.analyze_completion(
                    req, project_knowledge, req_matches, project_knowledge.get("project_path", "")
                ):
                    if evt.get("status"):
                        yield {"type": "status", "message": evt["status"]}
                    elif evt.get("done"):
                        completion_report = completion_analyzer.generate_completion_report(evt["done"])
                        completion_reports.append(completion_report)

            completion_summary = "\n\n".join(completion_reports)

            full_response = f"{requirement_summary}\n\n{impact_summary}\n\n# 需求完成度分析\n{completion_summary}"

            yield {"type": "status", "message": "正在生成执行计划..."}
            plan_generator = PlanGenerator()
            plan_summaries = []
            for idx, req in enumerate(parsed_requirements["requirements"]):
                req_matches = all_matches[idx] if idx < len(all_matches) else []
                completion_result = None
                for evt in completion_analyzer.analyze_completion(
                    req, project_knowledge, req_matches, project_knowledge.get("project_path", "")
                ):
                    if evt.get("done"):
                        completion_result = evt["done"]
                        break

                if completion_result and completion_result.get("completion_rate", 100) < 100:
                    plan = await plan_generator.generate_plan(req, completion_result, project_knowledge)
                    plan_generator.save_plan(plan)

                    task_result = await asyncio.to_thread(create_execution_task, plan)

                    plan_summary = plan_generator.generate_plan_summary(plan)
                    plan_summaries.append(plan_summary)

            if plan_summaries:
                plans_text = "\n\n".join(plan_summaries)
                full_response += f"\n\n# 执行计划\n{plans_text}"
                yield {"type": "token", "content": f"\n\n# 执行计划\n{plans_text}"}

        else:
            requirement_summary = RequirementAnalyzer().generate_requirement_summary(parsed_requirements)
            full_response = f"{requirement_summary}\n\n## 注意\n当前 workspace 中未找到项目知识，请先扫描项目以进行代码匹配分析。"

        yield {"type": "token", "content": full_response}

        yield {"type": "status", "message": "正在保存文档总结..."}
        doc_name = f"需求分析_{parsed_requirements.get('total_requirements', 0)}条需求"
        await asyncio.to_thread(_save_document_summary, doc_name, full_response, target_project)
        yield {"type": "status", "message": f"文档总结已保存到 {'项目' + target_project if target_project else '全局'} docs 目录"}

        yield {
            "type": "done",
            "response": full_response,
            "context_used": len(ctx.context) > 0,
            "tool_executions": [],
            "plan": [],
            "plan_steps": 0,
            "execution_trace": [],
            "is_complete": True,
            "conversation_id": ctx.conv_id or "",
            "project_context": {"project_name": target_project, "has_knowledge": project_knowledge is not None} if target_project else {}
        }
