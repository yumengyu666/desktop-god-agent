"""
统一日志系统
- 控制台彩色输出 + 文件持久化
- 按日自动分割日志文件
- 各模块独立Logger + 全局格式统一
"""

import logging
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Optional


# ANSI颜色码（Windows终端也支持）
COLORS = {
    'DEBUG': '\033[36m',     # 青色
    'INFO': '\033[32m',      # 绿色
    'WARNING': '\033[33m',   # 黄色
    'ERROR': '\033[31m',     # 红色
    'CRITICAL': '\033[41m',  # 红底白字
    'RESET': '\033[0m',
}


class ColorFormatter(logging.Formatter):
    """彩色控制台Formatter"""
    
    def __init__(self):
        fmt = (
            "\033[90m%(asctime)s\033[0m | "
            "%(levelname)-7s | "
            "%(name)-20s | "
            "%(message)s"
        )
        super().__init__(fmt=fmt, datefmt="%H:%M:%S")
    
    def format(self, record):
        # 给level加颜色
        color = COLORS.get(record.levelname, '')
        record.levelname = f"{color}{record.levelname:<7}{COLORS['RESET']}"
        return super().format(record)


class FileFormatter(logging.Formatter):
    """文件Formatter（无颜色）"""
    
    def __init__(self):
        fmt = '%(asctime)s | %(levelname)-7s | %(name)-20s | %(message)s'
        super().__init__(fmt=fmt, datefmt="%Y-%m-%d %H:%M:%S")


class DailyFileHandler(logging.FileHandler):
    """按日分割的文件Handler"""

    def __init__(self, log_dir: str = "./logs", prefix: str = "agent"):
        log_dir_path = Path(log_dir)
        log_dir_path.mkdir(parents=True, exist_ok=True)
        
        today = datetime.now().strftime("%Y-%m-%d")
        filename = log_dir_path / f"{prefix}_{today}.log"
        
        self._log_dir = log_dir
        self._prefix = prefix
        
        super().__init__(filename, encoding="utf-8", mode="a")
        
        self.setFormatter(FileFormatter())
    
    def shouldRollover(self, record) -> bool:
        """检查是否需要切换到新日期的文件"""
        today = datetime.now().strftime("%Y-%m-%d")
        expected = Path(self._log_dir) / f"{self._prefix}_{today}.log"
        return self.baseFilename != str(expected)
    
    def doRollover(self):
        """执行日志文件切换"""
        if self.stream:
            self.stream.close()
        
        today = datetime.now().strftime("%Y-%m-%d")
        new_file = Path(self._log_dir) / f"{self._prefix}_{today}.log"
        self.baseFilename = str(new_file)
        self.stream = self._open()


def setup_logging(
    level: str = "INFO",
    log_dir: str = "./logs",
    console: bool = True,
    file_log: bool = True,
) -> logging.Logger:
    """
    初始化全局日志系统
    
    Args:
        level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        log_dir: 日志文件目录
        console: 是否输出到控制台
        file_log: 是否写入文件
        
    Returns:
        根logger
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # 清除已有handlers（防止重复）
    root_logger.handlers.clear()
    
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(ColorFormatter())
        root_logger.addHandler(console_handler)
    
    if file_log:
        file_handler = DailyFileHandler(log_dir=log_dir, prefix="agent")
        root_logger.addHandler(file_handler)
    
    logger = get_logger("System")
    logger.info(f"Logging initialized (level={level}, dir={log_dir})")
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的Logger（带模块路径前缀）"""
    return logging.getLogger(f"Agent.{name}")
