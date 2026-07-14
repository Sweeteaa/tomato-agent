import os
import sys
from pathlib import Path

# ─── 工作空间 ───
WORKSPACE = Path(os.getenv("WORKSPACE_DIR", "workspace")).resolve()

# ─── 项目根目录 ───
if sys.platform == "win32":
    DEFAULT_PROJECTS_ROOT = "D:/projects"
else:
    DEFAULT_PROJECTS_ROOT = str(Path.home() / "projects")

PROJECTS_ROOT = Path(os.getenv("PROJECTS_ROOT", DEFAULT_PROJECTS_ROOT)).resolve()
ALLOWED_PROJECT_ROOTS = [PROJECTS_ROOT]

# ─── 扫描过滤 ───
SCAN_IGNORE_DIRS = {
    "node_modules",
    "dist",
    "build",
    ".git",
    ".idea",
    ".vscode",
    "coverage",
    ".output",
    ".nuxt",
    ".next",
    "__pycache__",
    ".tox",
    "venv",
    ".venv",
    ".DS_Store",
    ".Trash",
    ".fseventsd",
    ".Spotlight-V100",
    ".apdisk",
    ".AppleDouble",
}

# 扫描时允许读取的文件扩展名（统一来源，消除多处重复定义）
SCAN_ALLOWED_EXTENSIONS = {
    ".vue",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".txt",
    ".html",
    ".css",
    ".scss",
    ".less",
    ".py",
    ".yaml",
    ".yml",
}

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "sk-ws-H.EMYXYID.ZVVG.MEUCICwkpwMN7a4R2mEmOGw-l-1QGqAyESblsllc2J7ZJ62qAiEAiaVVmQhRtV2_EEP7IWiUx-TZEoXUYiWvPgfCtr7X6_o")
WORKSPACE_ID = os.getenv("WORKSPACE_ID", "ws-7xh0e417mx6yonyj")

MODEL_NAME = "qwen-plus"
VL_MODEL_NAME = os.getenv("VL_MODEL_NAME", "qwen-vl-plus")  # 图片识别专用视觉模型

# ─── 图片处理参数 ───
MAX_IMAGES_PER_REQUEST = int(os.getenv("MAX_IMAGES_PER_REQUEST", "5"))   # 单次上传图片上限
IMAGE_MAX_DIMENSION = int(os.getenv("IMAGE_MAX_DIMENSION", "1920"))      # 长边超过此值自动压缩
IMAGE_JPEG_QUALITY = int(os.getenv("IMAGE_JPEG_QUALITY", "85"))          # JPEG 压缩质量

# ─── LLM 参数 ───
# 规划和评审需要确定性，直接回答需要创造性
TEMPERATURE = 0.7
TEMPERATURE_PLANNING = float(os.getenv("TEMPERATURE_PLANNING", "0.1"))   # planner/reviewer 用低温度
TEMPERATURE_CHAT = float(os.getenv("TEMPERATURE_CHAT", "0.7"))           # 直接回答/summary 用较高温度

# ─── Agent 循环控制 ───
MAX_STEPS = int(os.getenv("MAX_STEPS", "5"))   # executor-reviewer 最大循环次数
