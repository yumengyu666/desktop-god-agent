"""
工种KPI指标追踪与质量控制系统
"""

import logging
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger("Ranch.Metrics")


@dataclass
class WorkerKPI:
    """单个工种的绩效指标"""
    total_tasks: int = 0
    success_count: int = 0
    fail_count: int = 0
    retry_count: int = 0
    interrupt_count: int = 0
    total_time_ms: float = 0.0
    avg_confidence: float = 0.0
    api_calls: int = 0
    tokens_used: int = 0

    @property
    def success_rate(self) -> float:
        if self.total_tasks == 0:
            return 1.0
        return self.success_count / self.total_tasks

    @property
    def avg_time_ms(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.total_time_ms / self.total_tasks

    @property
    def interrupt_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.interrupt_count / self.total_tasks

    @property
    def health_score(self) -> float:
        """
        综合健康评分 (0~100)
        
        权重：
        - 成功率 40%
        - 平均置信度 25%
        - 中断率反向 20%（越低越好）
        - 速度因子 15%
        """
        rate_score = self.success_rate * 40
        confidence_score = self.avg_confidence * 25
        interrupt_score = (1.0 - min(self.interrupt_rate, 1.0)) * 20
        # 速度：<500ms满分，>3000ms零分
        speed_factor = max(0, (3000 - self.avg_time_ms) / 3000) * 15
        return rate_score + confidence_score + interrupt_score + speed_factor

    def record_success(self, time_ms: float, confidence: float, tokens: int = 0):
        """记录一次成功任务"""
        self.total_tasks += 1
        self.success_count += 1
        self.total_time_ms += time_ms
        self.api_calls += 1
        self.tokens_used += tokens
        n = self.total_tasks
        self.avg_confidence = (self.avg_confidence * (n - 1) + confidence) / n

    def record_fail(self, time_ms: float = 0):
        """记录一次失败"""
        self.total_tasks += 1
        self.fail_count += 1
        if time_ms:
            self.total_time_ms += time_ms
        self.api_calls += 1

    def to_dict(self) -> dict:
        return {
            "total_tasks": self.total_tasks,
            "success_rate": f"{self.success_rate:.1%}",
            "fail_count": self.fail_count,
            "retry_count": self.retry_count,
            "interrupt_rate": f"{self.interrupt_rate:.1%}",
            "avg_time_ms": round(self.avg_time_ms, 0),
            "avg_confidence": round(self.avg_confidence, 2),
            "health_score": round(self.health_score, 1),
            "api_calls": self.api_calls,
            "tokens_used": self.tokens_used,
        }


@dataclass
class SystemMetrics:
    """整个圈养系统的运行指标"""
    total_dispatches: int = 0
    total_subtasks: int = 0
    successful_subtasks: int = 0
    failed_subtasks: int = 0
    avg_dispatch_latency_ms: float = 0.0
    uptime_seconds: float = 0.0
    warmup_total_time_ms: float = 0.0
    worker_restarts: int = 0
    queue_peak_size: int = 0
    resource_exhaustion_events: int = 0

    started_at: float = field(default_factory=time.time)


class MetricsCollector:
    """
    KPI收集器 - 负责追踪和持久化各工种绩效
    """

    def __init__(self, save_path: Optional[str] = None):
        self.kpis: Dict[str, WorkerKPI] = {}
        self.system = SystemMetrics()
        self.save_path = Path(save_path) if save_path else None

    def get_kpi(self, worker_name: str) -> WorkerKPI:
        if worker_name not in self.kpis:
            self.kpis[worker_name] = WorkerKPI()
        return self.kpis[worker_name]

    def get_dashboard(self) -> Dict:
        """生成仪表板数据"""
        workers_data = {}
        overall_health = 0.0
        count = 0

        for name, kpi in self.kpis.items():
            d = kpi.to_dict()
            workers_data[name] = d
            overall_health += kpi.health_score
            count += 1

        return {
            "workers": workers_data,
            "system": asdict(self.system),
            "overall_health": round(overall_health / max(count, 1), 1),
            "timestamp": time.time(),
        }

    def save_snapshot(self):
        """保存KPI快照到文件"""
        if not self.save_path:
            return
        try:
            self.save_path.parent.mkdir(parents=True, exist_ok=True)
            data = self.get_dashboard()
            with open(self.save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save metrics snapshot: {e}")
