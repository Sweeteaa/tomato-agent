# GT Agent 项目架构文档

> 生成时间：2026-07-15  
> 项目定位：本地开发助手，核心理念「知识即文件」

---

## 一、项目概况

| 维度 | 说明 |
|------|------|
| **项目名称** | GT Agent（番茄助手） |
| **核心定位** | 本地开发助手，所有状态/记忆/知识以文件形式存储 |
| **技术栈** | FastAPI + LangGraph + AsyncOpenAI (DashScope/Qwen) |
| **数据持久化** | 文件系统（JSON + Markdown），无数据库依赖 |
| **Python 版本** | 3.10+ |
| **入口文件** | `app.py` → `app/main.py` |
| **启动命令** | `python app.py` 或 `uvicorn app.main:app --reload` |
| **访问地址** | http://localhost:8000 |

### 依赖清单 (requirements.txt)

| 依赖 | 版本 | 用途 |
|------|------|------|
| fastapi | 0.115.0 | Web 框架 |
| uvicorn | 0.33.0 | ASGI 服务器 |
| python-multipart | 0.0.12 | 文件上传支持 |
| aiofiles | 24.1.0 | 异步文件操作 |
| python-dateutil | 2.9.0 | 日期处理 |
| openai | >=1.58.1 | OpenAI SDK（兼容 DashScope） |
| langgraph | 0.2.36 | 多节点工作流编排 |
| openpyxl | 3.1.5 | Excel 文件处理 |
| python-docx | 1.1.2 | Word 文件处理 |
| pillow | 10.4.0 | 图片处理与压缩 |

---

## 二、架构总览

```
tomato-agent/
├── app.py                     # 启动入口（uvicorn 包装）
├── index.html                 # 前端页面（Tailwind CSS + marked.js + SSE）
├── requirements.txt           # Python 依赖
├── PLAN.md                    # 项目设计文档
├── README.md                  # 项目说明
│
├── agent/                     # 【能力层】Agent 核心模块
│   ├── exceptions.py          # 统一异常体系 (ToolError)
│   ├── capabilities/          # 能力模块（4 个）
│   ├── registry/              # 能力注册中心
│   ├── skill_manager/         # 技能管理器
│   ├── skills/                # 技能库（Markdown 格式）
│   └── tools/                 # 工具实现（4 个模块，23 个工具）
│
├── app/                       # 【应用层】FastAPI 应用
│   ├── main.py                # 应用入口（路由注册 + 静态文件）
│   ├── config.py              # 配置中心
│   ├── logging_config.py      # 日志配置
│   ├── models/                # Pydantic 数据模型
│   ├── routes/                # API 路由（9 个模块）
│   └── services/              # 业务服务（14 个模块）
│
└── workspace/                 # 【数据层】运行时数据
    ├── conversations/         # 对话记录（JSON）
    ├── memory/                # 长期记忆（Markdown）
    ├── tasks/                 # 工作任务（Markdown）
    ├── projects/              # 项目知识文档
    ├── project_registry/      # 项目注册表（JSON + 缓存）
    ├── artifacts/             # 制品输出
    ├── uploads/               # 用户上传文件
    └── logs/                  # 运行日志
```

### 四层架构关系

```
前端层 (index.html)
    ↕ HTTP / SSE
应用层 (app/) — FastAPI 路由 + 服务编排
    ↕ 调用
能力层 (agent/) — 工具注册 + 执行
    ↕ 读写
数据层 (workspace/) — 文件持久化
```

---

## 三、核心引擎：LangGraph 工作流

**文件**：`app/services/graph_service.py`（约 450+ 行，项目核心）

### 3.1 状态定义 (AgentState)

```python
class AgentState(TypedDict):
    messages: list[str]           # 对话消息列表
    plan: list[dict]              # 执行计划（步骤列表）
    execution_results: list[dict] # 当前轮执行结果
    execution_trace: list[dict]   # 跨轮执行轨迹（累积）
    review_feedback: str          # 审查反馈
    is_complete: bool             # 是否完成
    revised_plan: list[dict]      # 修订计划（未完成时）
    conv_id: Optional[str]        # 对话 ID
    step_count: int               # 步骤计数
```

### 3.2 三节点循环

| 节点 | 函数 | 职责 | 温度 |
|------|------|------|------|
| **Planner** | `planner_node` | 分析用户问题，生成执行计划（JSON 步骤列表） | 0.1（确定性） |
| **Executor** | `executor_node` | 按计划调用 registry 工具，记录执行轨迹 | — |
| **Reviewer** | `reviewer_node` | 评审执行结果，三阶段决策（完成/强制完成/修订） | 0.1 |

### 3.3 工作流拓扑

```
entry → planner → executor → reviewer → _should_continue
                                              ├── True (is_complete) → END
                                              ├── True (step_count >= MAX_STEPS) → END
                                              └── False → executor (循环)
```

### 3.4 关键机制

| 机制 | 实现说明 |
|------|---------|
| **防幻觉规则** | `ANTI_HALLUCINATION_RULES` 常量，7 条强制规则注入 Planner prompt |
| **用户画像注入** | Planner 自动读取 `memory/user_profile.md` 注入上下文 |
| **技能上下文** | `SkillManager.get_skill_context()` 关键词匹配相关技能 |
| **待办提醒** | 自动检查 `tasks/pending.md`，未完成任务提醒用户 |
| **偏好提取** | 完成后自动从对话中提取技术栈/技能/代码风格偏好，更新用户画像 |
| **三重安全网** | reviewer_node + _should_continue + run_graph_stream 防无限循环 |
| **MemorySaver** | LangGraph 检查点，支持状态恢复 |
| **流式输出** | 通过 SSE 事件流实时返回 status/plan/trace/token/done 事件 |

### 3.5 LLM 客户端

```python
client = AsyncOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=f"https://{WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
)
# 主模型: qwen-plus | 视觉模型: qwen-vl-plus
```

---

## 四、能力层详解 (agent/)

### 4.1 统一异常体系

**文件**：`agent/exceptions.py`

```
ToolError (基类)
  ├── FileNotFoundError       — 文件/目录不存在
  ├── PathSecurityError       — 路径遍历攻击或权限不足
  └── ResourceNotFoundError   — 通用资源不存在（记忆/技能/任务/项目）
```

所有工具错误抛出异常而非返回错误字符串，由 `executor_node` 统一捕获。

### 4.2 能力注册中心

**文件**：`agent/registry/capability_registry.py`

- `CapabilityRegistry` 类：统一管理所有能力
- `create_default_registry()` 工厂函数：注册 4 个内置能力
- 接口：`get_all_tools()` / `get_all_handlers()` / `execute_tool()` / `list_capabilities()`

### 4.3 能力基类

**文件**：`agent/capabilities/base.py`

- `BaseCapability` 通过 `importlib.import_module()` 延迟加载工具模块
- 子类只需声明 `name` / `description` / `_tool_module` 三个类属性
- 避免 import 循环依赖

### 4.4 四大能力 × 23 个工具

#### 能力 1：文件系统 (filesystem)

**文件**：`agent/capabilities/filesystem/capability.py` + `agent/tools/filesystem.py`

| 工具 | 功能 | 安全特性 |
|------|------|---------|
| `read_file` | 读取文件内容 | 支持绝对路径 + workspace 相对路径 |
| `write_file` | 写入文件内容 | 写操作限制在 workspace 内 |
| `delete_file` | 删除文件 | 删除操作限制在 workspace 内 |
| `append_file` | 追加文件内容 | 写操作限制在 workspace 内 |
| `list_dir` | 列出目录内容 | 支持 recursive + max_depth 参数 |
| `search_file` | 搜索文件内容 | 支持 keyword + root_path 项目模式 |
| `create_folder` | 创建目录 | 写操作限制在 workspace 内 |
| `scan_menu_structure` | 扫描项目菜单结构 | 支持绝对路径深度扫描 |

**路径安全**：`_resolve_path()` 区分读操作（允许绝对路径）与写操作（`restrict_to_workspace=True`），检测路径遍历攻击。

#### 能力 2：记忆管理 (memory)

**文件**：`agent/capabilities/memory/capability.py` + `agent/tools/memory.py`

| 工具 | 功能 |
|------|------|
| `save_memory` | 保存长期记忆（Markdown） |
| `read_memory` | 读取指定记忆 |
| `list_memory` | 列出所有记忆 |
| `delete_memory` | 删除记忆 |

#### 能力 3：文档管理 (document)

**文件**：`agent/capabilities/document/capability.py` + `agent/tools/document.py`

| 工具 | 功能 |
|------|------|
| `save_skill` | 保存技能文档 |
| `read_skill` | 读取技能文档 |
| `list_skills` | 列出所有技能 |
| `save_task` | 保存任务文档 |
| `read_task` | 读取任务文档 |
| `list_tasks` | 列出所有任务 |

#### 能力 4：项目管理 (project)

**文件**：`agent/capabilities/project/capability.py` + `agent/tools/project.py`

| 工具 | 功能 |
|------|------|
| `list_registered_projects` | 列出已注册项目 |
| `get_project_info` | 获取项目详情 |
| `scan_project` | 深度扫描项目结构（自动检测框架） |
| `list_project_docs` | 列出项目文档 |
| `get_project_doc` | 读取项目文档内容 |

### 4.5 技能管理器

**文件**：`agent/skill_manager/manager.py`

- 技能文档 CRUD（操作 `workspace/skill/*.md`）
- `get_skill_context(query)` 基于关键词匹配检索相关技能上下文
- 内置技能：`document_generate.md`（文档生成）、`vue_analysis.md`（Vue 项目分析）

### 4.6 设计模式

```
graph_service.py (编排层)
       │ 调用
       ▼
CapabilityRegistry (注册中心)
       │ 聚合
       ▼
BaseCapability (能力基类) × 4
       │ 延迟加载 (importlib)
       ▼
tools/*.py (工具实现层) × 4
  ├── tool_definitions  → OpenAI function calling 格式
  └── tool_handlers     → 函数映射 dict
```

---

## 五、应用层详解 (app/)

### 5.1 应用入口

**文件**：`app/main.py`

- 创建 FastAPI 实例 (title="GT Agent")
- 初始化日志系统 (`setup_logging()`)
- 挂载静态文件
- 注册全部 9 个路由模块
- 提供 `/` 首页和 `/api/health` 健康检查

### 5.2 配置中心

**文件**：`app/config.py`

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `WORKSPACE` | `workspace/` (resolve) | 工作空间目录 |
| `PROJECTS_ROOT` | `D:/projects` (Win) | 用户项目根目录 |
| `DASHSCOPE_API_KEY` | 硬编码（待修复） | DashScope API Key |
| `WORKSPACE_ID` | `ws-7xh0e417mx6yonyj` | 阿里云工作区 ID |
| `MODEL_NAME` | `qwen-plus` | 主模型 |
| `VL_MODEL_NAME` | `qwen-vl-plus` | 视觉模型 |
| `TEMPERATURE_PLANNING` | 0.1 | 规划/评审温度 |
| `TEMPERATURE_CHAT` | 0.7 | 对话温度 |
| `MAX_STEPS` | 10 | Agent 最大循环步数 |
| `SCAN_IGNORE_DIRS` | 20+ 个目录 | 扫描忽略目录 |
| `SCAN_ALLOWED_EXTENSIONS` | 14 种扩展名 | 扫描允许的文件类型 |
| `MAX_IMAGES_PER_REQUEST` | 5 | 单次图片上传上限 |
| `IMAGE_MAX_DIMENSION` | 1920 | 图片压缩长边 |
| `IMAGE_JPEG_QUALITY` | 85 | JPEG 压缩质量 |

### 5.3 日志系统

**文件**：`app/logging_config.py`

- 控制台输出：INFO 级别
- 文件输出：DEBUG 级别，写入 `workspace/logs/agent.log`（5MB 轮转，保留 3 份）
- 三个 logger：`gt_agent.graph` / `gt_agent.chat_router` / `gt_agent.chat_service`
- 第三方库降噪：httpx/httpcore/openai/uvicorn.access → WARNING

### 5.4 路由层 (routes/) — 9 个模块

| 路由文件 | 前缀 | 功能 |
|---------|------|------|
| `chat_router.py` | `/api/chat` | 聊天接口（SSE 流式），支持文件上传 |
| `conversation_router.py` | `/api/conversations` | 对话记录 CRUD |
| `file_router.py` | `/api` | 文件上传 + 全文搜索 |
| `memory_router.py` | `/api/memory` | 记忆管理 + 用户画像 |
| `project_router.py` | `/api/projects` | 项目文档读取 |
| `project_registry_router.py` | `/api/project-registry` | 项目注册表管理 |
| `task_router.py` | `/api/tasks` | 任务管理 + 需求分析编排 |
| `artifact_router.py` | `/api/artifacts` | 制品文件读取 |
| `workspace_router.py` | `/api/workspace` | 工作空间目录概览 |

### 5.5 服务层 (services/) — 14 个模块

#### 核心引擎

| 服务文件 | 功能 |
|---------|------|
| **`graph_service.py`** | LangGraph 状态机引擎，Planner-Executor-Reviewer 循环 |
| `chat_service.py` | 聊天编排，图片压缩 + 文件处理 + 历史拼接 → 调用 graph_service |

#### 文件与上下文

| 服务文件 | 功能 |
|---------|------|
| `file_service.py` | `WorkspaceCache` 增量索引缓存（mtime 检查 + 定期全量扫描），零 IO 搜索 |
| `workspace_service.py` | 工作空间目录扫描（委托 `agent/tools/filesystem.py`） |

#### 记忆与任务

| 服务文件 | 功能 |
|---------|------|
| `memory_service.py` | 记忆 CRUD（委托 `agent/tools/memory.py`）+ 用户画像管理 |
| `task_service.py` | 任务 CRUD（委托 `agent/tools/document.py`）+ 待办任务管理 |
| `conversation_service.py` | 对话记录 JSON 持久化 |

#### 需求分析管线

| 服务文件 | 功能 |
|---------|------|
| `requirement_parser_service.py` | 需求文本 → 结构化数据（标题/摘要/交互项/字段/API/验收标准） |
| `project_matcher_service.py` | Token 重叠度匹配需求与项目（项目名 0.5 + 模块 0.3 + 目录 0.2） |
| `document_generator_service.py` | 自动生成 change-plan.md / impact-files.md / test-cases.md |

#### 项目管理

| 服务文件 | 功能 |
|---------|------|
| `project_registry_service.py` | 项目注册表 JSON 持久化 + 路径安全校验 + 批量导入 |
| `project_scanner_service.py` | 扫描项目结构，识别框架/构建工具/路由/组件目录等 |
| `project_service.py` | 项目文档读取 |
| `artifact_service.py` | 制品文件读写（`workspace/artifacts/{task_id}/`） |

### 5.6 数据模型

**文件**：`app/models/project_registry.py`

| 模型 | 用途 |
|------|------|
| `ProjectRegistryItem` | 完整项目信息（框架/构建工具/包管理器/源码目录/路由文件/组件目录等） |
| `ProjectRegistryCreate` | 创建请求 |
| `ProjectRegistryUpdate` | 部分更新请求 |
| `ProjectRegistryImportRequest` | 批量导入请求 |
| `ProjectRegistryImportResult` | 导入结果 |

### 5.7 委托模式

三个服务将基础 CRUD 委托给 `agent/tools/`，自身只保留独有功能：

```
memory_service.py     → 委托 agent/tools/memory.py (CRUD)
                        保留: user_profile 读写
task_service.py       → 委托 agent/tools/document.py (CRUD)
                        保留: pending.md 解析与管理
workspace_service.py  → 委托 agent/tools/filesystem.py:list_dir
                        保留: get_workspace() API 专用
```

---

## 六、前端

**文件**：`index.html`（单文件应用）

| 特性 | 说明 |
|------|------|
| 框架 | 原生 HTML + Tailwind CSS (CDN) |
| Markdown 渲染 | marked.js (CDN) |
| 图标 | Font Awesome 6.4.0 |
| 交互 | SSE EventSource 流式接收 |
| 功能 | 聊天界面 + 对话历史 + 文件上传 + 全屏模式 |

---

## 七、API 接口清单

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 前端页面 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/workspace` | 工作空间目录结构 |
| GET/POST | `/api/conversations` | 对话列表/创建 |
| GET/DELETE | `/api/conversations/{id}` | 对话详情/删除 |
| POST | `/api/chat` | 聊天（SSE 流式） |
| POST | `/api/upload` | 文件上传 |
| GET | `/api/search?q=` | 全文搜索 |
| GET/POST | `/api/memory/{name}` | 记忆读取/保存 |
| GET/PUT | `/api/memory/user_profile` | 用户画像 |
| GET | `/api/projects` | 项目列表 |
| GET | `/api/projects/{project}/{doc}` | 项目文档 |
| GET/POST/PUT/DELETE | `/api/tasks/{name}` | 任务管理 |
| GET | `/api/tasks/pending` | 待办任务 |
| POST | `/api/tasks/requirement-analysis` | 需求分析编排 |
| GET | `/api/artifacts` | 制品列表 |
| GET | `/api/artifacts/{name}` | 制品内容 |
| GET/POST | `/api/project-registry` | 项目注册表 |
| GET/PUT/DELETE | `/api/project-registry/{id}` | 注册项详情 |

---

## 八、数据流架构

### 8.1 聊天流程

```
用户输入消息 + 可选文件上传
    │
    ▼
chat_router.py (POST /api/chat)
    │
    ▼
chat_service.py
    ├── 图片: 压缩 → base64 编码
    ├── 文本文件: 读取内容
    ├── 拼接历史对话上下文
    └── 调用 graph_service.run_graph_stream()
         │
         ▼
    LangGraph 工作流
         ├── Planner: 生成执行计划
         ├── Executor: 调用工具执行
         ├── Reviewer: 评审结果
         └── 循环直到完成或达 MAX_STEPS
         │
         ▼ (SSE 事件流)
    status → plan → trace → token → done
         │
         ▼
chat_service.py (后处理)
    ├── 偏好提取 → 更新 user_profile.md
    ├── 未完成任务 → 保存 pending.md
    └── 保存对话记录 → conversations/{id}.json
```

### 8.2 需求分析管线

```
POST /api/tasks/requirement-analysis
    │
    ▼
requirement_parser_service.py
    ├── LLM 解析需求文本
    └── 输出 requirement.json + requirement.md
    │
    ▼
project_matcher_service.py
    ├── Token 重叠度评分
    └── 返回 Top 5 推荐项目
    │
    ▼
document_generator_service.py
    ├── 生成 change-plan.md (改造建议)
    ├── 生成 impact-files.md (影响文件)
    └── 生成 test-cases.md (测试用例)
```

---

## 九、文件统计

| 层 | 目录 | .py 文件数 | 核心文件数 |
|----|------|-----------|-----------|
| 能力层 | `agent/` | 21（含 9 个空 `__init__.py`） | 12 |
| 应用层 | `app/` | 31（含 `__pycache__`） | 19 |
| 数据层 | `workspace/` | — | JSON + Markdown |
| 前端 | 根目录 | — | 1 (index.html) |
| **合计** | — | **~52** | **~32** |

---

## 十、已知技术债务

| 优先级 | 问题 | 状态 |
|--------|------|------|
| P0 | API Key 硬编码在 config.py | 待修复（需引入 .env + python-dotenv） |
| P0 | 静态文件暴露源码 | 待修复（StaticFiles 挂载范围限制） |
| P1 | XSS 风险（marked.js 未 sanitize） | 待修复（需 DOMPurify 或 sanitize 选项） |

---

## 十一、架构设计亮点

1. **知识即文件**：无数据库依赖，所有状态以 JSON/Markdown 存储，透明可审计
2. **能力注册制**：BaseCapability 延迟加载 + 统一接口，新增能力只需声明 3 个属性
3. **防幻觉规则**：7 条强制规则注入 Planner，禁止 LLM 猜测文件结构
4. **增量缓存**：WorkspaceCache 基于 mtime 增量更新，搜索零 IO（32x 加速）
5. **三重安全网**：reviewer_node + _should_continue + run_graph_stream 防无限循环
6. **异步全链路**：AsyncOpenAI + async generator + asyncio.to_thread，不阻塞事件循环
7. **统一异常体系**：ToolError 替代错误字符串返回，executor 统一捕获
8. **委托模式**：services 层 CRUD 委托 agent/tools，消除代码重复
