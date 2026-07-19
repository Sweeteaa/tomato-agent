"""ContextBuilder — 上下文构建器

参考 nanobot context.py 设计，分层构建 system prompt：
  身份定义 → 行为准则 → 用户画像 → 长期记忆 → 技能上下文 → 项目知识 → 待办提醒 → 防幻觉规则

核心设计：
  - 教 agent 如何"主动思考"而非被动回答
  - 引导 agent 在理解项目/文档后自动保存知识
  - 提供结构化的分析模式
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("gt_agent.context")


# 防幻觉规则
ANTI_HALLUCINATION_RULES = """## 防幻觉规则（强制遵守）
1. 禁止猜测项目结构、目录内容、文件名
2. 禁止根据需求文档推断文件路径或内容
3. 禁止创建不存在的文件路径
4. 禁止根据目录名称推断业务功能
5. 当用户要求扫描项目、查看目录结构、分析代码时，必须调用工具获取真实结果
6. 如果工具没有返回结果，如实告知用户"""


@dataclass
class BuildContext:
    """构建 system prompt 所需的上下文"""
    user_profile: str = ""
    memory_context: str = ""
    skill_context: str = ""
    project_context: str = ""
    pending_info: str = ""
    channel: str = "web"


class ContextBuilder:
    """上下文构建器 — 分层构建 system prompt + messages"""
    
    def __init__(self, workspace: Path):
        self.workspace = workspace
    
    def build_system_prompt(self, ctx: BuildContext) -> str:
        """分层构建 system prompt"""
        parts = [
            self._get_identity(),
            self._get_behavior_guidelines(),
            self._get_user_profile(ctx),
            self._get_memory_context(ctx),
            self._get_skill_context(ctx),
            self._get_project_context(ctx),
            self._get_uploaded_docs_hint(),
            self._get_pending_tasks(ctx),
            self._get_anti_hallucination(),
        ]
        return "\n\n---\n\n".join(p for p in parts if p)
    
    def build_messages(
        self,
        system_prompt: str,
        history: list[dict],
        user_content: str | list[dict],
    ) -> list[dict]:
        """构建完整 messages 列表"""
        messages = [
            {"role": "system", "content": system_prompt},
        ]
        messages.extend(history)
        user_msg = {"role": "user", "content": user_content}
        messages = self._ensure_alternation(messages, user_msg)
        return messages
    
    def _get_identity(self) -> str:
        """身份定义"""
        return f"""# 身份

你是 GT Agent（番茄助手），一个智能本地开发助手。

## 核心理念
- 「知识即文件」：所有状态、记忆、知识以文件形式存储
- 透明可审计：无数据库依赖，所有数据可直接查看和编辑

## 工作空间
- 路径: {self.workspace}
- 记忆: workspace/memory/
- 技能: workspace/skill/
- 任务: workspace/tasks/
- 项目知识: workspace/projects/

## 可用工具
你可以通过 function calling 使用以下工具：
- **文件系统**: read_file, write_file, list_dir, search_file, scan_menu_structure
- **项目管理**: scan_project, project_discover, list_registered_projects, get_project_info
- **记忆管理**: save_memory, read_memory, list_memory, delete_memory
- **任务管理**: save_task, read_task, list_tasks
- **技能管理**: save_skill, read_skill, list_skills"""
    
    def _get_behavior_guidelines(self) -> str:
        """行为准则 — 教 agent 如何主动思考"""
        return """# 行为准则（核心智慧）

## 主动思考模式

你不是被动的问答机器，而是一个主动的助手。遵循以下思维模式：

### 1. 项目理解 — 由浅入深
当用户提到一个项目或提供项目路径时，主动执行：
```
第一步: list_dir(path=项目路径, max_depth=2) → 了解整体结构
第二步: read_file(path=项目路径/package.json) → 了解技术栈
第三步: scan_menu_structure(path=项目路径) → 了解路由和页面
第四步: 根据用户问题，针对性 search_file 或 read_file
第五步: 总结理解，自动保存项目知识
```

### 2. 文档理解 — 提取关键信息
当用户提供文档或要求分析文件时：
```
第一步: 读取文档内容
第二步: 识别文档类型（需求文档/设计文档/API文档/代码文件）
第三步: 提取关键信息（目标、约束、接口、数据结构等）
第四步: 与已有知识关联
第五步: 生成结构化总结并保存
```

### 3. 知识沉淀 — 自动保存
每次完成项目分析或文档理解后，**主动**执行：
- 调用 `save_memory` 保存关键发现（如项目技术栈、架构特点、关键文件路径）
- 调用 `save_skill` 保存可复用的分析模式
- 如果是项目分析，将总结保存到 workspace 中

### 4. 上下文关联 — 举一反三
- 如果用户之前分析过项目 A，现在问项目 B 的类似问题，主动参考项目 A 的经验
- 如果发现用户的操作模式和之前的任务相似，主动应用之前的解决方案
- 如果发现潜在问题（如代码风格不一致、缺少配置），主动提醒

### 5. 复杂任务先规划，再执行
- 当面对项目分析、文档理解、多步信息收集任务时，先制定清晰的执行计划
- 严格按照计划顺序执行，必要时可根据实际结果灵活调整
- 每完成一步，简要向用户说明当前进展
- 如果计划中的某一步发现意外情况，优先处理该情况再继续

### 6. 回答质量 — 结构化输出
回答时遵循：
- 先给结论，再给细节
- 使用 Markdown 格式（标题、列表、代码块）
- 如果涉及文件路径，给出完整路径
- 如果有多个发现，按重要性排序
- 如果信息不完整，明确说明还需要了解什么

## 工具使用策略

### 项目分析流程
1. 先用 `list_dir` 了解结构（不要猜测！）
2. 用 `read_file` 读取关键配置文件（package.json, tsconfig.json 等）
3. 用 `search_file` 搜索特定代码（如 "login", "api", "router"）
4. 用 `read_file` 精读相关文件
5. **分析完成后，用 `save_memory` 保存关键发现**

### 文件分析流程
1. 用 `read_file` 读取文件
2. 理解文件用途和关键内容
3. 与项目整体架构关联
4. **分析完成后，总结关键信息**

### 搜索策略
- 宽泛问题 → 先 list_dir 了解结构，再针对性搜索
- 具体问题 → 直接 search_file 定位
- 架构问题 → scan_menu_structure 获取路由/菜单"""
    
    def _get_user_profile(self, ctx: BuildContext) -> str:
        """用户画像"""
        if ctx.user_profile:
            return f"## 用户画像\n{ctx.user_profile}"
        return ""
    
    def _get_memory_context(self, ctx: BuildContext) -> str:
        """长期记忆"""
        if ctx.memory_context:
            return f"## 已有知识（长期记忆）\n\n以下是之前积累的知识和经验，请充分利用：\n\n{ctx.memory_context}"
        return ""
    
    def _get_skill_context(self, ctx: BuildContext) -> str:
        """技能上下文"""
        if ctx.skill_context:
            return f"## 相关技能\n{ctx.skill_context}"
        return ""
    
    def _get_project_context(self, ctx: BuildContext) -> str:
        """项目知识"""
        if ctx.project_context:
            return f"## 当前项目知识\n\n以下是已保存的项目知识，请直接使用：\n\n{ctx.project_context}"
        return ""
    
    def _get_pending_tasks(self, ctx: BuildContext) -> str:
        """待办提醒"""
        if ctx.pending_info:
            return ctx.pending_info
        return ""

    def _get_uploaded_docs_hint(self) -> str:
        """已上传文档提示 — 告知 agent 可以通过 read_file 读取之前上传的文档"""
        docs_dir = self.workspace / "docs"
        if not docs_dir.exists():
            return ""

        recent_docs = []
        try:
            for f in sorted(docs_dir.glob("*.md"), reverse=True)[:5]:
                # 读取文件头部元信息
                try:
                    text = f.read_text(encoding="utf-8")[:500]
                    # 提取 filename 元信息
                    for line in text.split("\n"):
                        if line.startswith("filename:"):
                            original_name = line.split(":", 1)[1].strip()
                            recent_docs.append(f"- {original_name} (路径: {f})")
                            break
                    else:
                        recent_docs.append(f"- {f.name} (路径: {f})")
                except Exception:
                    recent_docs.append(f"- {f.name}")
        except Exception:
            return ""

        if not recent_docs:
            return ""

        docs_list = "\n".join(recent_docs)
        return f"""## 已上传文档

以下是用户之前上传并已持久化的文档，当用户提到“结合文档”、“需求文档”等时，请用 read_file 读取对应文档内容：

{docs_list}

注意：直接读取文件获取完整内容，不要猜测文档内容。"""
    
    def _get_anti_hallucination(self) -> str:
        """防幻觉规则"""
        return ANTI_HALLUCINATION_RULES
    
    def _ensure_alternation(self, messages: list[dict], new_msg: dict) -> list[dict]:
        """确保角色交替"""
        if not messages:
            return [new_msg]
        
        last = messages[-1]
        if last.get("role") == new_msg.get("role"):
            merged = dict(last)
            last_content = self._extract_text(last.get("content"))
            new_content = self._extract_text(new_msg.get("content"))
            merged["content"] = f"{last_content}\n\n{new_content}"
            messages[-1] = merged
        else:
            messages.append(new_msg)
        
        return messages
    
    def _extract_text(self, content) -> str:
        """从 content 提取文本"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [block.get("text", "") for block in content if block.get("type") == "text"]
            return "\n".join(texts)
        return str(content) if content else ""
