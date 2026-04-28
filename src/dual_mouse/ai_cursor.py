"""
AI虚拟鼠标 - 透明窗口 + 蓝色光标

使用PyQt5创建一个全屏透明的覆盖窗口，
在上面绘制AI的虚拟光标和移动轨迹。
"""

import sys
import time
import math
import threading
from collections import deque
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# ---- 延迟导入 PyQt5 ----
try:
    from PyQt5.QtWidgets import (
        QWidget, QApplication,
    )
    from PyQt5.QtCore import (
        Qt, QTimer, QPoint, QPointF, QRect,
        QPropertyAnimation, QEasingCurve,
        pyqtSignal,
    )
    from PyQt5.QtGui import (
        QPainter, QColor, QPen, QBrush, QRadialGradient,
        QPixmap, QIcon, QFont, QPainterPath,
        QCursor,
    )
    HAS_PYQT5 = True
except ImportError:
    HAS_PYQT5 = False
    logger.warning("PyQt5 not installed, dual mouse unavailable")


# 光标配置
CURSOR_COLOR = QColor(64, 156, 255)       # 淡蓝色 #409CFF
CURSOR_OPACITY = 0.70                      # 70%透明度
TRAIL_LENGTH = 15                          # 轨迹点数量
TRAIL_FADE_SPEED = 0.08                    # 轨迹消失速度
CLICK_RADIUS = 8                           # 点击波纹半径


class AICursorWidget(QWidget):
    """
    AI光标渲染组件
    
    在透明窗口上绘制：
    - 淡蓝色箭头光标（与Windows系统光标同款）
    - 移动轨迹尾巴
    - 点击时的波纹动画
    - 当前目标位置指示器
    """

    # 信号
    position_changed = pyqtSignal(int, int)

    def __init__(self):
        super().__init__()
        
        # 窗口属性：无边框、置顶、透明、穿透鼠标事件
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.WindowTransparentForInput  # 关键！鼠标事件穿透
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_AlwaysStackOnTop)
        
        # 全屏覆盖
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.setGeometry(geo)
        
        # 光标状态
        self._cursor_pos: QPoint = QPoint(0, 0)
        self._target_pos: Optional[QPoint] = None
        self._is_visible = True
        
        # 轨迹历史
        self._trail: deque[dict] = deque(maxlen=TRAIL_LENGTH)
        
        # 动画状态
        self._click_animations: list[dict] = []   # 点击波纹
        self._target_indicator_opacity = 0.0      # 目标指示器透明度
        
        # 定时器：60fps刷新
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update_display)
        self._timer.start(16)  # ~60fps

        logger.info("AICursorWidget initialized")

    @property
    def cursor_position(self) -> tuple[int, int]:
        return (self._cursor_pos.x(), self._cursor_pos.y())

    def set_position(self, x: int, y: int, immediate: bool = False) -> None:
        """设置AI光标位置"""
        old_pos = QPoint(self._cursor_pos)
        new_pos = QPoint(x, y)
        
        if not immediate:
            # 记录轨迹
            self._trail.append({
                'pos': old_pos,
                'time': time.time(),
                'opacity': 1.0,
            })
        
        self._cursor_pos = new_pos
        self.position_changed.emit(x, y)
        
        if not immediate:
            self.update()

    def set_target(self, x: int, y: int) -> None:
        """显示目标位置指示"""
        self._target_pos = QPoint(x, y)
        self._target_indicator_opacity = 1.0

    def clear_target(self) -> None:
        """清除目标指示"""
        self._target_pos = None
        self._target_indicator_opacity = 0.0

    def trigger_click_animation(self) -> None:
        """触发点击波纹动画"""
        self._click_animations.append({
            'pos': QPoint(self._cursor_pos),
            'radius': 2,
            'max_radius': CLICK_RADIUS * 3,
            'opacity': CURSOR_OPACITY,
        })

    def show_cursor(self) -> None:
        """显示AI光标"""
        self._is_visible = True
        self.show()

    def hide_cursor(self) -> None:
        """隐藏AI光标"""
        self._is_visible = False
        self.hide()

    # ================================================================
    # 渲染
    # ================================================================

    def paintEvent(self, event) -> None:
        """主渲染函数"""
        if not self._is_visible:
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        current_time = time.time()
        
        # 1. 绘制移动轨迹
        self._draw_trail(painter, current_time)
        
        # 2. 绘制点击波纹
        self._draw_click_ripples(painter, current_time)
        
        # 3. 绘制目标位置指示
        self._draw_target(painter, current_time)
        
        # 4. 绘制主光标
        self._draw_cursor(painter)

    def _draw_trail(self, painter: QPainter, now: float) -> None:
        """绘制渐隐移动轨迹"""
        if len(self._trail) < 2:
            return
            
        for i, point_data in enumerate(self._trail):
            age = now - point_data['time']
            opacity = max(0, 1.0 - age / TRAIL_FADE_SPEED)
            
            if opacity <= 0:
                continue
                
            color = QColor(CURSOR_COLOR)
            color.setF(opacity * 0.3)  # 轨迹更淡
            
            pen = QPen(color)
            width = max(1, int(3 * opacity))
            pen.setWidth(width)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            
            pos = point_data['pos']
            size = max(2, int(4 * opacity))
            painter.drawEllipse(pos, size, size)

        # 清理过期轨迹
        while self._trail and (now - self._trail[0]['time']) > TRAIL_FADE_SPEED:
            self._trail.popleft()

    def _draw_click_ripples(self, painter: QPainter, now: float) -> None:
        """绘制点击波纹动画"""
        active_ripples = []
        
        for ripple in self._click_animations:
            ripple['radius'] += 3  # 扩散速度
            ripple['opacity'] -= 0.05  # 渐隐速度
            
            if ripple['opacity'] <= 0 or ripple['radius'] >= ripple['max_radius']:
                continue
                
            active_ripples.append(ripple)
            
            color = QColor(CURSOR_COLOR)
            color.setF(ripple['opacity'])
            pen = QPen(color)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(
                ripple['pos'],
                int(ripple['radius']),
                int(ripple['radius']),
            )
        
        self._click_animations = active_ripples

    def _draw_target(self, painter: QPainter, now: float) -> None:
        """绘制目标位置指示器（虚线圆环）"""
        if self._target_pos is None or self._target_indicator_opacity <= 0:
            return
            
        # 目标指示器渐隐
        self._target_indicatorOpacity = max(
            0, self._target_indicator_opacity - 0.02
        )
        
        color = QColor(CURSOR_COLOR)
        color.setAlphaF(self._target_indicator_opacity * 0.6)
        
        pen = QPen(color, 2, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(self._target_pos, 20, 20)
        
        # 十字准星
        cx, cy = self._target_pos.x(), self._target_pos.y()
        painter.drawLine(cx - 10, cy, cx + 10, cy)
        painter.drawLine(cx, cy - 10, cx, cy + 10)

    def _draw_cursor(self, painter: QPainter) -> None:
        """绘制主光标（标准Windows箭头形状）"""
        x, y = self._cursor_pos.x(), self._cursor_pos.y()
        
        # 使用径向渐变让光标更立体
        gradient = QRadialGradient(x, y, 12)
        gradient.setColorAt(0, QColor(CURSOR_COLOR))
        gradient.setColorAt(1, QColor(CURSOR_COLOR).darker(130))
        
        # 绘制标准Windows光标形状
        cursor_path = QPainterPath()
        # 箭头尖端
        cursor_path.moveTo(x, y)
        cursor_path.lineTo(x, y + 18)
        cursor_path.lineTo(x + 4, y + 14)
        cursor_path.lineTo(x + 9, y + 19)
        cursor_path.lineTo(x + 7, y + 13)
        cursor_path.lineTo(x + 12, y + 13)
        cursor_path.lineTo(x + 7, y + 7)
        cursor_path.lineTo(x + 11, y + 7)
        cursor_path.closeSubpath()
        
        # 填充
        fill_color = QColor(CURSOR_COLOR)
        fill_color.setAlphaF(CURSOR_OPACITY)
        painter.setBrush(QBrush(fill_color))
        painter.setPen(Qt.NoPen)
        painter.drawPath(cursor_path)
        
        # 边框
        border_color = QColor(255, 255, 255, int(180 * CURSOR_OPACITY))
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(cursor_path)

    def update_display(self) -> None:
        """定时刷新显示"""
        self.update()


class DualMouseSystem:
    """
    双鼠标系统总控
    
    管理：
    - PyQt5应用线程
    - AI光标窗口
    - 与执行引擎的位置同步
    - 用户/AI抢占检测
    """
    
    def __init__(self):
        if not HAS_PYQT5:
            raise RuntimeError("PyQt5 required for DualMouseSystem")
        
        self._app: Optional[QApplication] = None
        self._widget: Optional[AICursorWidget] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        
        # 回调：当执行引擎移动鼠标时调用
        self._position_callback: Optional[callable] = None

    def start(self) -> bool:
        """启动双鼠标系统"""
        if self._running:
            return True
            
        try:
            # PyQt5必须在主线程运行
            self._thread = threading.Thread(target=self._run_qt_app, daemon=True)
            self._thread.start()
            
            # 等待窗口初始化
            time.sleep(0.5)
            
            self._running = True
            logger.info("DualMouseSystem started")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start DualMouseSystem: {e}")
            return False

    def _run_qt_app(self) -> None:
        """在独立线程中运行Qt应用"""
        # 创建QApplication（每个进程只需要一个）
        app = QApplication.instance() or QApplication(sys.argv)
        self._app = app
        
        widget = AICursorWidget()
        self._widget = widget
        widget.show_cursor()
        
        logger.info("Qt event loop starting")
        app.exec_()
        logger.info("Qt event loop ended")

    def update_ai_position(self, x: int, y: int) -> None:
        """更新AI光标位置（由执行引擎调用）"""
        if self._widget:
            self._widget.set_position(x, y)

    def set_target(self, x: int, y: int) -> None:
        """显示目标位置"""
        if self._widget:
            self._widget.set_target(x, y)

    def on_click(self) -> None:
        """通知点击发生（用于波纹动画）"""
        if self._widget:
            self._widget.trigger_click_animation()

    def hide_ai_cursor(self) -> None:
        """隐藏AI光标（用户操作时）"""
        if self._widget:
            self._widget.hide_cursor()

    def show_ai_cursor(self) -> None:
        """显示AI光标"""
        if self._widget:
            self._widget.show_cursor()

    def stop(self) -> None:
        """停止双鼠标系统"""
        self._running = False
        if self._widget:
            self._widget.hide_cursor()
        if self._app:
            self._app.quit()
        logger.info("DualMouseSystem stopped")


def get_dual_mouse() -> DualMouseSystem:
    """获取全局双鼠标实例"""
    return DualMouseSystem()
