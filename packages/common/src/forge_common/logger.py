"""统一的日志记录模块。

提供统一的日志配置和便捷的 logger 获取接口，供整个项目使用。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


# 默认日志格式
DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 默认日志级别
DEFAULT_LOG_LEVEL = logging.INFO


def get_logger(
    name: Optional[str] = None, stream: Optional[object] = None
) -> logging.Logger:
    """获取一个配置好的 logger 实例。

    这是推荐的方式，每个模块应该使用自己的模块名来获取 logger：
    ```python
    from forge_common import get_logger
    logger = get_logger(__name__)
    ```

    Args:
        name: Logger 的名称，通常使用 `__name__`。如果为 None，则使用调用模块的名称。
        stream: 输出流，默认为 sys.stdout（符合现代应用和容器化实践）。
                可以设置为 sys.stderr 或其他流对象。

    Returns:
        配置好的 Logger 实例。
    """
    if name is None:
        # 自动获取调用模块的名称
        import inspect

        frame = inspect.currentframe()
        if frame is not None and frame.f_back is not None:
            name = frame.f_back.f_globals.get("__name__", "forge_common")
        else:
            name = "forge_common"

    logger = logging.getLogger(name)

    # 如果 logger 已经有 handler，说明已经配置过了，直接返回
    if logger.handlers:
        return logger

    # 设置日志级别
    logger.setLevel(DEFAULT_LOG_LEVEL)

    # 避免日志向上传播到根 logger（防止重复输出）
    logger.propagate = False

    # 创建控制台 handler（默认使用 stdout，符合现代应用和容器化实践）
    console_handler = logging.StreamHandler(stream or sys.stdout)
    console_handler.setLevel(DEFAULT_LOG_LEVEL)

    # 创建格式器
    formatter = logging.Formatter(fmt=DEFAULT_LOG_FORMAT, datefmt=DEFAULT_DATE_FORMAT)
    console_handler.setFormatter(formatter)

    # 添加 handler
    logger.addHandler(console_handler)

    return logger


def setup_logging(
    level: int | str = DEFAULT_LOG_LEVEL,
    format_string: Optional[str] = None,
    date_format: Optional[str] = None,
    log_file: Optional[str | Path] = None,
    enable_console: bool = True,
    stream: Optional[object] = None,
) -> None:
    """配置根 logger 的全局设置。

    这个函数应该在应用程序启动时调用一次，用于配置全局日志设置。
    如果不调用，每个模块的 logger 会使用默认配置。

    Args:
        level: 日志级别，可以是 logging.DEBUG, logging.INFO 等，或字符串如 "DEBUG", "INFO"。
        format_string: 日志格式字符串。如果为 None，使用默认格式。
        date_format: 日期格式字符串。如果为 None，使用默认格式。
        log_file: 日志文件路径。如果提供，日志会同时写入文件。
        enable_console: 是否启用控制台输出。
        stream: 输出流，默认为 sys.stdout（符合现代应用和容器化实践）。
                可以设置为 sys.stderr 或其他流对象。
    """
    # 转换字符串级别为数字
    if isinstance(level, str):
        level = getattr(logging, level.upper(), DEFAULT_LOG_LEVEL)

    # 获取根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清除现有的 handlers
    root_logger.handlers.clear()

    # 创建格式器
    formatter = logging.Formatter(
        fmt=format_string or DEFAULT_LOG_FORMAT,
        datefmt=date_format or DEFAULT_DATE_FORMAT,
    )

    # 添加控制台 handler（默认使用 stdout，符合现代应用和容器化实践）
    if enable_console:
        console_handler = logging.StreamHandler(stream or sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # 添加文件 handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # 配置第三方库的日志级别（可选）
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def configure_from_env() -> None:
    """从环境变量配置日志。

    支持的环境变量：
    - FORGE_LOG_LEVEL: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
    - FORGE_LOG_FILE: 日志文件路径
    - FORGE_LOG_CONSOLE: 是否启用控制台输出（true/false）
    - FORGE_LOG_STREAM: 输出流（stdout/stderr），默认为 stdout

    这个函数应该在应用程序启动时调用，通常在 main 函数或入口点。
    """
    import os

    # 从环境变量读取日志级别
    log_level_str = os.getenv("FORGE_LOG_LEVEL", "").upper()
    log_level = DEFAULT_LOG_LEVEL
    if log_level_str:
        log_level = getattr(logging, log_level_str, DEFAULT_LOG_LEVEL)

    # 从环境变量读取日志文件路径
    log_file = os.getenv("FORGE_LOG_FILE")

    # 从环境变量读取是否启用控制台
    enable_console_str = os.getenv("FORGE_LOG_CONSOLE", "true").lower()
    enable_console = enable_console_str in ("true", "1", "yes")

    # 从环境变量读取输出流
    stream_str = os.getenv("FORGE_LOG_STREAM", "stdout").lower()
    stream = sys.stderr if stream_str == "stderr" else sys.stdout

    setup_logging(
        level=log_level,
        log_file=log_file,
        enable_console=enable_console,
        stream=stream,
    )
