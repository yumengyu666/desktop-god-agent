"""
统一异常体系 + 安全调用装饰器
所有自定义异常继承自AgentError，支持错误链和上下文信息
"""

import functools
import logging
import time
import traceback
from typing import Optional, Callable, Type, Any, TypeVar

logger = logging.getLogger("Utils.Exceptions")

F = TypeVar("F", bound=Callable[..., Any])


# ============================================================
#  异常类层次
# ============================================================

class AgentError(Exception):
    """所有自定义异常的基类"""
    
    def __init__(
        self,
        message: str,
        code: str = "UNKNOWN",
        recoverable: bool = True,
        context: Optional[dict] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code                    # 机器可读的错误码
        self.recoverable = recoverable       # 是否可以自动恢复
        self.context = context or {}         # 额外上下文（用于日志/调试）
        self.timestamp = time.time()
        
        if cause:
            self.__cause__ = cause
    
    def __str__(self):
        parts = [f"[{self.code}] {self.message}"]
        if self.context:
            ctx_str = ", ".join(f"{k}={v}" for k, v in list(self.context.items())[:3])
            parts.append(f"({ctx_str})")
        return " ".join(parts)
    
    def to_dict(self) -> dict:
        return {
            "error": self.message,
            "code": self.code,
            "recoverable": self.recoverable,
            "context": self.context,
            "timestamp": self.timestamp,
        }


class PerceptionError(AgentError):
    """感知系统异常（截图/UIA/OCR）"""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="PERCEPTION_ERROR", **kwargs)


class ScreenshotError(PerceptionError):
    """截图失败"""
    def __init__(self, message: str = "截图捕获失败", **kw):
        super().__init__(message, code="SCREENSHOT_FAILED", **kw)


class UIAScanError(PerceptionError):
    """UIA扫描失败"""
    def __init__(self, message: str = "UIA元素扫描失败", **kw):
        super().__init__(message, code="UIA_SCAN_FAILED", **kw)


class OCRError(PerceptionError):
    """OCR识别失败"""
    def __init__(self, message: str = "OCR文字识别失败", **kw):
        super().__init__(message, code="OCR_FAILED", **kw)


class ExecutionError(AgentError):
    """执行引擎异常（鼠标/键盘操作）"""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="EXECUTION_ERROR", **kwargs)


class MouseOperationError(ExecutionError):
    """鼠标操作失败"""
    def __init__(self, message: str = "鼠标操作失败", **kw):
        super().__init__(message, code="MOUSE_OP_FAILED", recoverable=True, **kw)


class KeyboardOperationError(ExecutionError):
    """键盘操作失败"""
    def __init__(self, message: str = "键盘操作失败", **kw):
        super().__init__(message, code="KEYBOARD_OP_FAILED", recoverable=True, **kw)


class ModelError(AgentError):
    """模型调用异常"""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="MODEL_ERROR", **kwargs)


class ModelUnavailableError(ModelError):
    """模型不可用（全部后端挂了）"""
    def __init__(self, message: str = "所有模型后端不可用", **kw):
        super().__init__(message, code="MODEL_UNAVAILABLE", recoverable=False, **kw)


class ModelRateLimitError(ModelError):
    """API限流"""
    def __init__(self, message: str = "API请求频率超限", **kw):
        super().__init__(message, code="RATE_LIMITED", recoverable=True, **kw)


class SecurityViolationError(AgentError):
    """安全违规异常（不可恢复！）"""
    
    def __init__(self, message: str, violation_type: str = "unknown", **kwargs):
        super().__init__(
            message, 
            code=f"SECURITY_VIOLATION_{violation_type.upper()}",
            recoverable=False,
            **kwargs
        )


# ============================================================
#  装饰器：安全调用 + 重试
# ============================================================

def safe_call(
    error_return: Any = None,
    exceptions: tuple | Type[Exception] = Exception,
    log_level: str = "error",
    reraise: bool = False,
):
    """
    安全调用装饰器 - 捕获异常并返回默认值，不中断程序流
    
    用法:
        @safe_call(error_return={})
        def get_config(): ...
        
        @safe_call(reraise=True)  # 只记录不吞掉
        def critical_op(): ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                getattr(logger, log_level)(
                    f"[{func.__name__}] {type(e).__name__}: {e}"
                )
                if reraise:
                    raise
                return error_return
        return wrapper  # type: ignore
    return decorator


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable[[int, Exception], None]] = None,
):
    """
    自动重试装饰器 - 指数退避重试
    
    用法:
        @retry(max_attempts=3, delay=0.5)
        def call_api(): ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt < max_attempts:
                        if on_retry:
                            on_retry(attempt, e)
                        logger.warning(
                            f"[{func.__name__}] Attempt {attempt}/{max_attempts} "
                            f"failed: {e}, retry in {current_delay:.1f}s"
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
            
            raise last_exception  # type: ignore
        return wrapper  # type: ignore
    return decorator
