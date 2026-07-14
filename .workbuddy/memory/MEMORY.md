# GT Agent 项目记忆

## 项目概况
- 本地开发助手，核心理念"知识即文件"
- FastAPI + LangGraph (Planner→Executor→Reviewer)
- 阿里云 DashScope (Qwen) 大模型驱动

## 关键发现 (2026-07-14 代码审查)
- 致命安全漏洞：API Key 硬编码、静态文件暴露源码、路径遍历、XSS
- 双工具系统冲突：agent/tools/ 和 app/tools.py 不互通
- Graph 逻辑缺陷：reviewer 总设 is_complete=True，循环永不触发（已修复）
- 大量代码重复：SCAN_IGNORE_DIRS 多处不同定义（已统一到 config.py）、工具逻辑重复（已合并）、防幻觉提示重复（已提取为 ANTI_HALLUCINATION_RULES 常量）、Capability 样板代码（已提取 BaseCapability 基类）
- 性能瓶颈：build_context 每次 rglob 全量扫描（已修复：WorkspaceCache 索引缓存）、同步LLM调用阻塞事件循环（已修复：AsyncOpenAI + async generator + asyncio.to_thread）
- 错误处理反模式：返回错误字符串而非抛异常（已修复：ToolError 异常体系 + executor_node error 分支）
- 日志缺失：全项目无 logging（已修复：logging_config.py + 3 个 logger）

## 已完成的修复 (2026-07-14)
- 双工具系统合并：agent/tools/filesystem.py 统一了 app/tools.py + filesystem_tool.py 的功能
  - read_file/list_dir/search_file 支持绝对路径+相对路径双模式
  - scan_menu_structure 已注册到 registry（之前缺失导致"未知工具"错误）
  - list_dir 新增 recursive + max_depth 参数
  - search_file 新增 keyword + root_path 项目模式
  - 路径遍历防护：写入/删除操作限制在 workspace 内
- 新增 ProjectCapability（agent/tools/project.py）：
  - list_registered_projects / get_project_info / scan_project / list_project_docs / get_project_doc
  - LLM 可直接查询已注册项目和执行深度项目扫描
- app/services 重复代码委托 agent/tools/：
  - memory_service / task_service / workspace_service 的 CRUD 函数委托调用
  - 保留 user_profile / pending_tasks / get_workspace 等独有功能
- app/tools.py 已删除（废弃的僵尸代码）
- app/services/filesystem_tool.py 已删除（功能已在 agent/tools/filesystem.py 重新实现）
- requirements.txt 清理：移除 5 个从未使用的依赖
- 配置管理优化：
  - MAX_STEPS 从 graph_service.py 硬编码 → config.py（可环境变量覆盖）
  - 新增分场景温度：TEMPERATURE_PLANNING=0.1 / TEMPERATURE_CHAT=0.7
  - WORKSPACE 改为绝对路径 resolve()（可环境变量 WORKSPACE_DIR 覆盖）
  - config.py import 顺序按 PEP 8 整理
- LLM 调用效率优化：
  - 移除 AgentState.original_plan_length 冗余字段
  - reviewer 截断阈值从 200 → 500 字符 + 智能截断提示
- 类型安全改善：
  - AgentState TypedDict 泛型参数补全
  - conv_id → Optional[str]
  - chat_with_agent_stream → AsyncGenerator[dict, None] 返回类型标注
- graph_service.py prompt 矛盾修复：明确区分"项目扫描用绝对路径"和"workspace 操作用相对路径"
- SCAN_IGNORE_DIRS 和 SCAN_ALLOWED_EXTENSIONS 统一到 app/config.py
- 最终 registry 共注册 4 个能力（filesystem/memory/document/project）、23 个工具
- planner_node 重复规划修复：
  - planner_node 简化为 pass-through（使用 run_graph_stream 预生成的 plan，不再重复调用 LLM）
  - 移除死代码：_generate_streaming_response、_parse_plan_from_stream、planner_node 文件上传分支和 no-plan fallback
  - _build_planner_prompt 接受可选预计算参数（context/skill_context/cap_desc/user_profile/pending_info）
  - run_graph_stream 预计算共享上下文一次复用，build_context 调用从 2-3 次降到 1 次
- build_context 缓存优化：
  - WorkspaceCache 类：维护 {rel_path → (content, mtime)} 索引，增量更新
  - 首次全量扫描缓存，后续只检查 mtime 变化的文件（32x faster）
  - 30 秒间隔自动全量扫描检测新增文件，被删除文件自动移除
  - search_workspace 也基于缓存索引，零 IO
- reviewer 循环修复：
  - _build_reviewer_prompt 重写：接收完整 execution_trace + step_count + max_steps，输出 revised_plan
  - reviewer_node 三阶段决策：无结果→完成 / MAX_STEPS→强制完成 / LLM 评审→按 is_complete 判断
  - 未完成时设置 revised_plan 回到 executor，清空 execution_results，trace 跨轮累积
  - 三重安全网防无限循环：reviewer_node + _should_continue + run_graph_stream
  - run_graph_stream 多轮修复：跨轮步骤计数、修订计划前端通知、final_plan 用于 pending_task

## 保持现状的服务（不应作为 LLM 工具）
- conversation_service / chat_service — API 编排层
- artifact_service / document_generator_service / requirement_parser_service — 工作流步骤
- project_matcher_service — 工具类
- file_service.build_context — graph_service 内部调用（已缓存优化）

- 错误处理反模式修复：
  - 新建 agent/exceptions.py：ToolError / FileNotFoundError / PathSecurityError / ResourceNotFoundError
  - agent/tools/ 所有 ❌ 返回字符串 → 抛异常（36处）
  - 4个 capability.py + registry "❌ 未知工具" → raise ToolError
  - executor_node 新增 ToolError 专用 except 分支，status:"error" 正确标记
  - memory_service/task_service startswith("❌") → try/except ResourceNotFoundError
- 日志系统添加：
  - 新建 app/logging_config.py：控制台 INFO + 文件 DEBUG（5MB 轮转）
  - app/main.py 启动时调用 setup_logging()
  - gt_agent.graph / gt_agent.chat_router / gt_agent.chat_service 三个 logger
  - executor_node ToolError 分支 logger.warning，Exception 分支 logger.error(exc_info=True)
  - 降低第三方库噪音：httpx/httpcore/openai/uvicorn.access → WARNING

## 待修复
- API Key 硬编码 → 需引入 .env + python-dotenv
- 静态文件暴露源码 → StaticFiles 挂载范围限制
- XSS → marked 设置 sanitize 或使用 DOMPurify
