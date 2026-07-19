"""Memory Extractor — 每轮结束判断是否保存有价值的知识

输入: goal + trajectory（执行轨迹）
判断: 有没有值得保存的经验/模式/解决方案？
输出: 保存到 episodic/ 或 semantic/ 的 markdown 文件

重构后：
  - 解耦 AgentState 依赖，直接接收 goal + trajectory
  - 新增 extract_and_save_async 异步版本
  - 保留 extract_and_save 同步版本兼容
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from app.config import MODEL_NAME, TEMPERATURE_PLANNING, WORKSPACE

logger = logging.getLogger("gt_agent.memory.extractor")

# 记忆存储根目录
MEMORY_ROOT = WORKSPACE / "memory"
EPISODIC_DIR = MEMORY_ROOT / "episodic"
SEMANTIC_DIR = MEMORY_ROOT / "semantic"


def _ensure_dirs():
    """确保记忆目录存在"""
    EPISODIC_DIR.mkdir(parents=True, exist_ok=True)
    SEMANTIC_DIR.mkdir(parents=True, exist_ok=True)


def build_extractor_prompt(goal: str, trajectory: list) -> str:
    """构建 Memory Extractor 的提示词"""

    if trajectory:
        traj_lines = []
        for i, step in enumerate(trajectory):
            thought = step.get("thought", "")
            action = step.get("action", {})
            obs = step.get("observation", {})
            obs_text = obs.get("findings", "") or str(obs.get("result", ""))
            if len(obs_text) > 500:
                obs_text = obs_text[:500] + "..."
            traj_lines.append(f"  {i+1}. 思考: {thought} → 动作: {json.dumps(action, ensure_ascii=False)} → 观察: {obs_text}")
        traj_str = "\n".join(traj_lines)
    else:
        traj_str = "  （无执行记录）"

    return f"""你是 GT Agent 的记忆提取器。分析本次执行轨迹，判断是否有值得长期保存的知识。

## 用户目标
{goal}

## 执行轨迹
{traj_str}

## 判断标准（按优先级）

### 必须保存的情况
1. **项目知识**: 用户扫描/分析了某个项目，发现了技术栈、架构、页面结构、关键文件路径
2. **文档理解**: 用户提供了文档，提取了关键信息（需求、接口、数据结构等）
3. **问题解决**: 本次解决了什么具体问题？问题→原因→解决方案
4. **技术发现**: 发现了通用模式/最佳实践/技术知识

### 不需要保存的情况
- 简单问候、闲聊
- 简单的文件列表查看
- 没有实质性发现的查询

## 输出格式（严格 JSON）
如果值得保存：
{{
  "should_save": true,
  "episodic": {{
    "filename": "login_bug_fix.md",
    "content": "# 问题标题\n\n问题: ...\n原因: ...\n解决: ..."
  }},
  "semantic": {{
    "filename": "vue_project_architecture.md",
    "content": "# 项目知识标题\n\n- 技术栈: ...\n- 架构: ...\n- 关键文件: ..."
  }}
}}

如果不值得保存：
{{
  "should_save": false,
  "episodic": null,
  "semantic": null
}}

注意:
- episodic 和 semantic 至少有一个非 null（当 should_save=true 时）
- 如果是项目分析，优先保存到 semantic（项目知识是长期有效的）
- filename 不要加日期前缀（代码会自动加）
- content 用 markdown 格式，结构清晰"""


def _do_extract_and_save(goal: str, trajectory: list) -> dict:
    """同步执行记忆提取和保存（内部实现）"""
    from openai import OpenAI
    from app.config import DASHSCOPE_API_KEY, WORKSPACE_ID

    # 无轨迹或只有一步简单操作，跳过
    if len(trajectory) < 2:
        logger.debug("extractor: 轨迹太短，跳过记忆提取")
        return {}

    prompt = build_extractor_prompt(goal, trajectory)
    messages = [
        {"role": "system", "content": "你是 GT Agent 的记忆提取器，只输出 JSON 格式"},
        {"role": "user", "content": prompt},
    ]

    try:
        client = OpenAI(
            api_key=DASHSCOPE_API_KEY,
            base_url=f"https://{WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        )
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=TEMPERATURE_PLANNING,
            response_format={"type": "json_object"},
        )
        result = json.loads(completion.choices[0].message.content)
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("extractor: JSON 解析失败 (%s)", e)
        return {}
    except Exception as e:
        logger.warning("extractor: LLM 调用失败 (%s)", e)
        return {}

    should_save = result.get("should_save", False)
    if not should_save:
        logger.info("extractor: 本次轨迹不值得保存")
        return {}

    _ensure_dirs()
    today = datetime.now().strftime("%Y%m%d")
    saved = []

    # 保存情景记忆
    episodic = result.get("episodic")
    if episodic and episodic.get("content"):
        filename = f"{today}_{episodic.get('filename', 'note.md')}"
        filepath = EPISODIC_DIR / filename
        filepath.write_text(episodic["content"], encoding="utf-8")
        saved.append(f"episodic/{filename}")
        logger.info("extractor: 保存情景记忆 → %s", filename)

    # 保存语义记忆
    semantic = result.get("semantic")
    if semantic and semantic.get("content"):
        filename = semantic.get("filename", "pattern.md")
        filepath = SEMANTIC_DIR / filename
        # 语义记忆是追加模式（同一文件可能多次更新）
        if filepath.exists():
            existing = filepath.read_text(encoding="utf-8")
            filepath.write_text(existing + "\n\n---\n\n" + semantic["content"], encoding="utf-8")
        else:
            filepath.write_text(semantic["content"], encoding="utf-8")
        saved.append(f"semantic/{filename}")
        logger.info("extractor: 保存语义记忆 → %s", filename)

    if saved:
        logger.info("extractor: 共保存 %d 条记忆: %s", len(saved), saved)

    return {}


def extract_and_save_async(goal: str, trajectory: list) -> dict:
    """异步友好的记忆提取（实际是同步函数，由调用方通过 asyncio.to_thread 包装）

    Args:
        goal: 用户目标
        trajectory: 执行轨迹列表

    Returns:
        空字典（仅副作用写入文件）
    """
    return _do_extract_and_save(goal, trajectory)


# 保留旧接口兼容
def extract_and_save(goal: str, trajectory: list) -> dict:
    """同步版本 — 兼容旧调用"""
    return _do_extract_and_save(goal, trajectory)


def list_episodic_memories() -> list:
    """列出所有情景记忆"""
    _ensure_dirs()
    memories = []
    for f in sorted(EPISODIC_DIR.glob("*.md"), reverse=True):
        memories.append({"filename": f.name, "path": str(f)})
    return memories


def list_semantic_memories() -> list:
    """列出所有语义记忆"""
    _ensure_dirs()
    memories = []
    for f in sorted(SEMANTIC_DIR.glob("*.md")):
        memories.append({"filename": f.name, "path": str(f)})
    return memories
