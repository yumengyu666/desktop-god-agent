"""
性能监控 - 函数计时 + 资源追踪
"""

import functools
import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional, Any, Dict

logger = logging.getLogger("Utils.Perf")


@dataclass
class TimingResult:
    """计时结果"""
    name: str
    elapsed_ms: float
    success: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def __str__(self):
        status = "✅" if self.success else "❌"
        return f"{status} {self.name}: {self.elapsed_ms:.1f}ms"


class Timer:
    """
    上下文管理器计时器
    
    用法:
        with Timer("操作名称") as t:
            do_something()
        print(t.result)  # "操作名称: 123.4ms"
    """

    def __init__(self, name: str = "", log_threshold_ms: float = 0.0):
        self.name = name
        self.log_threshold = log_threshold_ms
        self._start: float = 0
        self._result: Optional[TimingResult] = None

    def __enter__(self) -> 'Timer':
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = (time.perf_counter() - self._start) * 1000
        self._result = TimingResult(
            name=self.name or "unnamed",
            elapsed_ms=elapsed,
            success=exc_type is None,
        )
        
        if self.log_threshold > 0 and elapsed > self.log_threshold:
            logger.debug(f"[Timer] {self._result}")
        return False  # 不吞异常

    @property
    def result(self) -> Optional[TimingResult]:
        return self._result
    
    @property
    def ms(self) -> float:
        return self._result.elapsed_ms if self._result else 0.0


def track_time(
    name: str | None = None,
    log_slow: bool = True,
    slow_threshold_ms: float = 1000.0,
):
    """
    计时装饰器
    
    用法:
        @track_time("API调用")
        def fetch_data(): ...
        
        # 自动使用函数名
        @track_time()
        def heavy_computation(): ...
    """
    def decorator(func: Callable) -> Callable:
        label = name or func.__name__
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed = (time.perf_counter() - start) * 1000
                if log_slow and elapsed > slow_threshold_ms:
                    logger.warning(
                        f"[Slow] {label} took {elapsed:.0f}ms "
                        f"(threshold: {slow_threshold_ms:.0f}ms)"
                    )
                elif log_slow is False or (log_slow and elapsed >= slow_threshold_ms * 0.5):
                    logger.debug(f"⏱ {label}: {elapsed:.0f}ms")
        return wrapper
    return decorator


class PerformanceTracker:
    """
    全局性能追踪器
    
    功能：
    - 按函数名记录调用次数和平均耗时
    - 检测性能退化（最近N次平均 > 历史平均 * 阈值）
    - 资源监控（CPU/内存/线程数）
    
    线程安全，可在多线程环境中使用。
    """

    _instance: Optional['PerformanceTracker'] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        self._records: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._initialized = True

    def record(self, name: str, elapsed_ms: float, success: bool = True):
        """记录一次调用"""
        with self._lock:
            if name not in self._records:
                self._records[name] = {
                    "calls": 0,
                    "total_ms": 0.0,
                    "successes": 0,
                    "min_ms": float('inf'),
                    "max_ms": 0.0,
                    "recent_10": [],
                }
            
            rec = self._records[name]
            rec["calls"] += 1
            rec["total_ms"] += elapsed_ms
            rec["successes"] += int(success)
            rec["min_ms"] = min(rec["min_ms"], elapsed_ms)
            rec["max_ms"] = max(rec["max_ms"], elapsed_ms)
            
            # 最近10次滑动窗口
            recent = rec.get("recent_10", [])
            recent.append(elapsed_ms)
            if len(recent) > 10:
                recent.pop(0)
            rec["recent_10"] = recent

    def get_report(self, top_n: int = 20) -> list:
        """生成性能报告（按总耗时排序）"""
        report = []
        for name, rec in self._records.items():
            avg = rec["total_ms"] / max(rec["calls"], 1)
            recent_avg = sum(rec["recent_10"]) / max(len(rec["recent_10"]), 1)
            
            # 性能退化检测
            degradation = ""
            if rec["calls"] > 10 and avg > 0:
                ratio = recent_avg / avg
                if ratio > 1.5:
                    degradation = f"⚠ 退化{ratio:.1f}x"
            
            report.append({
                "name": name,
                "calls": rec["calls"],
                "avg_ms": round(avg, 1),
                "recent_avg_ms": round(recent_avg, 1),
                "min_ms": round(rec["min_ms"], 1),
                "max_ms": round(rec["max_ms"], 1),
                "success_rate": (
                    f"{rec['successes']/rec['calls']:.0%}"
                    if rec["calls"] > 0 else "-"
                ),
                "degradation": degradation,
            })
        
        report.sort(key=lambda x: x["avg_ms"] * x["calls"], reverse=True)
        return report[:top_n]

    def get_summary(self) -> dict:
        """获取总体摘要"""
        total_calls = sum(r["calls"] for r in self._records.values())
        total_ms = sum(r["total_ms"] for r in self._records.values())
        return {
            "tracked_functions": len(self._records),
            "total_calls": total_calls,
            "total_time_s": round(total_ms / 1000, 2),
            "top_5_by_calls": sorted(
                self._records.items(), key=lambda x: x[1]["calls"], reverse=True
            )[:5],
        }

    def reset(self):
        """清空所有记录（用于测试或周期性重置）"""
        with self._lock:
            self._records.clear()


# 获取全局单例
def get_tracker() -> PerformanceTracker:
    return PerformanceTracker()
