import os
from pathlib import Path

WORKSPACE = Path("workspace")
import sys

if sys.platform == "win32":
    DEFAULT_PROJECTS_ROOT = "D:/projects"
else:
    DEFAULT_PROJECTS_ROOT = str(Path.home() / "projects")

PROJECTS_ROOT = Path(os.getenv("PROJECTS_ROOT", DEFAULT_PROJECTS_ROOT)).resolve()
ALLOWED_PROJECT_ROOTS = [PROJECTS_ROOT]
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
}

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "sk-ws-H.EMYXYID.ZVVG.MEUCICwkpwMN7a4R2mEmOGw-l-1QGqAyESblsllc2J7ZJ62qAiEAiaVVmQhRtV2_EEP7IWiUx-TZEoXUYiWvPgfCtr7X6_o")
WORKSPACE_ID = os.getenv("WORKSPACE_ID", "ws-7xh0e417mx6yonyj")

MODEL_NAME = "qwen-plus"
TEMPERATURE = 0.7
