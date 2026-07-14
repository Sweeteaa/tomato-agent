"""日志配置 — 全项目统一的 logging 初始化

使用方式:
  - 在 app/main.py 启动时调用 setup_logging()
  - 各模块通过 logging.getLogger("gt_agent.xxx") 获取 logger
  - 控制台: INFO 级别，带颜色区分
  - 文件: DEBUG 级别，写入 workspace/logs/agent.log（自动轮转）
"""

import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_level: str = "INFO", log_dir: str = None) -> None:
    """初始化全局日志配置

    Args:
        log_level: 控制台日志级别，默认 INFO。可通过环境变量 LOG_LEVEL 覆盖
        log_dir: 日志文件目录，默认 workspace/logs/
    """
    from app.config import WORKSPACE

    if log_dir is None:
        log_dir = str(WORKSPACE / "logs")

    # 确保日志目录存在
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    # 项目级 root logger
    root_logger = logging.getLogger("gt_agent")
    root_logger.setLevel(logging.DEBUG)  # 全局最低级别 DEBUG，由 handler 各自过滤

    # 防止重复初始化
    if root_logger.handlers:
        return

    # ─── 控制台 handler ───
    console = logging.StreamHandler()
    console.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    console_fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    console.setFormatter(console_fmt)
    root_logger.addHandler(console)

    # ─── 文件 handler（轮转）───
    file_handler = logging.handlers.RotatingFileHandler(
        filename=Path(log_dir) / "agent.log",
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    root_logger.addHandler(file_handler)

    # ─── 降低第三方库噪音 ───
    for noisy in ["httpx", "httpcore", "openai", "uvicorn.access", "urllib3"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root_logger.info("日志系统初始化完成 (level=%s, dir=%s)", log_level, log_dir)
