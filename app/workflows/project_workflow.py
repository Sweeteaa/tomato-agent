"""ProjectWorkflow - 项目扫描工作流"""

import re
from pathlib import Path

from app.workflows.context import WorkflowContext
from agent.workflows.project_scan_workflow import run_project_scan, is_project_scan_query, extract_project_path, load_project_knowledge
from app.services.conversation_project_memory import set_conversation_project


class ProjectWorkflow:
    @staticmethod
    async def run(ctx: WorkflowContext, registry=None):
        """执行项目扫描工作流"""
        provided_project_path = None
        provided_project_name = None
        
        project_path_prefix_match = re.match(r'^项目路径:\s*(\S+)(?:\s*\n\n(.+))?$', ctx.query, re.DOTALL)
        if project_path_prefix_match:
            provided_project_path = project_path_prefix_match.group(1)
            remaining_query = (project_path_prefix_match.group(2) or "").strip()
            provided_project_name = Path(provided_project_path).name
            if ctx.conv_id:
                set_conversation_project(ctx.conv_id, provided_project_name, provided_project_path)
                yield {"type": "status", "message": f"已设置项目上下文: {provided_project_name}"}
            ctx.project_name = provided_project_name
            ctx.project_path = provided_project_path
            ctx.query = remaining_query
        else:
            path_match = re.search(r'(D:/\S+|/Users/\S+|/home/\S+|/[a-zA-Z][a-zA-Z0-9_-]*/\S+|[a-zA-Z]:\\\S+|~/\S+)', ctx.query)
            if path_match:
                provided_project_path = path_match.group(1)
                provided_project_name = Path(provided_project_path).name
                if ctx.conv_id:
                    set_conversation_project(ctx.conv_id, provided_project_name, provided_project_path)
                    yield {"type": "status", "message": f"已设置项目上下文: {provided_project_name}"}
                ctx.project_name = provided_project_name
                ctx.project_path = provided_project_path

        need_scan = False
        project_path = None
        project_name = None

        if is_project_scan_query(ctx.query):
            need_scan = True
            project_path = extract_project_path(ctx.query) or provided_project_path
        elif provided_project_path:
            existing_knowledge = load_project_knowledge(provided_project_name)
            if not existing_knowledge:
                need_scan = True
                project_path = provided_project_path
            else:
                yield {"type": "status", "message": f"项目 {provided_project_name} 已有知识，跳过扫描"}

        if need_scan and project_path:
            async for evt in run_project_scan(project_path, registry):
                yield evt
                if evt.get('type') == 'project_scan_done' and evt.get('project_context'):
                    project_name = evt['project_context'].get('project_name')
                    project_path = evt['project_context'].get('project_path')
                    if ctx.conv_id:
                        set_conversation_project(ctx.conv_id, project_name, project_path)
                        yield {"type": "status", "message": f"已将 {project_name} 设置为当前对话项目"}

        final_project_name = ctx.project_name if ctx.project_name else (project_name if project_name else None)
        final_project_path = ctx.project_path if ctx.project_path else (project_path if project_path else None)

        if not ctx.query and need_scan:
            if final_project_name:
                project_knowledge = load_project_knowledge(final_project_name)
                if project_knowledge:
                    summary = project_knowledge.get("summary", "项目扫描完成")
                    yield {"type": "done", "response": summary, "context_used": True,
                           "tool_executions": [], "plan": [], "plan_steps": 0,
                           "execution_trace": [], "is_complete": True,
                           "conversation_id": ctx.conv_id or "",
                           "project_context": {"project_name": final_project_name, "has_knowledge": True}}
                    return

        if final_project_name or final_project_path:
            yield {"type": "project_updated", "project_name": final_project_name, "project_path": final_project_path}
