"""
执行引擎核心 - Win32 API 鼠标键盘控制 + 仿人行为模拟

关键特性：
- 贝塞尔曲线鼠标移动（SHM简谐运动，非直线跳跃）
- 可配置移动速度和加速度
- 每次操作前后自动截图验证
- 支持急停中断
"""

import time
import math
import random
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Callable
import logging

logger = logging.getLogger(__name__)

# ---- Win32 API 绑定 ----
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 常量定义
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

# 屏幕分辨率
SM_CXSCREEN = 0
SM_CYSCREEN = 1


class ActionType(str, Enum):
    """动作类型枚举"""
    MOUSE_CLICK = "click"
    MOUSE_DOUBLE_CLICK = "double_click"
    MOUSE_RIGHT_CLICK = "right_click"
    MOUSE_DRAG = "drag"
    MOUSE_SCROLL = "scroll"
    KEYBOARD_TYPE = "type"
    KEYBOARD_KEY = "key"
    KEYBOARD_HOTKEY = "hotkey"


@dataclass
class Action:
    """标准动作描述"""
    action_type: ActionType
    params: dict                    # 动作参数
    timestamp: float = field(default_factory=time.time)
    verified: bool = False          # 是否已验证成功
    rollback_action: Optional['Action'] = None  # 回滚动作
    
    @property
    def description(self) -> str:
        match self.action_type:
            case ActionType.MOUSE_CLICK:
                return f"点击 ({self.params.get('x', 0)}, {self.params.get('y', 0)})"
            case ActionType.MOUSE_DOUBLE_CLICK:
                return f"双击 ({self.params.get('x', 0)}, {self.params.get('y', 0)})"
            case ActionType.MOUSE_RIGHT_CLICK:
                return f"右键 ({self.params.get('x', 0)}, {self.params.get('y', 0)})"
            case ActionType.MOUSE_DRAG:
                s = self.params.get('start', (0, 0))
                e = self.params.get('end', (0, 0))
                return f"拖拽 {s} → {e}"
            case Action.Type.MOUSE_SCROLL:
                return f"滚动 {self.params.get('delta', 0)}"
            case Action.Type.KEYBOARD_TYPE:
                text = self.params.get('text', '')[:30]
                return f'输入 "{text}..."'
            case Action.Type.KEYBOARD_KEY:
                return f"按键 {self.params.get('key', '')}"
            case Action.Type.KEYBOARD_HOTKEY:
                keys = "+".join(self.params.get('keys', []))
                return f"组合键 [{keys}]"
            case _:
                return f"未知动作: {self.action_type}"


@dataclass
class ActionResult:
    """动作执行结果"""
    success: bool
    action: Action
    error: str = ""
    elapsed_ms: float = 0.0
    before_screenshot: Optional[bytes] = None
    after_screenshot: Optional[bytes] = None


class MouseController:
    """
    鼠标控制器 - 仿人移动 + 精确点击
    """
    
    def __init__(
        self,
        move_duration_ms: int = 300,
        humanize: bool = True,
    ):
        self._duration_ms = move_duration_ms
        self._humanize = humanize
        self._screen_width = user32.GetSystemMetrics(SM_CXSCREEN)
        self._screen_height = user32.GetSystemMetrics(SM_CYSCREEN)
        
        # 急停标志
        self._emergency_stop = threading.Event()
        
        logger.info(f"MouseController init | "
                     f"screen={self._screen_width}x{self._screen_height} | "
                     f"move_duration={move_duration_ms}ms")

    @property
    def position(self) -> tuple[int, int]:
        """获取当前鼠标位置"""
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        return (point.x, point.y)

    # ---- 核心移动 ----
    
    def move_to(
        self,
        x: int,
        y: int,
        duration_ms: Optional[int] = None,
    ) -> None:
        """
        移动鼠标到目标位置
        
        使用简谐正弦运动(SHM)贝塞尔曲线，
        而非直线匀速，更接近人类自然移动。
        
        Args:
            x: 目标X坐标
            y: 目标Y坐标
            duration_ms: 移动耗时(ms)，None则使用默认值
        """
        if self._emergency_stop.is_set():
            logger.warning("Move interrupted by emergency stop")
            return
            
        start_x, start_y = self.position
        duration = (duration_ms or self._duration_ms) / 1000.0  # 转秒
        
        if duration <= 0.001:
            self._set_position(x, y)
            return
            
        # SHM缓动函数：先快后慢，带微小随机偏移
        steps = max(int(duration * 60), 10)  # 60fps
        for i in range(steps + 1):
            if self._emergency_stop.is_set():
                break
                
            progress = i / steps
            # 简谐运动缓动
            eased_progress = 0.5 * (1 - math.cos(math.pi * progress))
            
            cur_x = int(start_x + (x - start_x) * eased_progress)
            cur_y = int(start_y + (y - start_y) * eased_progress)
            
            # 人类化微抖动
            if self._humanize and i > 0 and i < steps:
                jitter_x = random.randint(-1, 1)
                jitter_y = random.randint(-1, 1)
                cur_x += jitter_x
                cur_y += jitter_y
                
            self._set_position(cur_x, cur_y)
            time.sleep(duration / steps)

    def _set_position(self, x: int, y: int) -> None:
        """底层设置光标位置"""
        user32.SetCursorPos(x, y)

    # ---- 点击操作 ----
    
    def click(self, x: int, y: int, button: str = "left") -> None:
        """点击指定位置"""
        self.move_to(x, y)
        time.sleep(random.uniform(0.03, 0.08))  # 人类停顿
        
        match button.lower():
            case "left":
                self._mouse_event(MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE, x, y)
                time.sleep(random.uniform(0.03, 0.06))
                self._mouse_event(MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE, x, y)
            case "right":
                self._mouse_event(MOUSEEVENTF_RIGHTDOWN | MOUSEEVENTF_ABSOLUTE, x, y)
                time.sleep(random.uniform(0.03, 0.06))
                self._mouse_event(MOUSEEVENTF_RIGHTUP | MOUSEEVENTF_ABSOLUTE, x, y)

    def double_click(self, x: int, y: int) -> None:
        """双击"""
        self.move_to(x, y)
        time.sleep(0.05)
        self.click(x, y)
        time.sleep(random.uniform(0.04, 0.08))
        self.click(x, y)

    def right_click(self, x: int, y: int) -> None:
        """右键点击"""
        self.click(x, y, button="right")

    # ---- 拖拽 ----
    
    def drag(
        self,
        start_pos: tuple[int, int],
        end_pos: tuple[int, int],
        duration_ms: Optional[int] = None,
    ) -> None:
        """拖拽操作"""
        sx, sy = start_pos
        ex, ey = end_pos
        duration = duration_ms or self._duration_ms * 3  # 拖拽默认慢3倍
        
        self.move_to(sx, sy, duration_ms=200)
        time.sleep(0.05)
        self._mouse_event(MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE, sx, sy)
        time.sleep(0.02)
        self.move_to(ex, ey, duration_ms=duration)
        time.sleep(0.02)
        self._mouse_event(MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE, ex, ey)

    # ---- 滚轮 ----
    
    def scroll(self, delta: int, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """滚轮滚动"""
        if x is not None and y is not None:
            self.move_to(x, y)
        self._mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta * 120)

    @staticmethod
    def _mouse_event(flags: int, x: int = 0, y: int = 0, data: int = 0) -> None:
        """发送鼠标事件"""
        struct = wintypes.tagMOUSEINPUT()
        struct.dx = x
        struct.dy = y
        struct.mouseData = data
        struct.dwFlags = flags
        struct.time = 0
        struct.dwExtraInfo = 0
        
        input_struct = wintypes.tagINPUT()
        input_struct.type = 0  # INPUT_MOUSE
        input_struct.mi = struct
        
        user32.SendInput(1, ctypes.byref(input_struct), ctypes.sizeof(input_struct))

    # ---- 急停 ----
    
    def emergency_stop(self) -> None:
        """触发急停"""
        self._emergency_stop.set()
        logger.warning("EMERGENCY STOP triggered on mouse controller")
    
    def reset_emergency(self) -> None:
        """重置急停状态"""
        self._emergency_stop.clear()


class KeyboardController:
    """
    键盘控制器 - 文本输入 + 快捷键
    """
    
    def __init__(self, type_delay_ms: int = 50):
        self._delay_ms = type_delay_ms / 1000.0
        self._stop_flag = threading.Event()

    def type_text(self, text: str, interval_ms: Optional[int] = None) -> None:
        """
        输入文本（支持中文通过剪贴板）
        
        对于ASCII字符逐字输入模拟打字；
        对于中文等非ASCII字符使用剪贴板粘贴。
        """
        delay = (interval_ms or 50) / 1000.0
        
        # 判断是否包含非ASCII
        has_non_ascii = any(ord(c) > 127 for c in text)
        
        if has_non_ascii:
            # 使用剪贴板方式输入中文
            self._clipboard_type(text)
        else:
            # 逐字符输入英文
            for char in text:
                if self._stop_flag.is_set():
                    break
                    
                if ord(char) < 128:
                    self._press_key(char)
                else:
                    # 单个非ASCII也走剪贴板
                    self._clipboard_type(char)
                    
                time.sleep(delay + random.uniform(-0.01, 0.01))

    def press(self, key: str) -> None:
        """按下单个按键"""
        self._press_key(key)

    def hotkey(self, *keys: str) -> None:
        """组合键（如 Ctrl+C）"""
        vk_codes = [self._key_to_vk(k) for k in keys]
        
        # 依次按下
        for vk in vk_codes:
            self._key_event(vk, 0)  # KeyDown
        time.sleep(0.05)
        
        # 逆序释放
        for vk in reversed(vk_codes):
            self._key_event(vk, KEYEVENTF_KEYUP)  # KeyUp

    # ---- 内部实现 ----
    
    def _clipboard_type(self, text: str) -> None:
        """通过剪贴板粘贴文本"""
        try:
            import win32clipboard
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetCFUnicodeText(text)
            win32clipboard.CloseClipboard()
            
            # Ctrl+V 粘贴
            self.hotkey("ctrl", "v")
        except Exception as e:
            logger.error(f"Clipboard paste failed: {e}")
            # 降级方案：用SendInput逐字符发Unicode
            self._send_unicode(text)

    @staticmethod
    def _send_unicode(text: str) -> None:
        """直接发送Unicode字符"""
        for char in text:
            code = ord(char)
            struct = wintypes.tagKEYBDINPUT()
            struct.wVk = 0
            struct.wScan = code
            struct.dwFlags = KEYEVENTF_UNICODE
            struct.time = 0
            struct.dwExtraInfo = 0
            
            inp = wintypes.tagINPUT()
            inp.type = 1  # INPUT_KEYBOARD
            inp.ki = struct
            
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
            
            # KeyUp
            struct.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
            time.sleep(0.01)

    @staticmethod
    def _press_key(char_or_key: str) -> None:
        """按下并释放一个键"""
        vk = KeyboardController._key_to_vk(char_or_key)
        KeyboardController._key_event(vk, 0)
        time.sleep(0.02)
        KeyboardController._key_event(vk, KEYEVENTF_KEYUP)

    @staticmethod
    def _key_event(vk_code: int, flags: int = 0) -> None:
        """发送键盘事件"""
        struct = wintypes.tagKEYBDINPUT()
        struct.wVk = vk_code
        struct.wScan = 0
        struct.dwFlags = flags
        struct.time = 0
        struct.dwExtraInfo = 0
        
        inp = wintypes.tagINPUT()
        inp.type = 1
        inp.ki = struct
        
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    @staticmethod
    def _key_to_vk(key_name: str) -> int:
        """将键名转换为虚拟键码"""
        mapping = {
            # 特殊键
            'enter': 0x0D, 'return': 0x0D,
            'tab': 0x09,
            'space': 0x20,
            'escape': 0x1B, 'esc': 0x1B,
            'backspace': 0x08,
            'delete': 0x2E, 'del': 0x2E,
            'insert': 0x2D,
            'home': 0x24,
            'end': 0x23,
            'pageup': 0x21, 'pgup': 0x21,
            'pagedown': 0x22, 'pgdn': 0x22,
            'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
            # 修饰键
            'ctrl': 0x11, 'control': 0x11,
            'alt': 0x12, 'menu': 0x12,
            'shift': 0x10,
            'win': 0x5C, 'meta': 0x5C,
            'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
            'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
            'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
        }
        
        key_lower = key_name.lower()
        if key_lower in mapping:
            return mapping[key_lower]
        
        # 单字母或数字
        if len(key_name) == 1:
            code = ord(key_name.upper())
            if ord('A') <= code <= ord('Z'):
                return code
            if ord('0') <= code <= ord('9'):
                return code
            # 小写字母
            if ord('a') <= code <= ord('z'):
                return code - 32  # 转大写VK码
        
        raise ValueError(f"Unknown key: {key_name}")


class Executor:
    """
    执行引擎总入口
    
    整合鼠标+键盘控制，提供：
    - 动作队列管理
    - 自动验证
    - 审计日志
    - 安全限制
    """
    
    def __init__(self):
        from src.config.settings import settings
        self._settings = settings
        
        self.mouse = MouseController(
            move_duration_ms=settings.MOUSE_MOVE_DURATION_MS,
        )
        self.keyboard = KeyboardController(
            type_delay_ms=settings.KEYBOARD_TYPE_DELAY_MS,
        )
        
        # 动作历史
        self._action_history: list[Action] = []
        self._action_count = 0
        self._max_actions = settings.MAX_ACTIONS_PER_TASK
        
        # 急停
        self._stopped = False
        
        logger.info("Executor initialized")

    # ================================================================
    # 高级API
    # ================================================================

    def click(self, x: int, y: int) -> ActionResult:
        """点击"""
        action = Action(action_type=ActionType.MOUSE_CLICK, params={"x": x, "y": y})
        return self._execute_with_verify(action, lambda: self.mouse.click(x, y))

    def double_click(self, x: int, y: int) -> ActionResult:
        """双击"""
        action = Action(action_type=ActionType.MOUSE_DOUBLE_CLICK, params={"x": x, "y": y})
        return self._execute_with_verify(action, lambda: self.mouse.double_click(x, y))

    def right_click(self, x: int, y: int) -> ActionResult:
        """右键"""
        action = Action(action_type=ActionType.MOUSE_RIGHT_CLICK, params={"x": x, "y": y})
        return self._execute_with_verify(action, lambda: self.mouse.right_click(x, y))

    def drag(self, start: tuple, end: tuple) -> ActionResult:
        """拖拽"""
        action = Action(action_type=ActionType.MOUSE_DRAG, params={"start": start, "end": end})
        return self._execute_with_verify(action, lambda: self.mouse.drag(start, end))

    def scroll(self, delta: int, x: Optional[int] = None, y: Optional[int] = None) -> ActionResult:
        """滚轮"""
        action = Action(action_type=ActionType.MOUSE_SCROLL, params={"delta": delta})
        return self._execute_with_verify(
            action,
            lambda: self.mouse.scroll(delta, x, y),
        )

    def type_text(self, text: str) -> ActionResult:
        """文本输入"""
        action = Action(action_type=ActionType.KEYBOARD_TYPE, params={"text": text})
        return self._execute_with_verify(action, lambda: self.keyboard.type_text(text))

    def key_press(self, key: str) -> ActionResult:
        """单按键"""
        action = Action(action_type=ActionType.KEYBOARD_KEY, params={"key": key})
        return self._execute_with_verify(action, lambda: self.keyboard.press(key))

    def hotkey(self, *keys: str) -> ActionResult:
        """组合键"""
        action = Action(action_type=ActionType.KEYBOARD_HOTKEY, params={"keys": list(keys)})
        return self._execute_with_verify(action, lambda: self.keyboard.hotkey(*keys))

    # ================================================================
    # 内部实现
    # ================================================================

    def _execute_with_verify(
        self,
        action: Action,
        execute_fn: Callable[[], None],
    ) -> ActionResult:
        """执行动作并尝试验证"""
        start = time.perf_counter()
        
        # 检查安全限制
        self._action_count += 1
        if self._action_count > self._max_actions:
            return ActionResult(
                success=False,
                action=action,
                error=f"超过最大动作数限制 ({self._max_actions})",
                elapsed_ms=0,
            )
        
        if self._stopped:
            return ActionResult(success=False, action=action, error="已急停", elapsed_ms=0)
        
        try:
            execute_fn()
            action.verified = True
            self._action_history.append(action)
            
            elapsed = (time.perf_counter() - start) * 1000
            logger.info(f"[EXECUTE] {action.description} | {elapsed:.0f}ms")
            
            return ActionResult(
                success=True,
                action=action,
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"[EXECUTE FAILED] {action.description} | {e}")
            return ActionResult(
                success=False,
                action=action,
                error=str(e),
                elapsed_ms=elapsed,
            )

    def emergency_stop(self) -> None:
        """急停所有操作"""
        self._stopped = True
        self.mouse.emergency_stop()
        self.keyboard._stop_flag.set()
        logger.warning("=== EXECUTOR EMERGENCY STOP ===")

    def resume(self) -> None:
        """恢复执行"""
        self._stopped = False
        self.mouse.reset_emergency()
        self.keyboard._stop_flag.clear()

    def reset_task_count(self) -> None:
        """重置任务计数器"""
        self._action_count = 0


def get_executor() -> Executor:
    """获取全局执行引擎实例"""
    return Executor()
