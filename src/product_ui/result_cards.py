"""
结果展示层 - 任务完成后不只说完成，展示结构化结果
"""

import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

logger = logging.getLogger("ProductUI.Result")


@dataclass
class ResultCard:
    """单个结果卡片"""
    title: str
    status: str                    # success / partial / failed
    summary: str                   # 一句话总结
    details: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, str] = field(default_factory=dict)
    suggestions: List[str] = field(default_factory=list)
    files_affected: List[str] = field(default_factory=list)
    time_spent_s: float = 0.0
    
    def to_display_text(self) -> str:
        """生成面向用户的文本展示"""
        lines = [
            f"{'✅' if self.status == 'success' else '⚠️' if self.status == 'partial' else '❌'} {self.title}",
            f"",
            f"{self.summary}",
        ]
        
        if self.metrics:
            lines.append("")
            lines.append("详情:")
            for k, v in self.metrics.items():
                lines.append(f"  • {k}: {v}")
        
        if self.files_affected:
            lines.append(f"\n涉及文件: {len(self.files_affected)}个")
        
        if self.suggestions:
            lines.append("")
            lines.append("建议:")
            for s in self.suggestions[:3]:
                lines.append(f"  → {s}")
        
        if self.time_spent_s > 0:
            lines.append(f"\n⏱ 耗时: {self.time_spent_s:.1f}秒")
        
        return "\n".join(lines)


class ResultCards:
    """结果卡片管理器"""
    
    def __init__(self):
        self._recent: List[ResultCard] = []
        self.max_history = 50

    def create(
        self,
        title: str,
        status: str,
        summary: str,
        details: Optional[Dict] = None,
        metrics: Optional[Dict] = None,
        files_affected: Optional[List[str]] = None,
        time_spent_s: float = 0.0,
    ) -> ResultCard:
        """创建并记录一张结果卡片"""
        card = ResultCard(
            title=title,
            status=status,
            summary=summary,
            details=details or {},
            metrics=metrics or {},
            files_affected=files_affected or [],
            time_spent_s=time_spent_s,
            suggestions=self._generate_suggestions(status, details or {}),
        )
        
        self._recent.append(card)
        if len(self._recent) > self.max_history:
            self._recent = self._recent[-self.max_history:]
        
        return card

    def _generate_suggestions(self, status: str, details: Dict) -> List[str]:
        """根据结果生成建议"""
        suggestions = []
        
        if status == "success":
            suggestions.append("任务已完成 ✓")
            if details.get("can_template"):
                suggestions.append("可将此操作保存为模板以便复用")
                
        elif status == "partial":
            suggestions.append("部分完成，以下项目可能需要手动处理")
            
        elif status == "failed":
            suggestions.append("建议检查错误信息后重试")
            if details.get("error_type") == "network":
                suggestions.append("可能是网络问题，稍后再试")
            elif details.get("error_type") == "permission":
                suggestions.append("权限不足，请以管理员身份运行")
            suggestions.append("可输入 '/恢复' 让AI尝试修复")
        
        return suggestions

    def get_latest(self) -> Optional[ResultCard]:
        return self._recent[-1] if self._recent else None

    def get_recent(self, count: int = 10) -> List[ResultCard]:
        return list(reversed(self._recent[-count:]))
