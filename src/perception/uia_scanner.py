"""
UIA 元素扫描器 - Windows UI Automation 结构化元素获取

通过 Windows Accessibility API 获取窗口树、控件属性、
支持精确元素定位和文本提取。
这是"认知无限"的核心——让AI看到屏幕背后的结构化信息。
"""

import time
import threading
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable
from enum import Enum
import logging

logger = logging.getLogger(__name__)

# ---- 延迟导入 ----
try:
    import comtypes.client
    HAS_COMTYPES = True
except ImportError:
    HAS_COMTYPES = False
    logger.warning("comtypes not installed")


class ElementType(str, Enum):
    """UIA元素类型分类"""
    WINDOW = "window"
    BUTTON = "button"
    TEXT = "text"
    EDIT = "edit"              # 输入框
    LIST = "list"
    LIST_ITEM = "list_item"
    MENU = "menu"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    LINK = "link"
    IMAGE = "image"
    TAB = "tab"
    TOOLBAR = "toolbar"
    STATUSBAR = "statusbar"
    PROGRESS = "progress"
    SLIDER = "slider"
    UNKNOWN = "unknown"


@dataclass
class UIElement:
    """结构化UI元素"""
    name: str                   # 名称/显示文本
    control_type: str           # 控件类型
    automation_id: str          # AutomationId（程序内部ID）
    class_name: str             # Windows类名
    rect: tuple[int, int, int, int]  # (left, top, right, bottom)
    process_id: int             # 所属进程PID
    handle: int                 # 窗口句柄
    is_enabled: bool            # 是否可用
    is_visible: bool            # 是否可见
    value: str = ""             # 当前值（输入框内容等）
    help_text: str = ""         # 帮助文字
    depth: int = 0              # 在树中的深度
    children: list['UIElement'] = field(default_factory=list)

    @property
    def center(self) -> tuple[int, int]:
        """返回元素中心坐标 (x, y)"""
        l, t, r, b = self.rect
        return ((l + r) // 2, (t + b) // 2)

    @property
    def area(self) -> int:
        """元素面积"""
        l, t, r, b = self.rect
        return max(0, (r - l) * (b - t))

    def to_dict(self) -> dict:
        """转为字典（去掉children避免递归爆炸）"""
        d = asdict(self)
        d.pop("children", None)
        return d

    def find_by_name(self, name: str, partial: bool = True) -> Optional['UIElement']:
        """按名称查找自身或子元素"""
        if partial and name.lower() in self.name.lower():
            return self
        elif not partial and name == self.name:
            return self
        for child in self.children:
            result = child.find_by_name(name, partial)
            if result:
                return result
        return None

    def find_by_type(self, type_name: str) -> list['UIElement']:
        """按类型查找所有匹配的子元素"""
        results = []
        if type_name.lower() in self.control_type.lower():
            results.append(self)
        for child in self.children:
            results.extend(child.find_by_type(type_name))
        return results


@dataclass
class WindowInfo:
    """窗口信息摘要"""
    title: str
    class_name: str
    hwnd: int
    pid: int
    rect: tuple[int, int, int, int]
    is_foreground: bool
    state: str  # normal / minimized / maximized / hidden


class UIAScanner:
    """
    Windows UI Automation 扫描器
    
    能力：
    - 遍历桌面/指定窗口的完整UIA树
    - 按名称/类型/位置搜索元素
    - 实时监控窗口变化
    - 提取结构化文本（比OCR更准确）
    """

    def __init__(self, scan_interval_ms: int = 500):
        self._scan_interval_ms = scan_interval_ms
        self._lock = threading.Lock()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._change_callbacks: list[Callable[[list[WindowInfo]], None]] = []
        
        # 缓存上次扫描结果用于增量比较
        self._last_windows: dict[int, WindowInfo] = {}
        
        logger.info(f"UIAScanner init | interval={scan_interval_ms}ms")

    def get_desktop_tree(self, max_depth: int = 5) -> Optional[UIElement]:
        """
        获取桌面的完整UIA树
        
        Args:
            max_depth: 最大遍历深度，防止无限递归
            
        Returns:
            根UIElement（代表桌面）
        """
        try:
            import ctypes
            from ctypes.wintypes import HWND
            
            desktop_hwnd = ctypes.windll.user32.GetDesktopWindow()
            
            if HAS_COMTYPES:
                return self._build_tree_com(desktop_hwnd, max_depth=max_depth)
            else:
                return self._build_tree_win32(desktop_hwnd, max_depth=max_depth)
                
        except Exception as e:
            logger.error(f"Failed to build desktop tree: {e}")
            return None

    def get_window_tree(self, hwnd: int | None = None, max_depth: int = 8) -> Optional[UIElement]:
        """
        获取指定窗口的UIA树
        
        Args:
            hwnd: 窗口句柄，None则获取前台窗口
            max_depth: 最大遍历深度
        """
        if hwnd is None:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
        
        try:
            if HAS_COMTYPES:
                return self._build_tree_com(hwnd, max_depth)
            else:
                return self._build_tree_win32(hwnd, max_depth)
        except Exception as e:
            logger.error(f"Failed to build window tree ({hwnd}): {e}")
            return None

    def list_windows(self) -> list[WindowInfo]:
        """列出当前所有可见窗口"""
        import ctypes
        from ctypes.wintypes import HWND, DWORD, BOOL, RECT, LPARAM
        
        user32 = ctypes.windll.user32
        windows = []
        seen_titles = set()  # 去重
        
        WNDENUMPROC = ctypes.WINFUNCTYPE(BOOL, HWND, LPARAM)

        def enum_callback(hwnd, lp):
            nonlocal windows
            # 过滤不可见窗口
            if not user32.IsWindowVisible(hwnd):
                return True
            
            # 获取标题
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            title = buf.value.strip()
            if not title or len(title) < 3 or title in seen_titles:
                seen_titles.add(title)
                return True
            seen_titles.add(title)
            
            # 获取类名
            class_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buf, 256)
            class_name = class_buf.value
            
            # 获取矩形区域
            rect = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            
            # 获取进程ID
            pid = DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            
            # 判断是否为前台窗口
            is_fg = (hwnd == user32.GetForegroundWindow())
            
            # 判断窗口状态
            if user32.IsIconic(hwnd):
                state = "minimized"
            elif user32.IsZoomed(hwnd):
                state = "maximized"
            else:
                state = "normal"

            windows.append(WindowInfo(
                title=title,
                class_name=class_name,
                hwnd=hwnd,
                pid=pid.value,
                rect=(rect.left, rect.top, rect.right, rect.bottom),
                is_foreground=is_fg,
                state=state,
            ))
            return True

        callback = WNDENUMPROC(enum_callback)
        user32.EnumWindows(callback, 0)
        
        # 按前台优先排序
        windows.sort(key=lambda w: (not w.is_foreground, w.title))
        return windows

    def get_foreground_window_info(self) -> Optional[WindowInfo]:
        """获取当前前台窗口信息"""
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return None
        
        windows = self.list_windows()
        for w in windows:
            if w.hwnd == hwnd:
                return w
        return None

    def find_element(
        self,
        query: str,
        *,
        hwnd: Optional[int] = None,
        search_type: str = "name",  # name / type / automation_id
        fuzzy: bool = True,
    ) -> list[UIElement]:
        """
        在窗口中搜索元素
        
        Args:
            query: 搜索关键词
            hwnd: 目标窗口，None=前台窗口
            search_type: 搜索类型
            fuzzy: 是否模糊匹配
            
        Returns:
            匹配的元素列表
        """
        tree = self.get_window_tree(hwnd)
        if not tree:
            return []

        results = []
        self._search_recursive(tree, query, search_type, fuzzy, results)
        return results

    def _search_recursive(
        self,
        element: UIElement,
        query: str,
        search_type: str,
        fuzzy: bool,
        results: list[UIElement],
    ) -> None:
        """递归搜索"""
        target_value = ""
        match search_type:
            case "name":
                target_value = element.name
            case "type":
                target_value = element.control_type
            case "automation_id":
                target_value = element.automation_id
            case _:
                target_value = f"{element.name} {element.control_type}"

        if fuzzy and query.lower() in target_value.lower():
            results.append(element)
        elif not fuzzy and query == target_value:
            results.append(element)

        for child in element.children:
            self._search_recursive(child, query, search_type, fuzzy, results)

    def _build_tree_com(self, hwnd: int, max_depth: int = 8) -> UIElement:
        """使用comtypes构建UIA树（更详细）"""
        # TODO: 使用IUIAutomation接口获取完整UIA树
        # 目前降级到Win32实现
        return self._build_tree_win32(hwnd, max_depth)

    def _build_tree_win32(self, root_hwnd: int, max_depth: int = 8) -> UIElement:
        """使用纯Win32 API构建简化版窗口树"""
        import ctypes
        from ctypes.wintypes import HWND, DWORD, BOOL, RECT
        
        user32 = ctypes.wind32.user32
        
        # 获取根窗口信息
        title_buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(root_hwnd, title_buf, 512)
        
        class_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(root_hwnd, class_buf, 256)
        
        rect = RECT()
        user32.GetWindowRect(root_hwnd, ctypes.byref(rect))
        
        pid = DWORD()
        user32.GetWindowThreadProcessId(root_hwnd, ctypes.byref(pid))
        
        root = UIElement(
            name=title_buf.value,
            control_type="window",
            automation_id="",
            class_name=class_buf.value,
            rect=(rect.left, rect.top, rect.right, rect.bottom),
            process_id=pid.value,
            handle=root_hwnd,
            is_enabled=True,
            is_visible=True,
            depth=0,
        )
        
        if max_depth > 0:
            self._enum_child_windows(root_hwnd, root, max_depth - 1)
        
        return root

    def _enum_child_windows(
        self,
        parent_hwnd: int,
        parent_elem: UIElement,
        remaining_depth: int,
    ) -> None:
        """枚举子窗口"""
        if remaining_depth <= 0:
            return
        
        import ctypes
        from ctypes.wintypes import HWND, DWORD, BOOL, RECT, LPARAM
        
        user32 = ctypes.wind32.user32
        children = []

        WNDENUMPROC = ctypes.WINFUNCTYPE(BOOL, HWND, LPARAM)

        def enum_child_cb(hwnd, lp):
            nonlocal children
            
            if not user32.IsWindowVisible(hwnd):
                return True
            
            title_buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, title_buf, 512)
            title = title_buf.value
            
            class_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buf, 256)
            class_name = class_buf.value
            
            rect = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            
            elem = UIElement(
                name=title or f"[{class_name}]",
                control_type=self._guess_control_type(class_name),
                automation_id="",
                class_name=class_name,
                rect=(rect.left, rect.top, rect.right, rect.bottom),
                process_id=0,
                handle=hwnd,
                is_enabled=True,
                is_visible=True,
                depth=parent_elem.depth + 1,
            )
            children.append((hwnd, elem))
            return True

        callback = WNDENUMPROC(enum_child_cb)
        user32.EnumChildWindows(parent_hwnd, callback, 0)
        
        for child_hwnd, child_elem in children:
            parent_elem.children.append(child_elem)
            self._enum_child_windows(child_hwnd, child_elem, remaining_depth - 1)

    def _guess_control_type(self, class_name: str) -> str:
        """根据Windows类名猜测控件类型"""
        mapping = {
            "Button": "button",
            "Edit": "edit",
            "ComboBox": "combobox",
            "ListBox": "list",
            "ListView": "list",
            "TreeView": "tree_view",
            "Static": "text",
            "ScrollBar": "scroll_bar",
            "Toolbar": "toolbar",
            "StatusBar": "statusbar",
            "Tab": "tab",
            "ProgressBar": "progress",
            "Slider": "slider",
            "CheckBox": "checkbox",
            "RadioButton": "radio",
            "Link": "link",
        }
        for key, value in mapping.items():
            if key.lower() in class_name.lower():
                return value
        return "unknown"

    def to_structured_text(self, tree: Optional[UIElement]) -> str:
        """
        将UIA树转为结构化文本（可发给LLM分析）
        
        格式：
        [Window: Chrome]
          ├─ [Button: 关闭] (1234, 56, 1279, 89)
          ├─ [Tab: 新标签页] ...
          └─ [Edit: 地址栏] (...)
        """
        if tree is None:
            return "(无UI元素)"
        
        lines = []
        self._tree_to_lines(tree, lines, prefix="")
        return "\n".join(lines)

    def _tree_to_lines(self, elem: UIElement, lines: list[str], prefix: str) -> None:
        """递归转行"""
        cx, cy = elem.center
        line = (
            f"{prefix}[{elem.control_type}: {elem.name}] "
            f"@({cx}, {cy}) "
            f"area={elem.area}"
        )
        if elem.value:
            line += f' value="{elem.value}"'
        lines.append(line)
        
        for i, child in enumerate(elem.children):
            connector = "├─ " if i < len(elem.children) - 1 else "└─ "
            self._tree_to_lines(child, lines, prefix + ("│   " if i < len(elem.children) - 1 else "    "))

    # ================================================================
    # 变化监控
    # ================================================================

    def detect_window_changes(self) -> tuple[list[WindowInfo], list[WindowInfo]]:
        """检测窗口列表变化，返回(新增,消失)的窗口"""
        current = {w.hwnd: w for w in self.list_windows()}
        
        new_windows = [w for hwnd, w in current.items()
                      if hwnd not in self._last_windows]
        gone_windows = [w for hwnd, w in self._last_windows.items()
                       if hwnd not in current]
        
        self._last_windows = current
        return new_windows, gone_windows

    def start_monitoring(self) -> None:
        """开始后台窗口变化监控"""
        if self._running:
            return
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop_monitoring(self) -> None:
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2.0)

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                new_wins, gone_wins = self.detect_window_changes()
                if new_wins or gone_wins:
                    all_windows = self.list_windows()
                    for cb in self._change_callbacks:
                        cb(all_windows)
            except Exception as e:
                logger.error(f"Monitor error: {e")
            time.sleep(self._scan_interval_ms / 1000.0)


def get_uia_scanner() -> UIAScanner:
    """获取全局UIA扫描器实例"""
    return UIAScanner()
