"""
任务历史中心 - 用户可查看今天做过什么、哪些成功、失败原因、节省时间估算
"""

import json
import logging
import time
import os
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime

logger = logging.getLogger("ProductUI.History")


@dataclass
class TaskRecord:
    """单条任务记录"""
    id: str
    instruction: str           # 原始指令
    status: str                # success / partial / failed / cancelled
    started_at: float          # Unix时间戳
    completed_at: float = 0.0
    worker_used: str = ""       # 使用了哪个工种
    steps_total: int = 0       # 总步骤数
    steps_completed: int = 0   # 完成步骤数
    result_summary: str = ""    # 结果摘要
    error_message: str = ""    # 错误信息
    time_saved_estimated_s: float = 0.0  # AI估算节省的时间
    
    @property
    def duration_s(self) -> float:
        return max(0, self.completed_at - self.started_at)
    
    @property
    def date_str(self) -> str:
        return datetime.fromtimestamp(self.started_at).strftime("%Y-%m-%d %H:%M")
    
    @property
    def success_rate_display(self) -> str:
        if self.steps_total == 0:
            return "-" if self.status == "success" else "失败"
        pct = self.steps_completed / self.steps_total * 100
        return f"{pct:.0f}%"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration_s"] = round(self.duration_s, 1)
        d["date_str"] = self.date_str
        return d


class TaskHistoryCenter:
    """
    任务历史中心
    
    功能：
    - 记录每次任务执行结果
    - 按日期/状态/工种筛选
    - 统计分析（成功率、平均耗时、节省时间）
    - 历史数据持久化到JSON
    """

    def __init__(self, save_path: Optional[str] = None):
        self.save_path = Path(save_path or "./data/task_history.json")
        self._records: List[TaskRecord] = []
        self._load()
        # 今日统计缓存
        self._today_stats: Optional[Dict] = None

    def record(
        self,
        instruction: str,
        status: str,
        started_at: float,
        completed_at: float,
        worker: str = "",
        steps_total: int = 0,
        steps_completed: int = 0,
        result: str = "",
        error: str = "",
        estimated_time_saved: float = 0.0,
    ) -> TaskRecord:
        """记录一条任务"""
        import uuid
        record = TaskRecord(
            id=str(uuid.uuid4())[:8],
            instruction=instruction[:200],
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            worker_used=worker,
            steps_total=steps_total,
            steps_completed=steps_completed,
            result_summary=result[:200],
            error_message=error[:200],
            time_saved_estimated_s=estimated_time_saved,
        )
        
        self._records.append(record)
        self._today_stats = None  # 清除缓存
        
        # 只保留最近1000条
        if len(self._records) > 1000:
            self._records = self._records[-1000:]
        
        self._save()
        return record

    def get_today(self) -> List[TaskRecord]:
        """获取今天的记录"""
        today_start = datetime.now().replace(hour=0, minute=0, second=0).timestamp()
        return [r for r in self._records if r.started_at >= today_start]

    def get_recent(self, count: int = 20) -> List[TaskRecord]:
        """获取最近的记录"""
        return list(reversed(self._records[-count:]))

    def filter_by_status(self, status: str) -> List[TaskRecord]:
        return [r for r in self._records if r.status == status]

    def filter_by_worker(self, worker: str) -> List[TaskRecord]:
        return [r for r in self._records if r.worker_used == worker]

    def get_statistics(self, days: int = 1) -> Dict:
        """获取统计数据"""
        cutoff = time.time() - days * 86400
        recent = [r for r in self._records if r.started_at >= cutoff]
        
        if not recent:
            return {"total_tasks": 0, "message": "暂无数据"}

        total = len(recent)
        success_count = sum(1 for r in recent if r.status == "success")
        fail_count = sum(1 for r in recent if r.status == "failed")
        total_duration = sum(r.duration_s for r in recent)
        total_saved = sum(r.time_saved_estimated_s for r in recent)
        
        # 按工种统计
        by_worker = defaultdict(lambda: {"total": 0, "success": 0})
        for r in recent:
            w = r.worker_used or "unknown"
            by_worker[w]["total"] += 1
            if r.status == "success":
                by_worker[w]["success"] += 1
        
        return {
            "period_days": days,
            "total_tasks": total,
            "success_rate": f"{success_count / total:.1%}",
            "success_count": success_count,
            "fail_count": fail_count,
            "avg_duration_s": round(total_duration / total, 1),
            "total_time_saved_s": round(total_saved, 0),
            "total_time_saved_human": self._humanize_time(total_saved),
            "by_worker": dict(by_worker),
            "recorded_at": datetime.now().isoformat(),
        }

    def get_daily_summary(self) -> str:
        """生成今日总结文本"""
        stats = self.get_statistics(1)
        today = self.get_today()
        
        if not today:
            return "📋 今天还没有任务记录"
        
        lines = [
            f"📊 今日任务统计 ({len(today)}个)",
            f"",
            f"✅ 成功: {stats['success_count']}",
            f"❌ 失败: {stats['fail_count']}",
            f"📈 成功率: {stats['success_rate']}",
        ]
        
        if float(stats.get("total_time_saved_s", 0)) > 0:
            lines.append(f")
        lines.append(f"⏱ 平均耗时: {stats['avg_duration_s']}秒")
        
        # 列出最近的任务
        lines.append(f"\n📝 最近任务:")
        for r in today[-5:]:
            icon = {"success": "✅", "failed": "❌", "partial": "⚠️"}.get(r.status, "🔄")
            lines.append(f"  {icon} {r.instruction[:50]} ({r.date_str})")
        
        return "\n".join(lines)

    def clear_old(self, max_age_days: int = 90):
        """清除过期记录"""
        cutoff = time.time() - max_age_days * 86400
        before = len(self._records)
        self._records = [r for r in self._records if r.started_at >= cutoff]
        removed = before - len(self._records)
        if removed > 0:
            self._save()
            logger.info(f"Cleared {removed} old history records")

    # ---- 内部方法 ----

    def _load(self):
        try:
            if self.save_path.exists():
                with open(self.save_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._records = [TaskRecord(**d) for d in data]
                        logger.info(f"Loaded {len(self._records)} history records")
        except Exception as e:
            logger.warning(f"Failed to load history: {e}")

    def _save(self):
        try:
            self.save_path.parent.mkdir(parents=True, exist_ok=True)
            data = [r.to_dict() for r in self._records]
            with open(self.save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save history: {e}")

    @staticmethod
    def _humanize_time(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}秒"
        elif seconds < 3600:
            return f"{int(seconds // 60)}分{int(seconds % 60)}秒"
        else:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            return f"{h}小时{m}分钟"
