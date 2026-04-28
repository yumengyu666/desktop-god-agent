"""
世界模型实现 - 电脑数字孪生

维护电脑的全局状态图，
提供变化检测(Delta Engine)和异常识别能力。
"""

import time
import threading
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable
from collections import defaultdict
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


# ============================================================
# 数据定义
# ============================================================

class AppState(str, Enum):
    """应用运行状态"""
    RUNNING = "running"
    IDLE = "idle"
    FROZEN = "frozen"          # 卡死无响应
    NOT_RESPONDING = "not_responding"
    CRASHED = "crashed"
    MINIMIZED = "minimized"


@dataclass
class ProcessInfo:
    """进程信息"""
    pid: int
    name: str                   # 进程名 (chrome.exe)
    exe_path: str               # 可执行文件路径
    cmdline: str                # 命令行参数
    cpu_percent: float          # CPU使用率
    memory_mb: float            # 内存占用(MB)
    create_time: float          # 启动时间
    status: str                 # running/sleep/zombie 等


@dataclass 
class WindowState:
    """窗口状态"""
    title: str
    class_name: str
    hwnd: int
    rect: tuple[int, int, int, int]  # left,top,right,bottom
    is_foreground: bool
    is_visible: bool
    state: str  # normal/minimized/maximized


@dataclass
class InstantState:
    """即时状态快照（高频更新）"""
    timestamp: float
    
    # 前台窗口
    foreground_window: Optional[WindowState] = None
    
    # 所有可见窗口列表
    windows: list[WindowState] = field(default_factory=list)
    
    # 关键进程
    processes: list[ProcessInfo] = field(default_factory=list)
    
    # 屏幕状态指纹（用于变化检测）
    screen_hash: Optional[str] = None
    
    # 剪贴板内容摘要
    clipboard_summary: str = ""


@dataclass  
class TaskContext:
    """任务上下文（中频更新）"""
    task_id: str
    task_description: str
    current_step: int = 0
    total_steps: int = 0
    status: str = "pending"  # pending/running/completed/failed/paused
    start_time: float = field(default_factory=time.time)
    
    # 操作历史
    action_history: list[str] = field(default_factory=list)
    
    # 中间数据（如已识别的文字）
    context_data: dict = field(default_factory=dict)
    
    # 遇到的问题和解决方案
    issues_and_fixes: list[tuple[str, str]] = field(
        default_factory=list  # [(issue, fix)]
    )


@dataclass
class Anomaly:
    """检测到的异常"""
    anomaly_type: str           # frozen / popup_error / network_down / disk_full ...
    severity: str              # warning / critical / info
    description: str
    source: str                 # 来源进程或窗口
    detected_at: float = field(default_factory=time.time)
    suggested_action: str = ""
    auto_resolvable: bool = False


# ============================================================
# 世界模型核心
# ============================================================

class WorldModel:
    """
    电脑数字孪生 — 世界模型
    
    维护三层状态的实时快照，
    通过Delta Engine高效检测变化，
    自动识别各类异常情况。
    """

    def __init__(self):
        self._lock = threading.RLock()
        
        # 三层状态
        self._instant_state: Optional[InstantState] = None
        self._task_contexts: dict[str, TaskContext] = {}
        self._long_term_cache: dict = {}
        
        # Delta Engine
        self._last_state_hash: Optional[str] = None
        self._change_callbacks: list[Callable[[dict], None]] = []
        
        # 异常检测
        self._active_anomalies: list[Anomaly] = []
        self._anomaly_handlers: dict[str, Callable[[Anomaly], bool]] = {}
        
        # 监控线程
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        
        logger.info("WorldModel initialized")

    # ================================================================
    # 状态获取与更新
    # ================================================================

    def snapshot_instant(self) -> InstantState:
        """
        拍摄即时状态快照
        
        包括：前台窗口、所有可见窗口、关键进程、屏幕指纹
        """
        now = time.time()
        
        with self._lock:
            state = InstantState(timestamp=now)
            
            # 获取前台窗口信息
            try:
                import ctypes
                from ctypes.wintypes import HWND, RECT
                
                hwnd = ctypes.wind32.user32.GetForegroundWindow()
                if hwnd:
                    state.foreground_window = self._get_window_state(hwnd)
            except Exception as e:
                logger.debug(f"Failed to get foreground window: {e}")
            
            # 获取所有可见窗口
            state.windows = self._get_all_windows()
            
            # 获取关键进程
            if HAS_PSUTIL:
                state.processes = self._get_key_processes()
            
            # 屏幕指纹（轻量级）
            state.screen_hash = self._compute_screen_fingerprint()
            
            # 缓存
            self._instant_state = state
            
            return state

    def get_current_state(self) -> InstantState:
        """获取当前缓存的状态（不会重新扫描）"""
        with self._lock:
            return self._instant_state or self.snapshot_instant()

    def get_foreground_app(self) -> Optional[str]:
        """获取当前前台应用名"""
        state = self.get_current_state()
        if state and state.foreground_window:
            return state.foreground_window.class_name
        return None

    def get_foreground_title(self) -> Optional[str]:
        """获取当前前台窗口标题"""
        state = self.get_current_state()
        if state and state.foreground_window:
            return state.foreground_window.title
        return None

    # ================================================================
    # 任务上下文管理
    # ================================================================

    def create_task(self, task_id: str, description: str) -> TaskContext:
        """创建新任务上下文"""
        ctx = TaskContext(task_id=task_id, task_description=description)
        with self._lock:
            self._task_contexts[task_id] = ctx
        logger.info(f"[WORLD] Task created: {task_id} - {description[:50]}")
        return ctx

    def get_task(self, task_id: str) -> Optional[TaskContext]:
        """获取任务上下文"""
        return self._task_contexts.get(task_id)

    def update_task_progress(
        self,
        task_id: str,
        step: Optional[int] = None,
        total_steps: Optional[int] = None,
        status: Optional[str] = None,
        note: str = "",
    ) -> None:
        """更新任务进度"""
        ctx = self._task_contexts.get(task_id)
        if not ctx:
            return
        
        if step is not None:
            ctx.current_step = step
        if total_steps is not None:
            ctx.total_steps = total_steps
        if status:
            ctx.status = status
        if note:
            ctx.action_history.append(note)
        
        ctx.updated_at = time.time() if hasattr(ctx, 'updated_at') else time.time()

    def finish_task(self, task_id: str, success: bool = True) -> None:
        """结束任务"""
        ctx = self._task_contexts.get(task_id)
        if ctx:
            ctx.status = "completed" if success else "failed"

    def cleanup_task(self, task_id: str) -> None:
        """清理完成的任务"""
        self._task_contexts.pop(task_id, None)

    # ================================================================
    # Delta Engine — 变化检测
    # ================================================================

    def detect_changes(self) -> dict:
        """
        检测自上次以来的状态变化
        
        Returns:
            变化字典 {
                'foreground_changed': bool,
                'new_windows': list,
                'closed_windows': list,
                'screen_changed': bool,
                'process_changes': list,
            }
        """
        new_state = self.snapshot_instant()
        
        changes = {
            'foreground_changed': False,
            'new_windows': [],
            'closed_windows': [],
            'screen_changed': False,
            'process_changes': [],
        }
        
        old_state = self._instant_state
        if old_state is None:
            return changes
        
        # 前台窗口是否变化
        if (old_state.foreground_window and new_state.foreground_window and
            old_state.foreground_window.hwnd != new_state.foreground_window.hwnd):
            changes['foreground_changed'] = True
        
        # 屏幕是否变化
        if old_state.screen_hash != new_state.screen_hash:
            changes['screen_changed'] = True
        
        # 窗口变化
        old_titles = {w.hwnd for w in old_state.windows}
        new_titles = {w.hwnd for w in new_state.windows}
        for w in new_state.windows:
            if w.hwnd not in old_titles:
                changes['new_windows'].append(w.title)
        for w in old_state.windows:
            if w.hwnd not in new_titles:
                changes['closed_windows'].append(w.title)
        
        # 通知回调
        has_change = any(v for v in [changes[k] or [] if isinstance(changes[k], list) else changes[k]
                                      for k in changes])
        if has_change:
            for cb in self._change_callbacks:
                try:
                    cb(changes)
                except Exception as e:
                    logger.error(f"Change callback error: {e}")
        
        return changes

    # ================================================================
    # 异常检测
    # ================================================================

    def check_anomalies(self) -> list[Anomaly]:
        """
        执行一次异常检测
        
        检测项：
        - 无响应窗口(Not Responding)
        - 错误弹窗（标题含error/fail/exception）
        - 高CPU占用进程
        - 高内存占用
        """
        anomalies = []
        now = time.time()
        
        if HAS_PSUTIL:
            # 检查高CPU进程
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
                try:
                    info = proc.info
                    if info['cpu_percent'] and info['cpu_percent'] > 95:
                        anomalies.append(Anomaly(
                            anomaly_type="high_cpu",
                            severity="warning",
                            description=f"{info['name']} CPU使用率 {info['cpu_percent']}%",
                            source=str(info['pid']),
                            detected_at=now,
                        ))
                    
                    mem_mb = (info['memory_info'].rss / 1024 / 1024) if info.get('memory_info') else 0
                    if mem_mb > 2000:  # >2GB
                        anomalies.append(Anomaly(
                            anomaly_type="high_memory",
                            severity="info",
                            description=f"{info['name']} 内存占用 {mem_mb:.0f}MB",
                            source=str(info['pid']),
                            detected_at=now,
                        ))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        
        # 检查无响应窗口
        try:
            import ctypes
            user32 = ctypes.wind32.user32
            
            windows = self._get_all_windows()
            for win in windows:
                # 标题包含典型错误关键词
                error_keywords = [
                    'error', '错误', 'exception', '异常',
                    'fail', '失败', 'crash', '崩溃',
                    'warning', '警告',
                    'not responding', '未响应',
                ]
                title_lower = win.title.lower()
                for kw in error_keywords:
                    if kw.lower() in title_lower:
                        anomalies.append(Anomaly(
                            anomaly_type="error_popup",
                            severity="critical",
                            description=f"疑似错误弹窗: [{win.title}] @ ({win.rect})",
                            source=win.class_name,
                            detected_at=now,
                            auto_resolvable=True,
                            suggested_action="点击关闭按钮或按Esc关闭",
                        ))
                        break
                        
                # 检测"Not Responding"窗口
                if hasattr(ctypes.wintypes, 'DWORD'):
                    from ctypes.wintypes import DWORD
                    result = DWORD()
                    if user32.IsHungAppWindow(win.hwnd):
                        anomalies.append(Anomaly(
                            anomaly_type="frozen",
                            severity="critical",
                            description=f"应用卡死: [{win.title}]",
                            source=win.class_name,
                            detected_at=now,
                            suggested_action="等待或强制结束进程",
                        ))
        except Exception as e:
            logger.debug(f"Window anomaly check failed: {e}")
        
        # 更新活跃异常列表
        self._active_anomalies = anomalies
        
        if anomalies:
            logger.warning(f"[ANOMALY] Detected {len(anomalies)} issues")
            for a in anomalies:
                logger.warning(f"  - [{a.severity}] {a.anomaly_type}: {a.description}")
        
        return anomalies

    # ================================================================
    # 内部方法
    # ================================================================

    def _get_all_windows(self) -> list[WindowState]:
        """获取所有可见窗口"""
        import ctypes
        from ctypes.wintypes import HWND, RECT, DWORD, LPARAM, BOOL
        
        windows = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(BOOL, HWND, LPARAM)
        
        def enum_cb(hwnd, lp):
            nonlocal windows
            if not ctypes.wind32.user32.IsWindowVisible(hwnd):
                return True
            
            buf = ctypes.create_unicode_buffer(512)
            ctypes.wind32.user32.GetWindowTextW(hwnd, buf, 512)
            title = buf.value.strip()
            if not title or len(title) < 3:
                return True
            
            class_buf = ctypes.create_unicode_buffer(256)
            ctypes.wind32.user32.GetClassNameW(hwnd, class_buf, 256)
            
            rect = RECT()
            ctypes.wind32.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            
            is_fg = (hwnd == ctypes.wind32.user32.GetForegroundWindow())
            
            state = "normal"
            if ctypes.wind32.user32.IsIconic(hwnd):
                state = "minimized"
            elif ctypes.wind32.user32.IsZoomed(hwnd):
                state = "maximized"
            
            windows.append(WindowState(
                title=title,
                class_name=class_buf.value,
                hwnd=hwnd,
                rect=(rect.left, rect.top, rect.right, rect.bottom),
                is_foreground=is_fg,
                is_visible=True,
                state=state,
            ))
            return True
        
        callback = WNDENUMPROC(enum_cb)
        ctypes.wind32.user32.EnumWindows(callback, 0)
        return windows

    def _get_window_state(self, hwnd: int) -> WindowState:
        """获取单个窗口状态"""
        import ctypes
        from ctypes.wintypes import RECT
        
        title_buf = ctypes.create_unicode_buffer(512)
        ctypes.wind32.user32.GetWindowTextW(hwnd, title_buf, 512)
        
        class_buf = ctypes.create_unicode_buffer(256)
        ctypes.wind32.user32.GetClassNameW(hwnd, class_buf, 256)
        
        rect = RECT()
        ctypes.wind32.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        
        return WindowState(
            title=title_buf.value,
            class_name=class_buf.value,
            hwnd=hwnd,
            rect=(rect.left, rect.top, rect.right, rect.bottom),
            is_foreground=(hwnd == ctypes.wind32.user32.GetForegroundWindow()),
            is_visible=True,
            state="normal",
        )

    def _get_key_processes(self) -> list[ProcessInfo]:
        """获取关键进程信息（CPU/内存Top N）"""
        processes = []
        
        # 关注的关键进程名
        key_names = {
            'chrome.exe', 'msedge.exe', 'firefox.exe',
            'explorer.exe', 'cmd.exe', 'powershell.exe',
            'code.exe', 'notepad++.exe', 'winword.exe',
            'excel.exe', 'outlook.exe', 'wechat.exe',
            'qq.exe', 'dingtalk.exe', 'feishu.exe',
        }
        
        try:
            all_procs = sorted(
                psutil.process_iter(['pid', 'name', 'exe', 'cmdline',
                                    'cpu_percent', 'memory_info', 'create_time']),
                key=lambda p: p.info['memory_info'].rss if p.info.get('memory_info') else 0,
                reverse=True,
            )
            
            for proc in all_procs[:30]:  # Top 30 by memory
                try:
                    info = proc.info
                    name = info.get('name', '')
                    if name in key_names or (
                        info.get('memory_info') and 
                        info['memory_info'].rss > 50 * 1024 * 1024  # >50MB
                    ):
                        processes.append(ProcessInfo(
                            pid=info['pid'],
                            name=name,
                            exe_path=info.get('exe', ''),
                            cmdline=' '.join(info.get('cmdline', []) or []),
                            cpu_percent=info.get('cpu_percent', 0),
                            memory_mb=(info['memory_info'].rss / 1024 / 1024
                                      if info.get('memory_info') else 0),
                            create_time=info.get('create_time', 0),
                            status='running',
                        ))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                    
        except Exception as e:
            logger.error(f"Process enumeration failed: {e}")
        
        return processes

    def _compute_screen_fingerprint(self) -> str:
        """
        计算屏幕内容的轻量级指纹
        使用采样哈希而非全像素比较
        """
        try:
            import ctypes
            from ctypes.wintypes import HWND, RECT
            
            # 只采样几个关键位置的颜色值
            user32 = ctypes.wind32.user32
            hdc = user32.GetDC(0)
            
            screen_w = user32.GetSystemMetrics(0)
            screen_h = user32.GetSystemMetrics(1)
            
            # 在网格上采9个点 + 前台窗口中心
            samples = []
            sample_points = [
                (0.1, 0.1), (0.5, 0.1), (0.9, 0.1),
                (0.1, 0.5), (0.5, 0.5), (0.9, 0.5),
                (0.1, 0.9), (0.5, 0.9), (0.9, 0.9),
            ]
            
            for fx, fy in sample_points:
                x = int(screen_w * fx)
                y = int(screen_h * fy)
                color = user32.GetPixel(hdc, x, y)
                samples.append(color)
            
            user32.ReleaseDC(0, hdc)
            
            fingerprint = hashlib.md5(
                json.dumps(samples).encode()
            ).hexdigest()[:16]
            
            return fingerprint
            
        except Exception as e:
            logger.debug(f"Screen fingerprint failed: {e}")
            return f"fallback_{time.time():.0f}"

    # ================================================================
    # 监控模式
    # ================================================================

    def start_monitoring(self, interval_sec: float = 2.0) -> None:
        """启动后台监控循环"""
        if self._monitoring:
            return
        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval_sec,),
            daemon=True,
        )
        self._monitor_thread.start()
        logger.info("World model monitoring started")

    def stop_monitoring(self) -> None:
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=3.0)
            self._monitor_thread = None

    def _monitor_loop(self, interval: float) -> None:
        while self._monitoring:
            try:
                self.detect_changes()
                self.check_anomalies()
            except Exception as e:
                logger.error(f"Monitor loop error: {e")
            time.sleep(interval)


def get_world_model() -> WorldModel:
    """获取世界模型单例"""
    return WorldModel()
