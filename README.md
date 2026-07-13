# GT Agent

GT Agent 是一个**本地开发助手**，核心设计理念：**知识即文件**。所有状态、记忆、知识、项目上下文都以文件形式存储在 `workspace` 目录中。

## 核心特性

- **隐私优先**：所有数据仅存于本地，不上传任何数据
- **离线可用**：无需联网即可运行
- **专注开发**：专为开发工作设计，支持文件管理、代码分析、文档生成
- **智能规划**：基于 LangGraph 实现 Planner→Executor→Reviewer 三节点协作流程
- **实时反馈**：支持流式输出，实时显示 Agent 思考过程和执行状态

## 技术栈

- **框架**：FastAPI、LangChain、LangGraph
- **服务器**：Uvicorn
- **向量检索**：FAISS
- **文本嵌入**：Sentence Transformers
- **文件处理**：openpyxl（Excel）、python-docx（Word）、Pillow（图片）

## 环境要求

- Python 3.10+
- pip

## 快速开始

### 1. 克隆项目

```bash
cd d:\projects-pj\agent\tomato-agent
```

### 2. 创建虚拟环境

```powershell
# Windows PowerShell
python -m venv venv

# 激活虚拟环境
.\venv\Scripts\activate
```

```bash
# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

> **注意**：如果安装过程中遇到 numpy 编译错误（Python 3.14+），请先安装兼容版本：
> ```bash
> pip install numpy>=1.28.0
> pip install -r requirements.txt
> ```

### 4. 配置环境变量（可选）

```powershell
# Windows PowerShell
$env:DASHSCOPE_API_KEY="your-api-key"
$env:WORKSPACE_ID="your-workspace-id"
```

```bash
# macOS/Linux
export DASHSCOPE_API_KEY="your-api-key"
export WORKSPACE_ID="your-workspace-id"
```

> 如果不配置，将使用 `app/config.py` 中的默认值。

### 5. 启动服务

```bash
uvicorn app.main:app --reload
```

或者使用：

```bash
python app.py
```

### 6. 访问应用

打开浏览器访问：http://localhost:8000

## 项目结构

```
tomato-agent/
├── agent/              # Agent 核心模块
│   ├── capabilities/   # 能力模块（文件系统、记忆、文档）
│   ├── registry/       # 能力注册中心
│   ├── skill_manager/  # 技能管理器
│   ├── skills/         # 技能库（Markdown 格式）
│   └── tools/          # 工具实现
├── app/                # 应用服务层
│   ├── routes/         # API 路由
│   ├── services/       # 业务服务
│   ├── config.py       # 配置管理
│   ├── main.py         # FastAPI 应用实例
│   └── tools.py        # 工具注册
├── workspace/          # AI 核心数据目录（自动创建）
│   ├── conversations/  # 对话记录（JSON）
│   ├── memory/         # 长期记忆（Markdown）
│   ├── projects/       # 项目知识
│   ├── tasks/          # 工作任务
│   ├── uploads/        # 用户上传文件
│   └── vector/         # 向量数据库
├── venv/               # Python 虚拟环境
├── app.py              # 启动入口
├── index.html          # 前端页面
├── requirements.txt    # Python 依赖
└── PLAN.md             # 项目设计文档
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 前端页面 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/workspace` | 完整目录结构 |
| GET/POST | `/api/conversations` | 对话记录管理 |
| GET | `/api/conversations/{id}` | 对话详情 |
| GET/POST/PUT | `/api/memory/{name}` | 记忆管理 |
| GET | `/api/projects` | 项目列表 |
| GET/POST/PUT/DELETE | `/api/tasks/{name}` | 任务管理 |
| POST | `/api/upload` | 文件上传 |
| POST | `/api/chat` | 聊天接口（流式 SSE） |

## 支持的文件类型

| 文件类型 | 处理方式 |
|---------|---------|
| `.docx` | 提取文本内容 |
| `.xlsx` | 提取表格数据 |
| `.jpg/.jpeg/.png/.gif/.bmp` | 提取图片信息 |
| `.txt/.md` | 直接读取文本 |

## 常见问题

### Q: 启动时提示 `ModuleNotFoundError: No module named 'openpyxl'`

A: 请确保已安装所有依赖：
```bash
pip install -r requirements.txt
```

### Q: Python 命令找不到

A: 请确保 Python 已安装并添加到系统 PATH。推荐安装 Python 3.10+。

### Q: 如何更新依赖

A: 更新 `requirements.txt` 后执行：
```bash
pip install -r requirements.txt --upgrade
```

### Q: workspace 目录没有自动创建

A: 应用启动时会自动创建 `workspace` 目录。如果未创建，请检查目录权限。

## 许可证

MIT License