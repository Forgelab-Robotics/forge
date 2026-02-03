"""forge_common - 通用工具模块。

提供日志记录、配置等通用功能。
"""

from forge_common.logger import (
    configure_from_env,
    get_logger,
    setup_logging,
)

__all__ = [
    "get_logger",
    "setup_logging",
    "configure_from_env",
]
