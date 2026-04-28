"""
执行中反馈系统 - 用户最怕AI沉默执行
提供：进度更新、步骤说明、预计时间、置信度
"""

import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Callable

logger = logging.getLogger("ProductUI.Feedback")


@dataclass 
class FeedbackItem:
    """单条反馈消息"""
    timestamp: float = field(default_factory=time.time)
    message: str = ""
    level: str = "info"           # info / progress / warning / success / error
    progress_percent: float = 0.0   # 0~100
    step_current: int = 0
    step_total: int = 0
    eta_seconds: float = 0.0       # 预计剩余时间
    confidence: float = 0.0        # 当前操作置信度


@dataclass
class TaskFeedback:
    """任务反馈上下文"""
    task_id: str
    task_description: str
    status: str = "running"        # running / paused / done / failed / cancelled
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    
    # 反馈消息列表（保留最近50条）
    messages: List[FeedbackItem] = field(default_factory=list)
    max_messages: int = 50
    
    # 回调函数
    on_feedback: Optional[Callable[[FeedbackItem], None]] = None
    
    @property
    def elapsed_seconds(self) -> float:
        end = self.completed_at or time.time()
        return end - self.started_at
    
    @property
    def latest(self) -> Optional[FeedbackItem]:
        return self.messages[-1] if self.messages else None
    
    @property
    def summary(self) -> Dict:
        lat = self.latest
        return {
            "task_id": self.task_id,
            "description": self.task_description,
            "status": self.status,
            "elapsed_s": round(self.elapsed_seconds, 1),
            "latest_msg": lat.message if lat else "",
            "progress": round(lat.progress_percent, 0) if lat else 0,
            "step": f"{lat.step_current}/{lat.step_total}" if lat else "0/0",
            "confidence": round(lat.confidence, 2) if lat else 0,
            "eta_s": round(lat.eta_seconds, 0) if lat else 0,
            "message_count": len(self.messages),
        }


class FeedbackManager:
    """
    反馈管理器 - 统一管理所有任务的执行反馈
    
    核心原则：
    - 高频小事静默处理（不每步都弹）
    - 中风险轻提示
    - 高风险强确认
    """

    # 消息级别到显示方式的映射
    DISPLAY_RULES = {
        "info": {"show": True, "toast_ms": 2000, "sound": False},
        "progress": {"show": True, "toast_ms": 0, "sound": False},
        "warning": {"show": True, "toast_ms": 3000, "sound": True},
        "success": {"show": True, "toast_ms": 2000, "sound": True},
        "error": {"show": True, "toast_ms": 5000, "sound": True},
    }

    def __init__(self):
        self._active_tasks: Dict[str, TaskFeedback] = {}
        self._history: List[Dict] = []          # 已完成的任务摘要
        self._global_callback: Optional[Callable] = None

    def create_task(
        self,
        task_id: str,
        description: str,
        on_feedback: Optional[Callable] = None,
    ) -> TaskFeedback:
        """创建新任务的反馈跟踪"""
        tf = TaskFeedback(task_id=task_id, task_description=description)
        tf.on_feedback = on_feedback or self._global_callback
        self._active_tasks[task_id] = tf
        return tf

    def push(
        self,
        task_id: str,
        message: str,
        level: str = "info",
        *,
        progress: float = -1,         # -1表示不更新进度
        step: tuple = (0, 0),        # (current, total)
        eta: float = -1,
        confidence: float = -1,
    ):
        """推送一条反馈消息"""
        tf = self._active_tasks.get(task_id)
        if not tf:
            logger.warning(f"[Feedback] Unknown task: {task_id}")
            return

        item = FeedbackItem(
            message=message,
            level=level,
            progress_percent=max(tf.latest.progress_percent, progress) if progress >= 0 and tf.latest else max(progress, 0),
            step_current=step[0] or (tf.latest.step_current if tf.latest else 0),
            step_total=step[1] or (tf.latest.step_total if tf.latest else 0),
            eta_seconds=eta if eta >= 0 else (tf.latest.eta_seconds if tf.latest else 0),
            confidence=confidence if confidence >= 0 else (tf.latest.confidence if tf.latest else 0.5),
        )

        tf.messages.append(item)

        # 保持消息列表大小限制
        if len(tf.messages) > tf.max_messages:
            tf.messages = tf.messages[-tf.max_messages:]

        # 触发回调
        if tf.on_feedback:
            try:
                tf.on_feedback(item)
            except Exception as e:
                logger.error(f"Feedback callback error: {e}")

        logger.debug(f"[Feedback][{task_id}][{level}] {message[:80]}")

    def complete(self, task_id: str, success: bool = True):
        """标记任务完成"""
        tf = self._active_tasks.get(task_id)
        if not tf:
            return
        
        tf.status = "done" if success else "failed"
        tf.completed_at = time.time()
        
        # 移入历史
        self._history.append({
            **tf.summary,
            "completed_at": tf.completed_at,
        })
        
        # 从活跃列表移除
        del self._active_tasks[task_id]
        
        # 历史只保留最近100条
        if len(self._history) > 100:
            self._history = self._history[-100:]

        logger.info(f"[Feedback] Task '{task_id}' {'completed' if success else 'failed'} in {tf.elapsed_seconds:.1f}s")

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """获取指定任务状态"""
        tf = self._active_tasks.get(task_id)
        return tf.summary if tf else None

    def get_all_active(self) -> List[Dict]:
        """获取所有活跃任务状态"""
        return [tf.summary for tf in self._active_tasks.values()]

    def get_recent_history(self, count: int = 20) -> List[Dict]:
        """获取最近完成的历史"""
        return list(reversed(self._history[-count:]))

    def set_global_callback(self, callback: Callable):
        """设置全局回调（用于UI渲染）"""
        self._global_callback = callback
