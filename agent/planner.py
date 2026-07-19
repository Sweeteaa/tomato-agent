"""Planner — 思考规划器

为复杂任务（项目分析、文档理解、多步查询）生成执行计划，
让 agent 从"单步反应式"升级为"Plan + Execute"模式。
"""

import json
import logging
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger("gt_agent.planner")


# 不需要规划的关键词（简单问候/问答）
_SIMPLE_QUERY_PATTERNS = [
    "你好", "您好", "hello", "hi",
    "再见", "拜拜", "bye",
    "谢谢", "thanks",
    "你是谁", "你能做什么", "介绍一下自己",
]


class Planner:
    """规划器 — 生成 Plan + 判断是否需要规划"""

    def __init__(self, client: AsyncOpenAI, model: str, temperature: float = 0.3):
        self.client = client
        self.model = model
        self.temperature = temperature

    async def plan(
        self,
        query: str,
        tools: list[dict],
        project_context: str = "",
        memory_context: str = "",
    ) -> dict:
        """根据用户请求生成执行计划

        Returns:
            {
                "goal": "核心目标",
                "requires_planning": bool,
                "steps": [
                    {"step": 1, "action": "tool_name", "args": {...}, "purpose": "..."}
                ],
                "expected_output": "..."
            }
        """
        # 简单查询跳过规划
        if self._is_simple_query(query):
            return {
                "goal": query,
                "requires_planning": False,
                "use_reasoning": False,
                "steps": [],
                "expected_output": "直接回答",
            }

        prompt = self._build_prompt(query, tools, project_context, memory_context)
        messages = [
            {"role": "system", "content": "你是一个严谨的任务规划器，只输出合法 JSON。"},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            plan = json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning("planner: JSON 解析失败: %s", e)
            return self._fallback_plan(query)
        except Exception as e:
            logger.warning("planner: LLM 调用失败: %s", e)
            return self._fallback_plan(query)

        # 规范化
        plan.setdefault("goal", query)
        plan.setdefault("requires_planning", True)
        plan.setdefault("steps", [])
        plan.setdefault("expected_output", "给出结构化回答")
        plan.setdefault("use_reasoning", False)

        # use_reasoning 启发式兜底：如果模型没返回，复杂长查询默认启用
        if "use_reasoning" not in content:
            plan["use_reasoning"] = self._should_use_reasoning(query, plan)

        # 如果步骤为空，则不需要规划
        if not plan.get("steps"):
            plan["requires_planning"] = False

        # 为 steps 添加序号
        for i, step in enumerate(plan["steps"], start=1):
            step.setdefault("step", i)

        return plan

    def _is_simple_query(self, query: str) -> bool:
        """判断是否为简单查询，不需要规划"""
        query_lower = query.strip().lower()
        # 去除标点后的简短问候/常识问题
        if len(query) <= 20:
            for pattern in _SIMPLE_QUERY_PATTERNS:
                if pattern in query_lower:
                    return True
        return False

    def _should_use_reasoning(self, query: str, plan: dict) -> bool:
        """启发式判断是否需要启用推理模型展示思考链。"""
        if not plan.get("requires_planning"):
            return False
        # 多步骤、项目分析、复杂文档理解等启用推理
        reasoning_keywords = [
            "分析项目", "扫描项目", "项目结构", "需求分析", "代码审查",
            "设计", "架构", "优化", "排查", "调试", "错误定位",
        ]
        query_lower = query.lower()
        if any(kw in query_lower for kw in reasoning_keywords):
            return True
        if len(plan.get("steps", [])) >= 3:
            return True
        return False

    def _build_prompt(
        self,
        query: str,
        tools: list[dict],
        project_context: str,
        memory_context: str,
    ) -> str:
        """构建规划提示词"""
        tool_descriptions = []
        for tool in tools:
            func = tool.get("function", {})
            name = func.get("name", "")
            desc = func.get("description", "")
            tool_descriptions.append(f"- {name}: {desc}")

        tools_str = "\n".join(tool_descriptions) or "（无可用工具）"
        project_str = project_context or "（无当前项目信息）"
        memory_str = memory_context or "（无相关记忆）"

        return f"""请为以下用户请求制定执行计划。

## 用户请求
{query}

## 可用工具
{tools_str}

## 当前项目上下文
{project_str[:1500]}

## 相关记忆
{memory_str[:1000]}

## 规划要求
1. 仅当任务需要多步操作（如项目分析、文档理解、信息收集）时才制定详细计划
2. 如果任务简单（问候、常识问答、直接可回答的问题），返回 requires_planning: false
3. 每个步骤必须对应一个可用工具
4. 步骤应按逻辑顺序排列：先收集信息，再分析，最后总结
5. args 必须是该工具合法的参数

## 输出格式（严格 JSON）
{{
  "goal": "用户请求的核心目标，一句话概括",
  "requires_planning": true,
  "use_reasoning": true,
  "steps": [
    {{
      "step": 1,
      "action": "list_dir",
      "args": {{"path": "", "max_depth": 2}},
      "purpose": "了解项目顶层结构"
    }},
    {{
      "step": 2,
      "action": "read_file",
      "args": {{"path": "package.json"}},
      "purpose": "确认技术栈和依赖"
    }}
  ],
  "expected_output": "最终应生成的内容格式，如：项目结构总结、文档摘要等"
}}

use_reasoning 说明：当任务需要深度推理、多步分析、项目扫描、架构设计、故障排查时设为 true，此时会启用推理模型并展示思考链；简单信息收集设为 false。

如果不需要规划：
{{
  "goal": "...",
  "requires_planning": false,
  "steps": [],
  "expected_output": "直接回答"
}}"""

    def _fallback_plan(self, query: str) -> dict:
        """规划失败时的降级方案"""
        plan = {
            "goal": query,
            "requires_planning": True,
            "steps": [
                {
                    "step": 1,
                    "action": "list_dir",
                    "args": {"path": "", "max_depth": 2},
                    "purpose": "了解当前上下文结构",
                }
            ],
            "expected_output": "根据收集的信息给出结构化回答",
        }
        plan["use_reasoning"] = self._should_use_reasoning(query, plan)
        return plan
