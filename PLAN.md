# GT Agent 本地智能体搭建方案

## 一、项目定位

GT Agent 是一个**本地开发助手**，核心设计理念：**知识即文件**。
所有状态、记忆、知识、项目上下文都以文件形式存储在 `workspace` 目录中。

### 核心特性

- **隐私优先**：所有数据仅存于本地，不上传任何数据
- **离线可用**：无需联网即可运行
- **专注开发**：专为开发工作设计，支持文件管理、代码分析、文档生成
- **智能规划**：基于 LangGraph 实现 Planner→Executor→Reviewer 三节点协作流程
- **实时反馈**：支持流式输出，实时显示 Agent 思考过程和执行状态

## 二、完整目录结构

```
gt-agent/
├── app.py                  # FastAPI 入口（API + 路由）
├── index.html              # Tailwind CSS 前端页面
├── PLAN.md                 # 本方案文档
├── requirements.txt        # Python 依赖
│
├── agent/                  # Agent 核心模块
│   ├── capabilities/       # 能力模块（文件系统、记忆、文档）
│   │   ├── document/
│   │   │   ├── __init__.py
│   │   │   └── capability.py
│   │   ├── filesystem/
│   │   │   ├── __init__.py
│   │   │   └── capability.py
│   │   ├── memory/
│   │   │   ├── __init__.py
│   │   │   └── capability.py
│   │   └── __init__.py
│   ├── registry/           # 能力注册中心
│   │   ├── __init__.py
│   │   └── capability_registry.py
│   ├── skill_manager/      # 技能管理器
│   │   ├── __init__.py
│   │   └── manager.py
│   ├── skills/             # 技能库（Markdown 格式）
│   │   ├── document_generate.md
│   │   └── vue_analysis.md
│   ├── tools/              # 工具实现
│   │   ├── __init__.py
│   │   ├── document.py
│   │   ├── filesystem.py
│   │   └── memory.py
│   └── __init__.py
│
├── app/                    # 应用服务层
│   ├── routes/             # API 路由
│   │   ├── __init__.py
│   │   ├── chat_router.py           # 聊天接口（支持流式输出）
│   │   ├── conversation_router.py   # 对话管理
│   │   ├── file_router.py           # 文件上传
│   │   ├── memory_router.py         # 记忆管理
│   │   ├── project_router.py        # 项目文档
│   │   ├── task_router.py           # 任务管理
│   │   └── workspace_router.py      # 工作区管理
│   ├── services/           # 业务服务
│   │   ├── __init__.py
│   │   ├── chat_service.py          # 聊天服务（流式）
│   │   ├── conversation_service.py  # 对话记录
│   │   ├── file_service.py          # 文件处理
│   │   ├── graph_service.py         # LangGraph 工作流
│   │   ├── memory_service.py        # 用户画像系统
│   │   ├── project_service.py       # 项目管理
│   │   ├── task_service.py          # 待办任务
│   │   └── workspace_service.py     # 工作区扫描
│   ├── __init__.py
│   ├── config.py           # 配置管理
│   ├── main.py             # FastAPI 应用实例
│   └── tools.py            # 工具注册
│
├── workspace/              # AI 核心数据目录
│   ├── conversations/      # 对话记录（JSON）
│   │   ├── 2026-07-11.json
│   │   └── 2026-07-12.json
│   │
│   ├── memory/             # 长期记忆（Markdown）
│   │   ├── frontend.md     # 前端技术记忆
│   │   ├── projects.md     # 项目知识记忆
│   │   ├── bugs.md         # Bug 解决记忆
│   │   └── user_profile.md # 用户画像
│   │
│   ├── projects/           # 项目知识（按项目分目录）
│   │   ├── sassVue/
│   │   │   ├── overview.md
│   │   │   ├── api.md
│   │   │   └── components.md
│   │   └── remote-consult/
│   │
│   ├── tasks/              # 工作任务（Markdown）
│   │   ├── todo.md
│   │   ├── completed.md
│   │   └── pending.md      # 待办任务追踪
│   │
│   ├── uploads/            # 用户上传文件
│   │
│   └── vector/             # 向量数据库
│       └── faiss.index
│
└── venv/                   # Python 虚拟环境
```

## 三、数据流架构

### 3.1 核心流程

```
用户输入
   ↓
Planner 节点（任务规划）
   ↓
Executor 节点（工具执行）
   ↓
Reviewer 节点（结果评审）
   ↓
返回回答（流式输出）
   ↓
保存对话记录 → conversations/
   ↓
更新用户画像 → memory/user_profile.md
   ↓
保存待办任务（如果未完成）→ tasks/pending.md
```

### 3.2 LangGraph 工作流

```
用户输入
   ↓
┌─────────────────────────────────────────────┐
│              Planner 节点                    │
│  - 分析用户问题                              │
│  - 生成执行计划（步骤列表）                   │
│  - 检测上传文件，直接回答                     │
└─────────────────────────────────────────────┘
   ↓
┌─────────────────────────────────────────────┐
│              Executor 节点                   │
│  - 按计划执行工具调用                        │
│  - 记录执行轨迹（步骤、工具、参数、结果）     │
│  - 支持文件系统、记忆、文档操作               │
└─────────────────────────────────────────────┘
   ↓
┌─────────────────────────────────────────────┐
│              Reviewer 节点                   │
│  - 评审执行结果                              │
│  - 判断任务是否完成                          │
│  - 总结回答内容                             │
│  - 未完成时保存待办任务                      │
└─────────────────────────────────────────────┘
   ↓
循环或结束
```

### 3.3 流式输出事件

| 事件类型 | 说明 |
|---------|------|
| `status` | 当前执行状态（如"正在规划任务..."、"正在执行步骤 1/3..."） |
| `plan` | 任务拆解计划（步骤数和每步详情） |
| `trace` | 工具调用轨迹（步骤描述、工具名称、参数、结果） |
| `token` | 流式文本块（逐字显示回答） |
| `done` | 任务完成（包含完整响应和元数据） |

## 四、状态文件格式

### 4.1 对话记录 — JSON

路径：`workspace/conversations/YYYY-MM-DD_HH-MM-SS.json`

```json
{
  "id": "2026-07-12_12-06-03",
  "created_at": "2026-07-12 12:06:03",
  "preview": "帮我分析这个需求文档",
  "messages": [
    {
      "role": "user",
      "content": "帮我分析这个需求文档\n\n【文件: 专科运营需求.xlsx】\n..."
    },
    {
      "role": "assistant",
      "content": "根据您提供的需求文档，分析如下：..."
    }
  ],
  "tool_executions": []
}
```

### 4.2 用户画像 — Markdown

路径：`workspace/memory/user_profile.md`

```markdown
# 用户画像

## 技术栈偏好
- Vue
- React
- Python
- TypeScript

## 常用技能
- 文件操作
- 文档生成
- 代码分析

## 代码风格
- 异步编程
- 类型安全
- 组件化
- 模块化

## 其他偏好
- 喜欢详细的注释
- 偏好简洁的代码结构
```

### 4.3 待办任务 — Markdown

路径：`workspace/tasks/pending.md`

```markdown
# 待办任务

## 2026-07-12_12-06-03 | 2026-07-12 12:06:03
- [ ] 步骤 1：分析需求文档
- [ ] 步骤 2：创建项目结构
- [ ] 步骤 3：实现核心功能

## 2026-07-11_10-30-15 | 2026-07-11 10:30:15
- [x] 页面开发
- [ ] API联调
```

### 4.4 任务记录 — Markdown

路径：`workspace/tasks/todo.md`

```markdown
# 当前任务

## 远程会诊
- [x] 页面开发
- [x] API联调
- [ ] 功能测试

## 今日Bug
- qiankun加载异常
```

### 4.5 Agent 记忆 — Markdown

路径：`workspace/memory/frontend.md`

```markdown
前端技术栈:
- Vue2 / Vue3
- ElementUI / ElementPlus

代码偏好:
- 使用 async await
- API 统一封装
- 组件拆分
```

## 五、API 设计

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 前端页面 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/workspace` | 完整目录结构 |
| GET/POST | `/api/conversations` | 对话记录管理 |
| GET | `/api/conversations/{id}` | 对话详情 |
| GET/POST/PUT | `/api/memory/{name}` | 记忆管理 |
| GET | `/api/memory/user_profile` | 用户画像 |
| GET | `/api/projects` | 项目列表 |
| GET | `/api/projects/{project}/{doc}` | 项目文档读取 |
| GET | `/api/tasks/pending` | 待办任务列表 |
| GET/POST/PUT/DELETE | `/api/tasks/{name}` | 任务管理 |
| POST | `/api/upload` | 文件上传 |
| POST | `/api/chat` | 聊天接口（**流式 SSE**） |
| GET | `/api/search?q=keyword` | 全文搜索 |

### 5.1 聊天接口（流式 SSE）

**请求**：`POST /api/chat`

支持 `multipart/form-data` 格式：

| 参数 | 类型 | 说明 |
|------|------|------|
| `message` | string | 用户消息 |
| `conversation_id` | string | 对话 ID（可选） |
| `files` | file | 上传文件（支持多个，可选） |

**响应**：`text/event-stream`

```
data: {"type": "status", "message": "正在规划任务..."}

data: {"type": "plan", "steps": [...], "plan_steps": 3}

data: {"type": "status", "message": "正在执行步骤 1/3: 读取文件"}

data: {"type": "trace", "step": {...}}

data: {"type": "token", "content": "您"}

data: {"type": "token", "content": "好"}

data: {"type": "done", "response": "...", "is_complete": true}
```

## 六、技术栈

### 6.1 核心依赖

```
fastapi==0.115.0          # Web 框架
uvicorn==0.33.0           # ASGI 服务器
python-multipart==0.0.12  # 文件上传
langchain==0.3.7          # LLM 框架
langchain-community==0.3.7 # 社区工具
langchain-openai==0.3.0   # OpenAI 兼容接口
langgraph==0.2.36         # 多节点工作流
faiss-cpu==1.14.3         # 向量检索
sentence-transformers==3.4.1 # 文本嵌入
openai>=1.58.1            # OpenAI SDK
aiofiles==24.1.0          # 异步文件操作
python-dateutil==2.9.0    # 日期处理
python-docx==1.1.2        # Word 文件处理
openpyxl==3.1.5           # Excel 文件处理
pillow==10.4.0            # 图片处理
```

### 6.2 大模型配置

```python
MODEL_NAME = "qwen-plus"           # Qwen 大模型
TEMPERATURE = 0.7                   # 温度参数
DASHSCOPE_API_KEY = "..."          # 阿里云 DashScope API Key
WORKSPACE_ID = "ws-xxx"            # 阿里云工作区 ID
```

通过 OpenAI 兼容模式调用阿里云 DashScope 服务。

## 七、能力体系

### 7.1 文件系统能力 (filesystem)

| 工具 | 说明 | 参数 |
|------|------|------|
| `read_file` | 读取文件内容 | `path` |
| `write_file` | 写入文件内容 | `path`, `content` |
| `delete_file` | 删除文件 | `path` |
| `list_dir` | 列出目录内容 | `path` |
| `create_dir` | 创建目录 | `path` |

### 7.2 记忆管理能力 (memory)

| 工具 | 说明 | 参数 |
|------|------|------|
| `save_memory` | 保存记忆 | `name`, `content` |
| `load_memory` | 加载记忆 | `name` |
| `list_memories` | 列出所有记忆 | - |
| `update_profile` | 更新用户画像 | `preferences` |

### 7.3 文档管理能力 (document)

| 工具 | 说明 | 参数 |
|------|------|------|
| `save_skill` | 保存技能文档 | `name`, `content` |
| `list_skills` | 列出所有技能 | - |
| `load_skill` | 加载技能文档 | `name` |

### 7.4 文件上传支持

| 文件类型 | 处理方式 |
|---------|---------|
| `.docx` | 提取文本内容 |
| `.xlsx` | 提取表格数据 |
| `.jpg/.jpeg/.png/.gif/.bmp` | 提取图片信息（尺寸、格式等） |
| `.txt/.md` | 直接读取文本 |

## 八、启动方式

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量（可选，默认使用 config.py 中的值）
export DASHSCOPE_API_KEY="your-api-key"
export WORKSPACE_ID="your-workspace-id"

# 启动服务
python app.py

# 访问
http://localhost:8000
```

## 九、典型使用场景

### 场景1：文件上传与分析

```
用户：上传一个需求文档（Excel/Word）

Agent 流程：
1. 检测到上传文件，直接分析内容
2. 流式输出分析结果
3. 保存对话记录

输出：
正在分析上传文件...
正在生成回答...
根据您提供的需求文档，分析如下：
- 需求概述：...
- 核心功能：...
- 技术建议：...
```

### 场景2：代码开发任务

```
用户：帮我创建一个 Vue 组件

Agent 流程：
1. Planner：规划任务步骤
   - 步骤 1：创建组件文件
   - 步骤 2：编写组件代码
   - 步骤 3：验证文件创建

2. Executor：执行每个步骤
   - 正在执行步骤 1/3: 创建组件文件
   - 正在执行步骤 2/3: 编写组件代码
   - 正在执行步骤 3/3: 验证文件创建

3. Reviewer：总结结果

输出：
已成功创建 Vue 组件：src/components/MyComponent.vue
组件包含以下功能：...
```

### 场景3：跨天记忆检索

```
用户（第二天）：qiankun 白屏

Agent 搜索：
1. memory/ + vector/ → 找到昨天解决方案
2. 直接提示：你之前遇到过类似问题

输出：
2026-07-11 qiankun 子应用白屏
原因：automatic publicPath is not supported
解决：配置 webpack publicPath
```

### 场景4：待办任务追踪

```
用户：执行一个复杂任务，但中途中断

Agent 行为：
1. 检测到任务未完成
2. 将待办步骤保存到 pending.md
3. 下次对话时提醒用户

输出：
您有 2 个未完成任务：
- 对话 2026-07-12_10-00-00 (2026-07-12 10:00:00): 3 个待办步骤
```

## 十、后续扩展方向

1. **FAISS 向量检索**：对 memory + projects 建索引，支持语义搜索
2. **对话上下文管理**：自动管理对话窗口，避免 token 超限
3. **文件监听**：workspace 文件变更时自动更新向量索引
4. **多 Agent 协作**：不同项目可配置不同 Agent 角色和工具
5. **代码审查能力**：集成代码审查工具，支持 PR 分析
6. **调试支持**：集成调试工具，支持运行时问题诊断
7. **多模态支持**：扩展图片理解、图表分析能力