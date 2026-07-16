"""DocumentWorkflow - 文档和图片分析工作流"""

import asyncio
import re
from pathlib import Path
from typing import Dict, Any, Optional, List

from app.workflows.context import WorkflowContext
from app.workflows.utils import load_project_knowledge, save_document_summary, find_relevant_project, build_project_context
from agent.workflows.project_scan_workflow import run_project_scan
from app.services.requirement_analyzer_service import RequirementAnalyzer
from app.services.code_matcher_service import CodeMatcher
from app.services.completion_analyzer_service import RequirementCompletionAnalyzer
from app.services.plan_generator_service import PlanGenerator
from app.services.task_service import create_execution_task
from app.config import MODEL_NAME, VL_MODEL_NAME, TEMPERATURE_CHAT, DASHSCOPE_API_KEY, WORKSPACE_ID

from openai import AsyncOpenAI

client = AsyncOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=f"https://{WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
)

requirement_analyzer = RequirementAnalyzer()
code_matcher = CodeMatcher()
completion_analyzer = RequirementCompletionAnalyzer()
plan_generator = PlanGenerator()

ANTI_HALLUCINATION_RULES = """## 防幻觉规则（强制遵守）
1. 禁止猜测项目结构、目录内容、文件名
2. 禁止根据需求文档推断文件路径或内容
3. 禁止创建不存在的文件路径
4. 禁止根据目录名称推断业务功能（如不能因目录名包含"data"就推断它是"实验室检查"页面）
5. 当用户要求扫描项目、查看目录结构、分析代码时，必须调用 list_dir / read_file / search_file 工具获取真实结果
6. 扫描项目结构时，**必须先调用 list_dir 工具**获取目录结构信息，建议使用足够的深度（max_depth=5-10）
7. 如果工具没有返回结果，只能回答"无法访问本地文件系统，请检查路径是否正确或提供扫描权限"""


class DocumentWorkflow:
    @staticmethod
    async def run(ctx: WorkflowContext, registry=None):
        """执行文档分析工作流"""
        use_vl = ctx.has_images
        active_model = VL_MODEL_NAME if use_vl else MODEL_NAME
        status_msg = "正在分析上传图片..." if use_vl else "正在分析上传文件..."
        yield {"type": "status", "message": status_msg}

        image_hint = ""
        if ctx.has_images and ctx.images:
            image_names = ", ".join(img["filename"] for img in ctx.images)
            image_hint = f"\n\n## 上传图片\n用户上传了 {len(ctx.images)} 张图片: {image_names}\n图片已附带在消息中，你可以直接看到图片内容。请结合图片和文本内容回答用户问题。"

        target_project_name = None
        target_project_path = None
        project_knowledge = None

        if ctx.query.startswith("项目路径:"):
            rest = ctx.query[5:].strip()
            if '\n' in rest:
                target_project_path = rest[:rest.index('\n')].strip()
            else:
                target_project_path = rest.strip()
            target_project_name = Path(target_project_path).name
        else:
            path_match = re.search(r'(D:/[^\s]+|/[a-zA-Z]/[^\s]+|[a-zA-Z]:\\[^\s]+)', ctx.query)
            if path_match:
                target_project_path = path_match.group(1)
                target_project_name = Path(target_project_path).name

        if target_project_path:
            project_knowledge = load_project_knowledge(target_project_name)
            if project_knowledge:
                yield {"type": "status", "message": f"发现已存在项目知识: {target_project_name}"}
                yield {"type": "status", "message": f"项目框架: {project_knowledge.get('framework', '未知')}, 页面数: {len(project_knowledge.get('pages', []))}"}
            else:
                yield {"type": "status", "message": f"项目 {target_project_name} 没有知识，开始扫描..."}
                async for evt in run_project_scan(target_project_path, registry):
                    yield evt
                    if evt.get('type') == 'project_scan_done':
                        project_knowledge = load_project_knowledge(target_project_name)
                        if project_knowledge:
                            yield {"type": "status", "message": f"项目扫描完成，已加载知识"}
        else:
            target_project_name = ctx.project_name if ctx.project_name else find_relevant_project(ctx.query)
            if target_project_name:
                yield {"type": "status", "message": f"发现已存在项目知识: {target_project_name}"}
                project_knowledge = load_project_knowledge(target_project_name)
                if project_knowledge:
                    yield {"type": "status", "message": f"项目框架: {project_knowledge.get('framework', '未知')}, 页面数: {len(project_knowledge.get('pages', []))}"}

        if not ctx.has_images:
            yield {"type": "status", "message": "正在解析需求文档..."}
            parsed_requirements = requirement_analyzer.parse_requirements(ctx.query, ctx.conv_id or "")

            yield {"type": "status", "message": f"解析出 {parsed_requirements['total_requirements']} 条需求"}

            all_matches = []
            if project_knowledge:
                yield {"type": "status", "message": "正在进行需求代码匹配..."}
                for req in parsed_requirements["requirements"]:
                    matches = code_matcher.match_requirement_to_code(req, project_knowledge)
                    all_matches.append(matches)

                impact_analysis = code_matcher.analyze_impact(all_matches, parsed_requirements["requirements"])
                impact_summary = impact_analysis["summary"]
                requirement_summary = requirement_analyzer.generate_requirement_summary(parsed_requirements)

                yield {"type": "status", "message": "正在进行需求完成度分析..."}
                completion_reports = []
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
                requirement_summary = requirement_analyzer.generate_requirement_summary(parsed_requirements)
                full_response = f"{requirement_summary}\n\n## 注意\n当前 workspace 中未找到项目知识，请先扫描项目以进行代码匹配分析。"

            yield {"type": "token", "content": full_response}

            yield {"type": "status", "message": "正在保存文档总结..."}
            doc_name = f"需求分析_{parsed_requirements.get('total_requirements', 0)}条需求"
            await asyncio.to_thread(save_document_summary, doc_name, full_response, target_project)
            yield {"type": "status", "message": f"文档总结已保存到 {'项目' + target_project if target_project else '全局'} docs 目录"}
        else:
            direct_prompt = f"""你是 GT Agent，一个本地智能开发助手。

{ANTI_HALLUCINATION_RULES}
6. 扫描项目结构时，必须先调用 scan_menu_structure 工具获取菜单和路由信息

## 路径规则
- 扫描用户项目: 使用绝对路径，如 'D:/projects/xxx'
- workspace 内操作: 使用相对路径，如 'skill/hello.md'

知识库上下文: {ctx.context}
相关技能: {ctx.skill_context}
可用能力: {ctx.cap_desc}
{image_hint}

用户已上传文件，文件内容已包含在问题中，请直接根据文件内容回答用户问题：
{ctx.query}"""

            yield {"type": "status", "message": "正在生成回答..."}

            user_content = [{"type": "text", "text": direct_prompt}]
            for img in ctx.images:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{img['mime']};base64,{img['data']}"}
                })
            messages = [
                {"role": "system", "content": "你是一个专业的开发助手，具备图片理解能力"},
                {"role": "user", "content": user_content}
            ]

            full_response = ""

            async for chunk in await client.chat.completions.create(
                model=active_model,
                messages=messages,
                temperature=TEMPERATURE_CHAT,
                stream=True
            ):
                if chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_response += token
                    yield {"type": "token", "content": token}

            yield {"type": "status", "message": "正在保存文档总结..."}
            doc_name = f"图片分析_{len(ctx.images)}张图片"
            await asyncio.to_thread(save_document_summary, doc_name, full_response, target_project)
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
