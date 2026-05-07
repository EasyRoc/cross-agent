"""
日志配置模块

为整个项目提供统一的日志配置。所有模块通过 get_logger(__name__) 获取 logger 实例，
确保日志格式一致、便于排查问题。

日志级别说明：
- DEBUG: 详细的调试信息，如 API 请求/响应、数据详情
- INFO: 关键流程节点信息，如模块启动、分析完成
- WARNING: 可能影响结果但不中断的异常
- ERROR: 中断流程的错误

使用方法：
    from app.logger import get_logger
    logger = get_logger(__name__)
    logger.info("流程开始")
    logger.debug(f"数据详情: {data}")
"""

import logging
import logging.handlers
import sys
from pathlib import Path


def setup_logging(
    level: int = logging.INFO,
    log_file: str | None = None,
) -> None:
    """
    配置全局日志格式和处理器。

    Args:
        level: 日志级别，默认 INFO
        log_file: 日志文件路径（可选），指定后会同时输出到文件
    """
    # 定义日志格式：时间 | 日志级别 | 模块名 | 消息
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台处理器：输出到 stdout
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # 根 logger 配置
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(console_handler)

    # 文件处理器（可选）：按天轮转
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(log_path),
            max_bytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # 屏蔽第三方库的 noisy 日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("pymilvus").setLevel(logging.WARNING)
    logging.getLogger("langgraph").setLevel(logging.WARNING)
    logging.getLogger("langchain").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    获取模块级 logger 实例。

    用法：
        logger = get_logger(__name__)
        logger.info("消息")

    Args:
        name: 模块名，通常传入 __name__

    Returns:
        配置好的 Logger 实例
    """
    return logging.getLogger(name)
