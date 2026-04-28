"""
悬浮面板 - 桌面上的轻量状态显示
显示当前任务、进度、预计时间、置信度

注意：实际GUI面板使用PyQt5/Tauri实现，
这里定义数据接口和状态管理，GUI渲染在独立文件。
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, Any, Dict

logger = logging.getLogger("ProductUI.Panel")


@dataclass
class PanelState:
    """悬浮面板当前状态"""
    # 任务信息
    current_task: str = ""
    task_status: str = "idle"       # idle / running / paused / done
    
    # 进度
    step_current: int = 0
    step_total: int = 0
    progress_percent: float = 0.0
    
    # 时间
    elapsed_s: float = 0.0
    eta_s: float = 0.0
    
    # AI状态
    confidence: float = 0.0
    active_worker: str = ""          # 当前活跃的工种名
    
    # 资源
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    api_calls_today: int = 0
    
    @property
    def status_text(self) -> str:
        if self.task_status == "idle":
            return "🟢 就绪"
        elif self.task_status == "running":
            return f"🔵 {self.current_task[:30]}... ({self.step_current}/{self.step_total})"
        elif self.task_status == "paused":
            return f"⏸ 已暂停"
        else:
            return "✅ 完成"


class OverlayPanel:
    """
    悬浮面板管理器
    
    在桌面右上角（或用户指定位置）显示一个半透明小窗口：
    ┌──────────────────────┐
    │ 🟢 Desktop God Agent │
    │ 当前：发送日报      │
    │ 步骤：3/5 | 94%     │
    │ 预计剩余：18秒      │
    │ [⏸] [⏹] [接管]     │
    └──────────────────────┘
    
    低打扰原则：
    - 不挡住用户操作（可拖动）
    - 高频操作时自动缩小到图标
    - 重要变化时才闪烁提醒
    """

    def __init__(self):
        self.state = PanelState()
        self._visible = True
        self._minimized = False
        self._position = (None, None)  # (x, y) or auto
        
        # 回调（由GUI层实现）
        self._on_pause: Optional[Callable] = None
        self._on_stop: Optional[Callable] = None
        self._on_takeover: Optional[Callable] = None
        self._render_callback: Optional[Callable[[PanelState], None]] = None

    def update(self, **kwargs):
        """更新面板状态"""
        for k, v in kwargs.items():
            if hasattr(self.state, k):
                setattr(self.state, k, v)
        
        # 触发重绘
        if self._render_callback:
            try:
                self._render_callback(self.state)
            except Exception as e:
                logger.debug(f"Render callback error: {e}")

    def show(self):
        self._visible = True
        self._minimized = False

    def hide(self):
        self._visible = False

    def minimize(self):
        self._minimized = True

    def toggle(self):
        if not self._visible:
            self.show()
        elif self._minimized:
            self._minimized = False
        else:
            self.minimize()

    def set_render_callback(self, cb: Callable[[PanelState], None]):
        """设置GUI渲染回调"""
        self._render_callback = cb

    # ---- 用户操作按钮回调 ----

    def on_pause_clicked(self):
        if self._on_pause:
            self._on_pause()

    def on_stop_clicked(self):
        if self._on_stop:
            self._on_stop()

    def on_takeover_clicked(self):
        """用户点击接管 → AI进入观察模式"""
        if self._on_takeover:
            self._on_takeover()

    def get_state_dict(self) -> Dict:
        return {
            "status_text": self.state.status_text,
            "current_task": self.state.current_task,
            "progress": f"{self.state.progress_percent:.0f}%",
            "step": f"{self.state.step_current}/{self.state.step_total}",
            "eta_s": round(self.state.eta_s, 0),
            "confidence": round(self.state.confidence, 2),
            "worker": self.state.active_worker,
            "elapsed_s": round(self.state.elapsed_s, 1),
            "visible": self._visible,
            "minimized": self._minimized,
        }
