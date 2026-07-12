import os
from pathlib import Path

WORKSPACE = Path("workspace")

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "sk-ws-H.EMYXYID.ZVVG.MEUCICwkpwMN7a4R2mEmOGw-l-1QGqAyESblsllc2J7ZJ62qAiEAiaVVmQhRtV2_EEP7IWiUx-TZEoXUYiWvPgfCtr7X6_o")
WORKSPACE_ID = os.getenv("WORKSPACE_ID", "ws-7xh0e417mx6yonyj")

MODEL_NAME = "qwen-plus"
TEMPERATURE = 0.7