"""
Desktop God Agent - 核心模块
上下文采集 + 任务编排
"""

from .context_manager import (
    ContextCollector,
    ExecutionContext,
    CollectionLevel,
    get_context_collector,
    quick_context,
    context_for_llm,
)

__all__ = [
    "ContextCollector",
    "ExecutionContext",
    "CollectionLevel",
    "get_context_collector",
    "quick_context",
    "context_for_llm",
]
