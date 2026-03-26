"""
日志系统模块
Logging system module
"""
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path


class ColoredFormatter(logging.Formatter):
    """彩色日志格式化器
    Colored log formatter
    """

    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',      # 红色
        'CRITICAL': '\033[35m',   # 紫色
        'RESET': '\033[0m'        # 重置
    }

    def format(self, record):
        # 添加颜色
        # Add color
        if record.levelname in self.COLORS:
            record.levelname = f"{self.COLORS[record.levelname]}{record.levelname}{self.COLORS['RESET']}"

        # 添加时间戳
        # Add timestamp
        record.asctime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        return super().format(record)


def setup_logger(name: str = f"google_search_{datetime.now().strftime('%Y-%m-%d')}", level: str = "INFO") -> logging.Logger:
    """设置日志器
    Setup and return a configured logger  
    返回配置好的 logger 实例
    """

    # 创建日志器
    # Create the logger
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    # 避免重复添加处理器
    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    # 创建控制台处理器（输出到 stderr，防止污染 stdout 用于 RPC）
    # Create console handler (write to stderr to avoid polluting stdout used for RPC)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)

    # 检测是否为Windows环境，如果是则不使用颜色
    # Detect Windows environment; avoid ANSI colors on Windows
    import platform
    is_windows = platform.system().lower() == 'windows'
    
    if is_windows:
        # Windows环境下使用无颜色格式
        # Use non-colored format on Windows
        console_formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    else:
        # 非Windows环境下使用彩色格式
        # Use colored format on non-Windows platforms
        console_formatter = ColoredFormatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    console_handler.setFormatter(console_formatter)

    # 创建文件处理器
    # Create file handler
    log_dir = Path("./logs")
    log_dir.mkdir(exist_ok=True)

    log_file = log_dir / f"{name}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)

    # 设置文件格式
    # Set file formatter
    file_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)

    # 添加处理器
    # Add handlers to logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


def signal_handler(signum, frame):
    """信号处理器
    Signal handler for graceful shutdown
    """
    logger = logging.getLogger("google_search")
    logger.info("进程退出，日志关闭  (Process exiting, closing logs)")
    sys.exit(0)


# 注册信号处理器  # Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# 创建默认日志器  # Create default logger
_logger = setup_logger()

# 导出日志函数  # Export logging wrapper functions
def info(message):
    _logger.info(message)

def warn(message):
    _logger.warning(message)

def error(message):
    _logger.error(message)

def debug(message):
    _logger.debug(message)

def critical(message):
    _logger.critical(message)
