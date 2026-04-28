"""
UIA 元素扫描器 - Windows UI Automation 完整实现

通过 COM IUIAutomation 接口获取完整的UI元素树，
支持精确元素定位、控制模式调用、浏览器DOM桥接。
这是"认知无限"的核心——让AI看到屏幕背后的完整结构化信息。

## 架构说明
- 真UIA: comtypes → IUIAutomation → 完整控件树（Chrome/VSCode/Electron全可见）
- 降级方案: Win32 EnumChildWindows（传统Win32应用备用）
- 双引擎: 自动检测，优先真UIA，失败时降级
"""

import time
import threading
import ctypes
from ctypes.wintypes import HWND, DWORD, BOOL, RECT, LPARAM
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable
from enum import Enum, IntEnum, IntFlag
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)

# ---- 延迟导入 ----
try:
    import comtypes
    from comtypes import GUID, IUnknown
    from comtypes.automation import IDispatch
    HAS_COMTYPES = True
except ImportError:
    HAS_COMTYPES = False
    logger.warning("comtypes not installed - UIA will use Win32 fallback")


# ================================================================
# UIA 常量定义
# ================================================================

class ControlType(IntEnum):
    """UIA 控件类型ID (UIA_ControlTypePropertyId = 30003)"""
    BUTTON = 50000
    CALENDAR = 50001
    CHECK_BOX = 50002
    COMBO_BOX = 50003
    GRID = 50028
    GRID_ITEM = 50029
    GROUP = 50026
    HEADER = 50034
    HEADER_ITEM = 50035
    HYPERLINK = 50005
    IMAGE = 50006
    LIST = 50008
    LIST_ITEM = 50007
    MENU = 50009
    MENU_BAR = 50010
    MENU_ITEM = 50011
    PANE = 50033
    PROGRESS_BAR = 50010
    RADIO_BUTTON = 50011
    SCROLL_BAR = 50012
    SEPARATOR = 50027
    SLIDER = 50013
    SPINNER = 50014
    SPLIT_BUTTON = 50037
    STATUS_BAR = 50015
    TAB = 50016
    TAB_ITEM = 50017
    TEXT = 50020
    TOOLBAR = 50018
    TOOL_TIP = 50019
    TREE = 50021
    TREE_ITEM = 50022
    WINDOW = 50032
    CUSTOM = 50025
    TITLE_BAR = 50036
    SEMI_EDIT = 50004   # Document/编辑区
    THUMB = 50038
    DATA_GRID = 50039
    DATA_ITEM = 50040


# 控件类型ID → 可读名称映射
CONTROL_TYPE_NAMES = {
    50000: "Button", 50001: "Calendar", 50002: "CheckBox",
    50003: "ComboBox", 50004: "Edit", 50005: "Hyperlink",
    50006: "Image", 50007: "ListItem", 50008: "List",
    50009: "Menu", 50010: "MenuBar", 50011: "MenuItem",
    50012: "ScrollBar", 50013: "Slider", 50014: "Spinner",
    50015: "StatusBar", 50016: "Tab", 50017: "TabItem",
    50018: "Toolbar", 50019: "ToolTip", 50020: "Text",
    50021: "Tree", 50022: "TreeItem", 50025: "Custom",
    50026: "Group", 50027: "Separator", 50028: "Grid",
    50029: "GridItem", 50032: "Window", 50033: "Pane",
    50034: "Header", 50035: "HeaderItem", 50036: "TitleBar",
    50037: "SplitButton", 50038: "Thumb", 50039: "DataGrid",
    50040: "DataItem",
}


class UIA_PropertyIDs(IntEnum):
    """关键 UIA 属性ID"""
    NamePropertyId = 30005
    ControlTypePropertyId = 30003
    LocalizedControlTypePropertyId = 30004
    BoundingRectanglePropertyId = 30001
    ProcessIdPropertyId = 30002
    ClassNamePropertyId = 30012
    AutomationIdPropertyId = 30011
    NativeWindowHandlePropertyId = 30014
    IsEnabledPropertyId = 30009
    IsOffscreenPropertyId = 30022
    HelpTextPropertyId = 30013
    ItemStatusPropertyId = 30026
    ItemTypePropertyId = 30025
    ValueValuePropertyId = 30045
    ValueIsReadOnlyPropertyId = 30048
    RangeValueValuePropertyId = 30054
    RangeValueMinimumPropertyId = 30051
    RangeValueMaximumPropertyId = 30052
    ToggleToggleStatePropertyId = 30056
    SelectionSelectionContainerPropertyId = 30061
    LegacyIAccessibleStatePropertyId = 30069
    OrientationPropertyId = 30021
    AcceleratorKeyPropertyId = 30010
    AccessKeyPropertyId = 30008
    IsPasswordPropertyId = 30029
    IsKeyboardFocusablePropertyId = 30047
    HasKeyboardFocusPropertyId = 30046
    RuntimeIdPropertyId = 30011
    FrameworkIdPropertyId = 30024
    ProviderDescriptionPropertyId = 30023
    IsContentElementPropertyId = 30060
    IsControlElementPropertyId = 30059
    ControllerForPropertyId = 30073
    DescribedByPropertyId = 30074
    FlowsToPropertyId = 30075
    FlowsFromPropertyId = 30076
    LiveSettingPropertyId = 30077
    CulturePropertyId = 30023
    IsPeripheralPropertyId = 30078
    PositionInSetPropertyId = 30079
    SizeOfSetPropertyId = 30080
    LevelPropertyId = 30081
    AnnotationsPropertyId = 30082
    LandmarkTypePropertyId = 30083


# 浏览器特有Framework标识
BROWSER_FRAMEWORKS = {"Edge", "Chrome", "MozillaFirefox", "Webkit"}
ELECTRON_FRAMEWORKS = {"Electron", "Chromium", "CEF"}


class PatternID(IntEnum):
    """UIA 控制模式(接口)ID"""
    InvokePatternId = 10000
    SelectionPatternId = 10001
    ValuePatternId = 10002
    RangeValuePatternId = 10003
    ScrollPatternId = 10004
    ExpandCollapsePatternId = 10005
    GridPatternId = 10006
    GridItemPatternId = 10007
    MultipleViewPatternId = 10008
    WindowPatternId = 10009
    SelectionItemPatternId = 10010
    DockPatternId = 10011
    TablePatternId = 10012
    TableItemPatternId = 10013
    TextPatternId = 10014
    TogglePatternId = 10015
    TransformPatternId = 10016
    ScrollItemPatternId = 10017
    LegacyIAccessiblePatternId = 10018
    ItemContainerPatternId = 10019
    VirtualizedItemPatternId = 10020
    SynchronizedInputPatternId = 10021
    ObjectModelPatternId = 10022
    AnnotationPatternId = 10023
    TextPattern2 = 10024
    StylesPatternId = 10025
    SpreadsheetPatternId = 10026
    SpreadsheetItemPatternId = 10027
    TransformPattern2 = 10028
    CustomNavigationPatternId = 10029
    SelectionPattern2 = 10030
    TextChildPatternId = 10031
    DragPatternId = 10032
    DropTargetPatternId = 10033
    TextEditPatternId = 10034


# ================================================================
# 数据结构
# ================================================================

class ElementType(str, Enum):
    """UI元素类型分类（兼容旧接口）"""
    WINDOW = "window"
    BUTTON = "button"
    TEXT = "text"
    EDIT = "edit"
    LIST = "list"
    LIST_ITEM = "list_item"
    MENU = "menu"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    LINK = "link"
    IMAGE = "image"
    TAB = "tab"
    TAB_ITEM = "tab_item"
    TOOLBAR = "toolbar"
    STATUSBAR = "statusbar"
    PROGRESS = "progress"
    SLIDER = "slider"
    GROUP = "group"
    PANE = "pane"
    GRID = "grid"
    TREE = "tree"
    TREE_ITEM = "tree_item"
    HYPERLINK = "hyperlink"
    COMBOBOX = "combobox"
    SPINNER = "spinner"
    SPLITBUTTON = "split_button"
    TITLEBAR = "titlebar"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


@dataclass
class UIElement:
    """结构化UI元素——真UIA的完整信息"""
    # ---- 基础身份 ----
    name: str = ""                    # NamePropertyId - 显示文本/名称
    control_type_id: int = 0          # ControlTypePropertyId - 数值ID
    control_type: str = "unknown"     # 可读名称(Button/Edit/Text...)
    localized_type: str = ""          # LocalizedControlTypePropertyId

    # ---- 定位信息 ----
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)  # BoundingRectanglePropertyId
    center: tuple[int, int] = (0, 0)
    native_handle: int = 0            # NativeWindowHandlePropertyId (HWND)

    # ---- 进程与框架 ----
    process_id: int = 0               # ProcessIdPropertyId
    class_name: str = ""              # ClassNamePropertyId
    automation_id: str = ""           # AutomationIdPropertyId
    framework_id: str = ""            # FrameworkIdPropertyId (Win32/WPF/Electron/Chrome)

    # ---- 状态 ----
    is_enabled: bool = True           # IsEnabledPropertyId
    is_visible: bool = True           # !IsOffscreenPropertyId
    has_focus: bool = False           # HasKeyboardFocusPropertyId
    is_password: bool = False         # IsPasswordPropertyId
    is_content_element: bool = True   # IsContentElementPropertyId
    is_control_element: bool = True   # IsControlElementPropertyId

    # ---- 值与内容 ----
    value: str = ""                   # 当前值(输入框/文本)
    help_text: str = ""               # HelpTextPropertyId
    accelerator_key: str = ""         # 快捷键
    access_key: str = ""              # 访问键
    item_type: str = ""               # ItemTypePropertyId
    item_status: str = ""             # ItemStatusPropertyId
    orientation: str = ""             # OrientationPropertyId

    # ---- 树结构 ----
    depth: int = 0
    runtime_id: str = ""              # RuntimeIdPropertyId (唯一标识)
    children: list['UIElement'] = field(default_factory=list)

    # ---- 控制模式能力 ----
    supported_patterns: list[str] = field(default_factory=list)

    # ---- 内部引用(不序列化) ----
    _raw_ref = field(default=None, repr=False, compare=False)  # comtypes原始对象

    @property
    def area(self) -> int:
        l, t, r, b = self.rect
        return max(0, (r - l) * (b - t))

    @property
    def width(self) -> int:
        return max(0, self.rect[2] - self.rect[0])

    @property
    def height(self) -> int:
        return max(0, self.rect[3] - self.rect[1])

    @property
    def is_browser_element(self) -> bool:
        """是否为浏览器内部DOM元素"""
        return self.framework_id in BROWSER_FRAMEWORKS or self.framework_id in ELECTRON_FRAMEWORKS

    @property
    def is_interactive(self) -> bool:
        """是否为可交互元素"""
        interactive_types = {
            "button", "edit", "checkbox", "radio", "link", "hyperlink",
            "combobox", "list_item", "tab", "tab_item", "tree_item",
            "menu_item", "split_button", "slider", "spinner",
        }
        return self.control_type in interactive_types and self.is_enabled and self.is_visible

    def to_dict(self, flat: bool = True) -> dict:
        d = asdict(self)
        if flat:
            d.pop("children", None)
        d.pop("_raw_ref", None)
        return d

    def find_by_name(self, name: str, partial: bool = True) -> Optional['UIElement']:
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
        results = []
        if type_name.lower() in self.control_type.lower():
            results.append(self)
        for child in self.children:
            results.extend(child.find_by_type(type_name))
        return results

    def find_by_automation_id(self, aid: str) -> Optional['UIElement']:
        if aid == self.automation_id:
            return self
        for child in self.children:
            result = child.find_by_automation_id(aid)
            if result:
                return result
        return None

    def get_interactive_children(self) -> list['UIElement']:
        """获取所有可交互的子元素"""
        results = []
        if self.is_interactive and self.depth > 0:
            results.append(self)
        for child in self.children:
            results.extend(child.get_interactive_children())
        return results

    def count_elements(self) -> int:
        """递归统计元素总数"""
        count = 1
        for child in self.children:
            count += child.count_elements()
        return count


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
    framework_id: str = ""  # UIA framework info


@dataclass
class UISnapshot:
    """一次UI扫描的快照结果"""
    timestamp: float = 0.0
    foreground_window: Optional[WindowInfo] = None
    all_windows: list[WindowInfo] = field(default_factory=list)
    element_tree: Optional[UIElement] = None
    interactive_elements: list[UIElement] = field(default_factory=list)
    text_content: str = ""  # 提取的所有可读文字
    total_elements: int = 0
    scan_duration_ms: float = 0.0
    engine: str = "win32"  # "uia" or "win32"


# ================================================================
# 控制模式封装
# ================================================================

class ControlPattern(ABC):
    """UIA控制模式基类"""

    @abstractmethod
    def execute(self):
        pass


class InvokePattern(ControlPattern):
    """点击/触发按钮、链接等"""
    def __init__(self, raw_pattern):
        self._raw = raw_pattern

    def invoke(self):
        try:
            self._raw.Invoke()
            return True
        except Exception as e:
            logger.warning(f"Invoke failed: {e}")
            return False


class ValuePattern(ControlPattern):
    """读取/设置输入框、文本等值"""
    def __init__(self, raw_pattern):
        self._raw = raw_pattern

    @property
    def value(self) -> str:
        try:
            return self._raw.Value or ""
        except Exception:
            return ""

    @value.setter
    def value(self, new_val: str):
        try:
            self._raw.SetValue(new_val)
        except Exception as e:
            logger.warning(f"SetValue failed: {e}")

    @property
    def is_readonly(self) -> bool:
        try:
            return self._raw.IsReadOnly
        except Exception:
            return True


class TogglePattern(ControlPattern):
    """复选框、开关切换"""
    def __init__(self, raw_pattern):
        self._raw = raw_pattern

    def toggle(self) -> int:
        try:
            self._raw.Toggle()
            return self.current_state
        except Exception as e:
            logger.warning(f"Toggle failed: {e}")
            return -1

    @property
    def current_state(self) -> int:
        try:
            return self._raw.CurrentToggleState  # 0=Off, 1=On, 2=Indeterminate
        except Exception:
            return -1

    @property
    def state_name(self) -> str:
        names = {0: "Off", 1: "On", 2: "Indeterminate"}
        return names.get(self.current_state, f"Unknown({self.current_state})")


class SelectionItemPattern(ControlPattern):
    """列表项/标签页选择"""
    def __init__(self, raw_pattern):
        self._raw = raw_pattern

    def select(self):
        try:
            self._raw.Select()
            return True
        except Exception as e:
            logger.warning(f"Select failed: {e}")
            return False


class ExpandCollapsePattern(ControlPattern):
    """树节点/菜单展开折叠"""
    def __init__(self, raw_pattern):
        self._raw = raw_pattern

    def expand(self):
        try:
            self._raw.Expand()
            return True
        except Exception as e:
            logger.warning(f"Expand failed: {e}")
            return False

    def collapse(self):
        try:
            self._raw.Collapse()
            return True
        except Exception as e:
            logger.warning(f"Collapse failed: {e}")
            return False

    @property
    def state(self) -> int:
        try:
            return self._raw.CurrentExpandCollapseState
        except Exception:
            return 0

    @property
    def is_expanded(self) -> bool:
        return self.state == 1  # Expanded=1, Collapsed=0, PartiallyExpanded=2


class WindowPattern(ControlPattern):
    """窗口操作(最大化/最小化/关闭等)"""
    def __init__(self, raw_pattern):
        self._raw = raw_pattern

    @property
    def window_visual_state(self) -> int:
        try:
            return self._raw.CurrentWindowVisualState
        except Exception:
            return 0  # Normal=1, Maximized=2, Minimized=3

    @property
    def can_maximize(self) -> bool:
        try:
            return self._raw.CurrentCanMaximize
        except Exception:
            return False

    @property
    def can_minimize(self) -> bool:
        try:
            return self._raw.CurrentCanMinimize
        except Exception:
            return False

    def set_window_state(self, state: str):
        """设置窗口状态: maximize/minimize/normal/close"""
        mapping = {
            "maximize": lambda: self._raw.SetWindowVisualState(2),
            "minimize": lambda: self._raw.SetWindowVisualState(3),
            "normal": lambda: self._raw.SetWindowVisualState(1),
            "close": lambda: self._raw.Close(),
        }
        action = mapping.get(state)
        if action:
            try:
                action()
                return True
            except Exception as e:
                logger.warning(f"Window operation '{state}' failed: {e}")
        return False


class RangeValuePattern(ControlPattern):
    """滑块/进度条等范围值"""
    def __init__(self, raw_pattern):
        self._raw = raw_pattern

    @property
    def value(self) -> float:
        try:
            return self._raw.CurrentValue
        except Exception:
            return 0.0

    @value.setter
    def value(self, val: float):
        try:
            self._raw.SetValue(val)
        except Exception as e:
            logger.warning(f"RangeValue.SetValue failed: {e}")

    @property
    def minimum(self) -> float:
        try:
            return self._raw.CurrentMinimum
        except Exception:
            return 0.0

    @property
    def maximum(self) -> float:
        try:
            return self._raw.CurrentMaximum
        except Exception:
            return 100.0


# ================================================================
# 真正的 UIA 引擎 (IUIAutomation via comtypes)
# ================================================================

class _UIAEngine:
    """
    IUIAutomation COM 接口的 Python 封装
    
    通过 comtypes 调用 Windows UI Automation API，
    能看到所有标准控件的完整属性和控制模式。
    
    支持: Chrome, Edge, Firefox, VSCode, Electron, WPF,
          WinForms, Qt, 以及几乎所有现代桌面应用。
    """

    # 单例缓存
    _instance: Optional['_UIAEngine'] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return

        if not HAS_COMTYPES:
            raise RuntimeError("comtypes not available")

        self._automation = None
        self._initialized = False
        self._init_com()

    def _init_com(self):
        """初始化COM并创建IUIAutomation实例"""
        try:
            import comtypes.client

            # 初始化COM线程
            comtypes.CoInitialize()

            # 创建 IUIAutomation 实例
            clsid_uia = comtypes.GUID("{FF48DBA4-60EF-4201-AA87-54103EEF594E}")
            iid_iuia = comtypes.GUID("{30CBE57D-D9D0-452A-AB21-7436DC6C6DB6}")

            self._automation = comtypes.CoCreateInstance(
                clsid_uia,
                interface=comtypes.IUnknown,
                context=comtypes.CLSCTX_INPROC_SERVER
            ).QueryInterface(comtypes.IID_IAccessible)

            # 备选方式：直接从 ProgID
            if self._automation is None:
                self._automation = comtypes.client.CreateObject(
                    "{FF48DBA4-60EF-4201-AA87-54103EEF594E}",
                    interface=comtypes.IUnknown
                )

            self._initialized = True
            logger.info("✅ IUIAutomation initialized via COM")
            return True

        except Exception as e:
            logger.error(f"IUIAutomation init failed: {e}")
            self._initialized = False
            return False

    @property
    def is_available(self) -> bool:
        return self._initialized and self._automation is not None

    def get_root_element(self):
        """获取桌面根元素"""
        if not self.is_available:
            return None
        try:
            return self._automation.GetRootElement()
        except Exception as e:
            logger.error(f"GetRootElement failed: {e}")
            return None

    def element_from_handle(self, hwnd: int):
        """从窗口句柄获取UIA元素"""
        if not self.is_available:
            return None
        try:
            return self._automation.ElementFromHandle(hwnd)
        except Exception as e:
            logger.warning(f"ElementFromHandle({hwnd}) failed: {e}")
            return None

    def element_from_point(self, x: int, y: int):
        """从屏幕坐标获取UIA元素"""
        if not self.is_available:
            return None
        try:
            tagPOINT = ctypes.c_long * 2
            pt = tagPOINT(x, y)
            return self._automation.ElementFromPoint(pt)
        except Exception as e:
            logger.warning(f"ElementFromPoint({x},{y}) failed: {e}")
            return None

    def get_focused_element(self):
        """获取当前焦点元素"""
        if not self.is_available:
            return None
        try:
            return self._automation.GetFocusedElement()
        except Exception as e:
            logger.warning(f"GetFocusedElement failed: {e}")
            return None

    def find_first(self, root, scope: int, condition):
        """查找第一个匹配元素"""
        if not self.is_available:
            return None
        try:
            return root.FindFirst(scope, condition)
        except Exception as e:
            logger.debug(f"FindFirst failed: {e}")
            return None

    def find_all(self, root, scope: int, condition):
        """查找所有匹配元素"""
        if not self.is_available:
            return None
        try:
            return root.FindAll(scope, condition)
        except Exception as e:
            logger.debug(f"FindAll failed: {e}")
            return None

    def create_property_condition(self, prop_id: int, value):
        """创建属性条件"""
        try:
            return self._automation.CreatePropertyCondition(prop_id, value)
        except Exception as e:
            logger.debug(f"CreatePropertyCondition({prop_id}, {value}) failed: {e}")
            return None

    def create_true_condition(self):
        """创建匹配所有元素的条件"""
        try:
            return self._automation.CreateTrueCondition()
        except Exception:
            return None

    def create_and_condition(self, cond1, cond2):
        """创建AND组合条件"""
        if cond1 is None or cond2 is None:
            return cond1 or cond2
        try:
            return self._automation.CreateAndCondition(cond1, cond2)
        except Exception:
            return None

    def create_or_condition(self, cond1, cond2):
        """创建OR组合条件"""
        if cond1 is None or cond2 is None:
            return cond1 or cond2
        try:
            return self._automation.CreateOrCondition(cond1, cond2)
        except Exception:
            return None

    def get_view_conditions(self):
        """获取'只看控件元素'的条件"""
        try:
            return self._automation.ControlViewCondition
        except Exception:
            return self.create_true_condition()


# 搜索范围常量
class TreeScope(IntFlag):
    Element = 0x1
    Children = 0x2
    Descendants = 0x4
    Parent = 0x8
    Ancestors = 0x10
    Subtree = Element | Children | Descendants


# ================================================================
# 属性提取工具
# ================================================================

def _extract_rect(raw_elem) -> tuple[int, int, int, int]:
    """提取BoundingRectangle (l,t,r,b)"""
    try:
        rect = raw_elem.CurrentBoundingRectangle
        return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    except Exception:
        return (0, 0, 0, 0)


def _extract_string_prop(raw_elem, prop_id: int, default: str = "") -> str:
    """安全提取字符串属性"""
    try:
        val = raw_elem.GetCurrentPropertyValue(prop_id)
        if val is None:
            return default
        s = str(val).strip()
        return s if s else default
    except Exception:
        return default


def _extract_int_prop(raw_elem, prop_id: int, default: int = 0) -> int:
    """安全提取整数属性"""
    try:
        val = raw_elem.GetCurrentPropertyValue(prop_id)
        return int(val) if val is not None else default
    except Exception:
        return default


def _extract_bool_prop(raw_elem, prop_id: int, default: bool = False) -> bool:
    """安全提取布尔属性"""
    try:
        val = raw_elem.GetCurrentPropertyValue(prop_id)
        return bool(val) if val is not None else default
    except Exception:
        return default


def _detect_supported_patterns(raw_elem) -> list[str]:
    """检测元素支持的控制模式"""
    patterns = []
    pattern_checks = [
        (PatternID.InvokePatternId, "invoke"),
        (PatternID.ValuePatternId, "value"),
        (PatternID.TogglePatternId, "toggle"),
        (PatternID.SelectionItemPatternId, "selection_item"),
        (PatternID.ExpandCollapsePatternId, "expand_collapse"),
        (PatternID.WindowPatternId, "window"),
        (PatternID.RangeValuePatternId, "range_value"),
        (PatternID.ScrollPatternId, "scroll"),
        (PatternID.GridPatternId, "grid"),
        (PatternID.GridItemPatternId, "grid_item"),
        (PatternID.TablePatternId, "table"),
        (PatternID.TableItemPatternId, "table_item"),
        (PatternID.TextPatternId, "text"),
        (PatternID.SelectionPatternId, "selection"),
        (PatternID.LegacyIAccessiblePatternId, "legacy_accessible"),
        (PatternID.TransformPatternId, "transform"),
        (PatternID.CustomNavigationPatternId, "custom_navigation"),
    ]
    for pid, pname in pattern_checks:
        try:
            if raw_elem.GetCurrentPropertyValue(pid + 100000):  # IsPatternAvailable偏移
                patterns.append(pname)
        except Exception:
            pass
        # 备选检查方式
        try:
            curr_pat = raw_elem.GetCurrentPattern(pid)
            if curr_pat is not None and pname not in patterns:
                patterns.append(pname)
        except Exception:
            pass
    return patterns


def _get_pattern(raw_elem, pattern_id: int):
    """获取控制模式的原始接口"""
    try:
        return raw_elem.GetCurrentPattern(pattern_id)
    except Exception:
        return None


def _control_type_id_to_name(ct_id: int) -> str:
    return CONTROL_TYPE_NAMES.get(ct_id, f"Custom_{ct_id}")


# ================================================================
# 主类: UIAScanner
# ================================================================

class UIAScanner:
    """
    Windows UI Automation 扫描器 — 双引擎架构
    
    主引擎: comtypes IUIAutomation (真UIA，能看透Chrome/VSCode/Electron)
    备用引擎: Win32 EnumChildWindows (传统Win32应用兜底)
    
    能力：
    - 遍历桌面/指定窗口的完整UIA树（可达数百个元素）
    - 按名称/类型/AutomationID/位置搜索元素
    - 控制模式调用（点击/输入值/勾选/选择/展开）
    - 实时监控窗口变化
    - 结构化文本输出（可直接发给LLM分析）
    """

    def __init__(self, scan_interval_ms: int = 500):
        self._scan_interval_ms = scan_interval_ms
        self._lock = threading.Lock()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._change_callbacks: list[Callable[[list[WindowInfo]], None]] = []

        # 缓存上次扫描结果用于增量比较
        self._last_windows: dict[int, WindowInfo] = {}

        # UIA引擎
        self._engine: Optional[_UIAEngine] = None
        self._use_real_uia: bool = False  # 是否使用真UIA

        # 性能配置
        self.default_max_depth = 8        # 默认遍历深度
        self.desktop_max_depth = 4        # 桌面层级限制（防止爆炸）

        # 元素过滤规则
        self.filter_invisible = True       # 过滤不可见元素
        self.filter_no_name = False        # 过滤无名称元素（默认保留）
        self.min_element_area = 0          # 最小元素面积过滤

        self._ensure_engine()
        logger.info(
            f"UIAScanner init | interval={scan_interval_ms}ms | "
            f"engine={'IUIAutomation(COM)' if self._use_real_uia else 'Win32(Fallback)'}"
        )

    # ----------------------------------------------------------------
    # 引擎管理
    # ----------------------------------------------------------------

    def _ensure_engine(self):
        """确保引擎可用"""
        if HAS_COMTYPES:
            try:
                self._engine = _UIAEngine()
                self._use_real_uia = self._engine.is_available
            except Exception as e:
                logger.warning(f"Real UIA unavailable: {e} — using Win32 fallback")
                self._use_real_uia = False
        else:
            self._use_real_uia = False

    @property
    def using_real_uia(self) -> bool:
        """当前是否使用真UIA引擎"""
        return self._use_real_uia

    @property
    def engine_status(self) -> str:
        if self._use_real_uia:
            return f"✅ Real UIA (IUIAutomation via COM)"
        elif HAS_COMTYPES:
            return f"⚠️  Win32 Fallback (comtypes installed but UIA init failed)"
        else:
            return f"❌ Pure Win32 (no comtypes)"

    # ----------------------------------------------------------------
    # 核心：树构建
    # ----------------------------------------------------------------

    def get_desktop_tree(self, max_depth: int = 4) -> Optional[UIElement]:
        """
        获取桌面的完整UIA树
        
        Args:
            max_depth: 最大遍历深度（桌面建议≤4层，否则元素爆炸）
            
        Returns:
            根UIElement（代表桌面），包含所有顶层窗口及其子控件
        """
        t0 = time.perf_counter()

        if self._use_real_uia and self._engine:
            tree = self._build_tree_uia_root(max_depth=max_depth)
        else:
            desktop_hwnd = ctypes.windll.user32.GetDesktopWindow()
            tree = self._build_tree_win32(desktop_hwnd, max_depth=max_depth)

        elapsed = (time.perf_counter() - t0) * 1000
        if tree:
            logger.info(f"Desktop tree: {tree.count_elements()} elements, {elapsed:.1f}ms, depth={max_depth}")
        return tree

    def get_window_tree(self, hwnd: int | None = None, max_depth: int = 8) -> Optional[UIElement]:
        """
        获取指定窗口的完整UIA树
        
        Args:
            hwnd: 窗口句柄，None则获取前台窗口
            max_depth: 最大遍历深度（单个窗口可用更深）
            
        Returns:
            根UIElement（代表该窗口）
        """
        t0 = time.perf_counter()

        if hwnd is None:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return None

        if self._use_real_uia and self._engine:
            tree = self._build_tree_uia(hwnd, max_depth=max_depth)
        else:
            tree = self._build_tree_win32(hwnd, max_depth=max_depth)

        elapsed = (time.perf_counter() - t0) * 1000
        if tree:
            logger.info(
                f"Window tree ({hex(hwnd)}): {tree.count_elements()} elements, "
                f"{elapsed:.1f}ms, depth={max_depth}"
            )
        return tree

    def take_snapshot(self, hwnd: int | None = None, max_depth: int = 8) -> UISnapshot:
        """
        采集完整UI快照——一次性获取所有需要的信息
        
        这是最常用的方法：一次调用获得窗口列表+元素树+交互元素+文字内容
        """
        snap = UISnapshot(timestamp=time.time())

        # 1. 窗口列表
        snap.all_windows = self.list_windows()
        snap.foreground_window = self.get_foreground_window_info()

        # 2. 元素树
        snap.element_tree = self.get_window_tree(hwnd, max_depth)
        if snap.element_tree:
            snap.total_elements = snap.element_tree.count_elements()
            snap.interactive_elements = snap.element_tree.get_interactive_children()
            snap.text_content = self._extract_all_text(snap.element_tree)
            snap.engine = "uia" if self._use_real_uia else "win32"

        snap.scan_duration_ms = (time.time() - snap.timestamp) * 1000
        return snap

    # ----------------------------------------------------------------
    # 真 UIA 树构建 (IUIAutomation)
    # ----------------------------------------------------------------

    def _build_tree_uia_root(self, max_depth: int = 4) -> Optional[UIElement]:
        """从桌面根元素构建UIA树"""
        try:
            raw_root = self._engine.get_root_element()
            if raw_root is None:
                return None
            return self._convert_uia_element(raw_root, depth=0, max_depth=max_depth)
        except Exception as e:
            logger.error(f"_build_tree_uia_root failed: {e}")
            return None

    def _build_tree_uia(self, hwnd: int, max_depth: int = 8) -> Optional[UIElement]:
        """从指定窗口句柄构建UIA树"""
        try:
            raw_root = self._engine.element_from_handle(hwnd)
            if raw_root is None:
                # 回退到Win32
                logger.warning(f"UIA: ElementFromHandle({hex(hwnd)}) returned null, falling back")
                return self._build_tree_win32(hwnd, max_depth)
            return self._convert_uia_element(raw_root, depth=0, max_depth=max_depth)
        except Exception as e:
            logger.error(f"_build_tree_uia({hex(hwnd)}) failed: {e}, falling back to Win32")
            return self._build_tree_win32(hwnd, max_depth)

    def _convert_uia_element(self, raw_elem, depth: int, max_depth: int = 8) -> UIElement:
        """
        将 IUIAutomationElement 转为我们的 UIElement 数据类
        
        这里是真UIA的核心——提取全部可用属性
        """
        # ---- 基础身份 ----
        ct_id = _extract_int_prop(raw_elem, UIA_PropertyIDs.ControlTypePropertyId.value, 0)
        name = _extract_string_prop(raw_elem, UIA_PropertyIDs.NamePropertyId.value)
        local_type = _extract_string_prop(raw_elem, UIA_PropertyIDs.LocalizedControlTypePropertyId.value)
        ctrl_type_name = _control_type_id_to_name(ct_id)

        # ---- 定位 ----
        rect = _extract_rect(raw_elem)
        cx = (rect[0] + rect[2]) // 2 if rect != (0, 0, 0, 0) else 0
        cy = (rect[1] + rect[3]) // 2 if rect != (0, 0, 0, 0) else 0
        hwnd = _extract_int_prop(raw_elem, UIA_PropertyIDs.NativeWindowHandlePropertyId.value)

        # ---- 进程与框架 ----
        pid = _extract_int_prop(raw_elem, UIA_PropertyIDs.ProcessIdPropertyId.value)
        class_name = _extract_string_prop(raw_elem, UIA_PropertyIDs.ClassNamePropertyId.value)
        automation_id = _extract_string_prop(raw_elem, UIA_PropertyIDs.AutomationIdPropertyId.value)
        fw_id = _extract_string_prop(raw_elem, UIA_PropertyIDs.FrameworkIdPropertyId.value)

        # ---- 状态 ----
        is_en = _extract_bool_prop(raw_elem, UIA_PropertyIDs.IsEnabledPropertyId.value, True)
        is_offscreen = _extract_bool_prop(raw_elem, UIA_PropertyIDs.IsOffscreenPropertyId.value, False)
        has_focus = _extract_bool_prop(raw_elem, UIA_PropertyIDs.HasKeyboardFocusPropertyId.value, False)
        is_pwd = _extract_bool_prop(raw_elem, UIA_PropertyIDs.IsPasswordPropertyId.value, False)
        is_content = _extract_bool_prop(raw_elem, UIA_PropertyIDs.IsContentElementPropertyId.value, True)
        is_ctrl = _extract_bool_prop(raw_elem, UIA_PropertyIDs.IsControlElementPropertyId.value, True)

        # ---- 值与内容 ----
        help_text = _extract_string_prop(raw_elem, UIA_PropertyIDs.HelpTextPropertyId.value)
        acc_key = _extract_string_prop(raw_elem, UIA_PropertyIDs.AcceleratorKeyPropertyId.value)
        access_key = _extract_string_prop(raw_elem, UIA_PropertyIDs.AccessKeyPropertyId.value)
        item_type = _extract_string_prop(raw_elem, UIA_PropertyIDs.ItemTypePropertyId.value)
        item_status = _extract_string_prop(raw_elem, UIA_PropertyIDs.ItemStatusPropertyId.value)

        # ---- 运行时ID ----
        rt_id_str = ""
        try:
            rt_id = raw_elem.GetCurrentPropertyValue(UIA_PropertyIDs.RuntimeIdPropertyId.value)
            if rt_id is not None:
                rt_id_str = str(list(rt_id)) if hasattr(rt_id, '__iter__') else str(rt_id)
        except Exception:
            pass

        # ---- 值（对输入框等）----
        value = ""
        if not is_pwd:  # 不提取密码字段的值
            # 尝试 ValuePattern 的 Value
            try:
                val_pat = _get_pattern(raw_elem, PatternID.ValuePatternId.value)
                if val_pat is not None:
                    value = val_pat.Value or ""
            except Exception:
                pass

            # 尝试 TextPattern 或直接取 Name
            if not value and ct_id in (
                ControlType.TEXT.value, ControlType.EDIT.value,
                ControlType.DOCUMENT.value, ControlType.CUSTOM.value
            ):
                value = name  # 文本元素的Name就是其内容

        # ---- 支持的控制模式 ----
        patterns = _detect_supported_patterns(raw_elem)

        # ---- 构建元素 ----
        elem = UIElement(
            name=name,
            control_type_id=ct_id,
            control_type=ctrl_type_name,
            localized_type=local_type,
            rect=rect,
            center=(cx, cy),
            native_handle=hwnd,
            process_id=pid,
            class_name=class_name,
            automation_id=automation_id,
            framework_id=fw_id,
            is_enabled=is_en,
            is_visible=(not is_offscreen),
            has_focus=has_focus,
            is_password=is_pwd,
            is_content_element=is_content,
            is_control_element=is_ctrl,
            value=value,
            help_text=help_text,
            accelerator_key=acc_key,
            access_key=access_key,
            item_type=item_type,
            item_status=item_status,
            depth=depth,
            runtime_id=rt_id_str,
            supported_patterns=patterns,
            _raw_ref=raw_elem,
        )

        # ---- 递归子元素 ----
        if depth < max_depth:
            try:
                raw_children = raw_elem.FindAll(
                    TreeScope.Children.value,
                    self._engine.create_true_condition() or True
                )
                if raw_children is not None:
                    for i in range(raw_children.Length):
                        try:
                            child_raw = raw_children.GetElement(i)
                            if child_raw:
                                child_elem = self._convert_uia_element(
                                    child_raw, depth=depth + 1, max_depth=max_depth
                                )
                                # 应用过滤规则
                                if self._should_include(child_elem):
                                    elem.children.append(child_elem)
                        except Exception as e:
                            logger.debug(f"Skip child[{i}] at depth={depth}: {e}")
                            continue
            except Exception as e:
                logger.debug(f"No children at depth={depth}: {e}")

        return elem

    def _should_include(self, elem: UIElement) -> bool:
        """判断元素是否应包含在结果中"""
        # 过滤不可见
        if self.filter_invisible and not elem.is_visible:
            return False
        # 过滤面积过小的装饰性元素
        if self.min_element_area > 0 and elem.area < self.min_element_area and not elem.name:
            return False
        return True

    # ----------------------------------------------------------------
    # Win32 降级树构建
    # ----------------------------------------------------------------

    def _build_tree_win32(self, root_hwnd: int, max_depth: int = 8) -> UIElement:
        """使用纯Win32 API构建简化版窗口树（备用）"""
        user32 = ctypes.windll.user32

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
            control_type_id=ControlType.WINDOW.value,
            automation_id="",
            class_name=class_buf.value,
            rect=(rect.left, rect.top, rect.right, rect.bottom),
            center=((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2),
            process_id=pid.value,
            handle=root_hwnd,
            is_enabled=True,
            is_visible=True,
            depth=0,
            framework_id="Win32",
        )

        if max_depth > 0:
            self._enum_child_windows(root_hwnd, root, max_depth - 1)

        return root

    def _enum_child_windows(self, parent_hwnd: int, parent_elem: UIElement, remaining_depth: int) -> None:
        """枚举子窗口（Win32降级）"""
        if remaining_depth <= 0:
            return

        user32 = ctypes.windll.user32
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
                control_type_id=0,
                automation_id="",
                class_name=class_name,
                rect=(rect.left, rect.top, rect.right, rect.bottom),
                center=((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2),
                process_id=0,
                handle=hwnd,
                is_enabled=True,
                is_visible=True,
                depth=parent_elem.depth + 1,
                framework_id="Win32",
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
            "ToolbarWindow32": "toolbar",
            "StatusBar": "statusbar",
            "msctls_statusbar32": "statusbar",
            "Tab": "tab",
            "SysTabControl32": "tab",
            "ProgressBar": "progress",
            "msctls_progress32": "progress",
            "Slider": "slider",
            "msctls_trackbar32": "slider",
            "CheckBox": "checkbox",
            "Button": "button",
            "RadioButton": "radio",
            "Link": "link",
            "ReBarWindow32": "rebar",
            "NativeWindowHost": "content_host",
        }
        for key, value in mapping.items():
            if key.lower() in class_name.lower():
                return value
        return "unknown"

    # ----------------------------------------------------------------
    # 窗口列表
    # ----------------------------------------------------------------

    def list_windows(self) -> list[WindowInfo]:
        """列出当前所有可见窗口（增强版：包含framework_id）"""
        windows = []
        seen_titles = set()

        WNDENUMPROC = ctypes.WINFUNCTYPE(BOOL, HWND, LPARAM)
        user32 = ctypes.windll.user32

        def enum_callback(hwnd, lp):
            nonlocal windows
            if not user32.IsWindowVisible(hwnd):
                return True

            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            title = buf.value.strip()
            if not title or len(title) < 3 or title in seen_titles:
                seen_titles.add(title)
                return True
            seen_titles.add(title)

            class_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buf, 256)
            class_name = class_buf.value

            rect = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))

            pid = DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            is_fg = (hwnd == user32.GetForegroundWindow())

            if user32.IsIconic(hwnd):
                state = "minimized"
            elif user32.IsZoomed(hwnd):
                state = "maximized"
            else:
                state = "normal"

            # 尝试从UIA获取framework_id
            fw_id = ""
            if self._use_real_uia and self._engine:
                try:
                    uia_elem = self._engine.element_from_handle(hwnd)
                    if uia_elem:
                        fw_id = _extract_string_prop(uia_elem, UIA_PropertyIDs.FrameworkIdPropertyId)
                except Exception:
                    pass

            windows.append(WindowInfo(
                title=title,
                class_name=class_name,
                hwnd=hwnd,
                pid=pid.value,
                rect=(rect.left, rect.top, rect.right, rect.bottom),
                is_foreground=is_fg,
                state=state,
                framework_id=fw_id,
            ))
            return True

        callback = WNDENUMPROC(enum_callback)
        user32.EnumWindows(callback, 0)

        windows.sort(key=lambda w: (not w.is_foreground, w.title))
        return windows

    def get_foreground_window_info(self) -> Optional[WindowInfo]:
        """获取当前前台窗口信息"""
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return None
        windows = self.list_windows()
        for w in windows:
            if w.hwnd == hwnd:
                return w
        return None

    # ----------------------------------------------------------------
    # 元素搜索
    # ----------------------------------------------------------------

    def find_element(
        self,
        query: str,
        *,
        hwnd: Optional[int] = None,
        search_type: str = "name",  # name / type / automation_id / value / all
        fuzzy: bool = True,
        only_interactive: bool = False,
    ) -> list[UIElement]:
        """在窗口中搜索元素"""
        tree = self.get_window_tree(hwnd)
        if not tree:
            return []

        results = []
        self._search_recursive(tree, query, search_type, fuzzy, results)

        if only_interactive:
            results = [r for r in results if r.is_interactive]

        return results

    def find_element_at(self, x: int, y: int) -> Optional[UIElement]:
        """获取屏幕坐标处的UI元素"""
        if self._use_real_uia and self._engine:
            try:
                raw = self._engine.element_from_point(x, y)
                if raw:
                    return self._convert_uia_element(raw, depth=0, max_depth=0)
            except Exception as e:
                logger.warning(f"element_from_point({x},{y}) failed: {e}")

        # Win32降级：返回坐标所在的窗口
        hwnd = ctypes.windll.user32.WindowFromPoint(ctypes.wintypes.POINT(x, y))
        if hwnd:
            return self.get_window_tree(hwnd)
        return None

    def get_focused_element(self) -> Optional[UIElement]:
        """获取当前焦点元素"""
        if self._use_real_uia and self._engine:
            try:
                raw = self._engine.get_focused_element()
                if raw:
                    return self._convert_uia_element(raw, depth=0, max_depth=0)
            except Exception as e:
                logger.warning("get_focused_element failed: {e}")
        return None

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
            case "value":
                target_value = element.value
            case "all":
                target_value = f"{element.name} {element.control_type} {element.automation_id} {element.value}"
            case _:
                target_value = f"{element.name} {element.control_type}"

        if fuzzy and query.lower() in target_value.lower():
            results.append(element)
        elif not fuzzy and query == target_value:
            results.append(element)

        for child in element.children:
            self._search_recursive(child, query, search_type, fuzzy, results)

    # ----------------------------------------------------------------
    # 控制模式执行
    # ----------------------------------------------------------------

    def click(self, element: UIElement) -> bool:
        """通过UIA InvokePattern 点击元素"""
        if not element._raw_ref:
            return False
        try:
            pat = _get_pattern(element._raw_ref, PatternID.InvokePatternId.value)
            if pat:
                pat.Invoke()
                return True
        except Exception as e:
            logger.warning(f"UIA Click failed on [{element.name}]: {e}")
        return False

    def set_value(self, element: UIElement, value: str) -> bool:
        """通过UIA ValuePattern 设置元素值"""
        if not element._raw_ref:
            return False
        try:
            pat = _get_pattern(element._raw_ref, PatternID.ValuePatternId.value)
            if pat:
                pat.SetValue(value)
                return True
        except Exception as e:
            logger.warning(f"UIA SetValue failed on [{element.name}]: {e}")
        return False

    def get_value(self, element: UIElement) -> str:
        """通过UIA ValuePattern 读取元素值"""
        if not element._raw_ref:
            return element.value
        try:
            pat = _get_pattern(element._raw_ref, PatternID.ValuePatternId.value)
            if pat:
                return pat.Value or ""
        except Exception:
            pass
        return element.value

    def toggle(self, element: UIElement) -> Optional[int]:
        """通过UIA TogglePattern 切换元素状态"""
        if not element._raw_ref:
            return None
        try:
            pat = _get_pattern(element._raw_ref, PatternID.TogglePatternId.value)
            if pat:
                pat.Toggle()
                return pat.CurrentToggleState
        except Exception as e:
            logger.warning(f"UIA Toggle failed on [{element.name}]: {e}")
        return None

    def select(self, element: UIElement) -> bool:
        """通过UIA SelectionItemPattern 选择元素（列表项/标签页）"""
        if not element._raw_ref:
            return False
        try:
            pat = _get_pattern(element._raw_ref, PatternID.SelectionItemPatternId.value)
            if pat:
                pat.Select()
                return True
        except Exception as e:
            logger.warning(f"UIA Select failed on [{element.name}]: {e}")
        return False

    def expand(self, element: UIElement) -> bool:
        """展开树节点或菜单"""
        if not element._raw_ref:
            return False
        try:
            pat = _get_pattern(element._raw_ref, PatternID.ExpandCollapsePatternId.value)
            if pat:
                pat.Expand()
                return True
        except Exception as e:
            logger.warning(f"UIA Expand failed: {e}")
        return False

    def collapse(self, element: UIElement) -> bool:
        """折叠树节点或菜单"""
        if not element._raw_ref:
            return False
        try:
            pat = _get_pattern(element._raw_ref, PatternID.ExpandCollapsePatternId.value)
            if pat:
                pat.Collapse()
                return True
        except Exception as e:
            logger.warning(f"UIA Collapse failed: {e}")
        return False

    # ----------------------------------------------------------------
    # 结构化文本输出（给LLM用）
    # ----------------------------------------------------------------

    def to_structured_text(self, tree: Optional[UIElement], compact: bool = True) -> str:
        """
        将UIA树转为结构化文本（可发给LLM分析）
        
        格式示例:
        
        [Window: Google Chrome] framework=Chrome pid=1234 (0,0,1920,1080)
          ├─ [MenuBar: 应用程序] @(945, 42) area=1920×78
          │   ├─ [Button: Chrome]
          │   ├─ [MenuItem: 文件(F)] acc_key=Alt+F
          │   └─ ...
          ├─ [ToolBar: 工具栏] @(960, 120) area=1920×48
          │   ├─ [Tab: GitHub - ...] focused ✓
          │   ├─ [Button: 新标签页]
          │   └─ [Edit: 地址栏] value="https://github.com/..."
          └─ [GroupControl: 内容区域] ...(960, 800)
              ├─ [Button: ⭐ Star]
              ├─ [Hyperlink: Code] @(...)
              └─ [Text: README.md]
        """
        if tree is None:
            return "(无UI元素)"

        lines = []
        self._tree_to_lines(tree, lines, prefix="", compact=compact)
        return "\n".join(lines)

    def _tree_to_lines(self, elem: UIElement, lines: list[str], prefix: str, compact: bool = True) -> None:
        """递归转文本行"""
        cx, cy = elem.center

        # 基础信息行
        line_parts = [
            f"{prefix}[{elem.control_type}: {elem.name}]",
        ]

        # 位置和尺寸
        w, h = elem.width, elem.height
        if not compact or w * h > 100:  # 大于10px²才显示位置
            line_parts.append(f"@({cx},{cy})")
        if h > 0 and w > 0:
            line_parts.append(f"{w}×{h}")

        # 关键属性
        attrs = []
        if elem.has_focus:
            attrs.append("★焦点")
        if elem.automation_id:
            attrs.append(f"id={elem.automation_id}")
        if elem.accelerator_key:
            attrs.append(f"key={elem.accelerator_key}")
        if elem.framework_id and elem.depth <= 1:
            attrs.append(f"fmt={elem.framework_id}")
        if elem.is_browser_element and elem.depth >= 3:
            attrs.append("🌐DOM")
        if elem.supported_patterns:
            # 只显示关键模式
            key_patterns = {"invoke", "value", "toggle", "selection_item", "text"}
            visible_pats = [p for p in elem.supported_patterns if p in key_patterns]
            if visible_pats:
                attrs.append(f"pat={','.join(visible_pats)}")

        if attrs:
            line_parts.append(" ".join(attrs))

        # 值（截断长文本）
        if elem.value:
            val_display = elem.value[:80] + ("..." if len(elem.value) > 80 else "")
            line_parts.append(f'= "{val_display}"')

        lines.append(" ".join(line_parts))

        # 子元素（限制显示数量避免过长）
        max_children = 200 if compact else 500
        displayed = elem.children[:max_children]

        for i, child in enumerate(displayed):
            is_last = (i == len(displayed) - 1)
            connector = "└─ " if is_last else "├─ "
            extension = "    " if is_last else "│   "
            self._tree_to_lines(child, lines, prefix + connector, compact=compact)

        if len(elem.children) > max_children:
            lines.append(f"{prefix}    ... (+{len(elem.children) - max_children} more)")

    def to_flat_list(self, tree: Optional[UIElement]) -> list[dict]:
        """将树扁平化为元素列表（适合表格展示）"""
        if not tree:
            return []

        items = []
        def flatten(e: UIElement):
            items.append(e.to_dict(flat=True))
            for c in e.children:
                flatten(c)
        flatten(tree)
        return items

    # ----------------------------------------------------------------
    # 文字提取（OCR替代/补充）
    # ----------------------------------------------------------------

    def _extract_all_text(self, tree: UIElement) -> str:
        """递归提取树中所有可读文字（比OCR更准确）"""
        texts = []
        self._collect_text(tree, texts)
        return "\n".join(texts)

    def _collect_text(self, elem: UIElement, texts: list[str]) -> None:
        """收集元素的可读文本"""
        # 有名字的元素通常有可读内容
        if elem.name and elem.control_type in (
            "text", "hyperlink", "list_item", "tree_item",
            "menu_item", "tab_item", "button", "titlebar",
        ):
            texts.append(elem.name)

        # 有值的元素
        if elem.value and elem.control_type in ("edit", "text"):
            texts.append(elem.value)

        for child in elem.children:
            self._collect_text(child, texts)

    # ----------------------------------------------------------------
    # 变化监控
    # ----------------------------------------------------------------

    def detect_window_changes(self) -> tuple[list[WindowInfo], list[WindowInfo]]:
        """检测窗口列表变化"""
        current = {w.hwnd: w for w in self.list_windows()}
        new_wins = [w for hwnd, w in current.items() if hwnd not in self._last_windows]
        gone_wins = [w for hwnd, w in self._last_windows.items() if hwnd not in current]
        self._last_windows = current
        return new_wins, gone_wins

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
                    all_wins = self.list_windows()
                    for cb in self._change_callbacks:
                        cb(all_wins)
            except Exception as e:
                logger.error(f"Monitor error: {e}")
            time.sleep(self._scan_interval_ms / 1000.0)

    # ----------------------------------------------------------------
    # 统计与诊断
    # ----------------------------------------------------------------

    def diagnose(self) -> dict:
        """诊断当前UIA环境状态"""
        info = {
            "engine": self.engine_status,
            "using_real_uia": self._use_real_uia,
            "comtypes_installed": HAS_COMTYPES,
        }

        if self._use_real_uia:
            try:
                root = self._engine.get_root_element()
                info["root_element"] = "OK" if root else "NULL"
                fg = self._engine.get_focused_element()
                info["focused_element"] = "OK" if fg else "NONE"
            except Exception as e:
                info["error"] = str(e)
        else:
            info["fallback_reason"] = "comtypes未安装" if not HAS_COMTYPES else "IUIAutomation初始化失败"

        # 测试前台窗口
        fg_win = self.get_foreground_window_info()
        if fg_win:
            info["foreground_window"] = {
                "title": fg_win.title,
                "class": fg_win.class_name,
                "framework": fg_win.framework_id,
                "hwnd": hex(fg_win.hwnd),
            }

            # 快速测试树构建
            tree = self.get_window_tree(fg_win.hwnd, max_depth=2)
            if tree:
                info["test_tree_elements"] = tree.count_elements()
                info["test_tree_engine"] = "uia" if self._use_real_uia else "win32"

        return info


# ================================================================
# 便捷函数
# ================================================================

def get_uia_scanner(scan_interval_ms: int = 500) -> UIAScanner:
    """获取全局UIA扫描器实例"""
    return UIAScanner(scan_interval_ms=scan_interval_ms)


def quick_scan() -> UISnapshot:
    """快速扫描前台窗口（一行搞定）"""
    scanner = UIAScanner()
    return scanner.take_snapshot()


def scan_desktop() -> UISnapshot:
    """快速扫描桌面全局"""
    scanner = UIAScanner()
    snap = UISnapshot(timestamp=time.time())
    snap.all_windows = scanner.list_windows()
    snap.foreground_window = scanner.get_foreground_window_info()
    snap.element_tree = scanner.get_desktop_tree(max_depth=3)
    if snap.element_tree:
        snap.total_elements = snap.element_tree.count_elements()
        snap.text_content = scanner._extract_all_text(snap.element_tree)
    snap.scan_duration_ms = (time.time() - snap.timestamp) * 1000
    snap.engine = "uia" if scanner._use_real_uia else "win32"
    return snap


# ================================================================
# CLI测试入口
# ================================================================

if __name__ == "__main__":
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    console = Console()
    console.print("\n[bold cyan]🔍 Desktop God Agent — UIA Scanner Diagnostic[/bold cyan]\n")

    scanner = UIAScanner()

    # 诊断
    diag = scanner.diagnose()
    console.print(Panel(
        f"[green]引擎: {diag['engine']}[/green]\n"
        f"真UIA: {'✅ 是' if diag['using_real_uia'] else '❌ 否'}\n"
        f"comtypes: {'✅ 已安装' if diag['comtypes_installed'] else '❌ 未安装'}",
        title="系统状态",
    ))

    # 前台窗口信息
    fg = scanner.get_foreground_window_info()
    if fg:
        console.print(Panel(
            f"[yellow]{fg.title}[/yellow]\n"
            f"类名: {fg.class_name}\n"
            f"句柄: {hex(fg.hwnd)}\n"
            f"进程: {fg.pid}\n"
            f"框架: {fg.framework_id or '(未知)'}\n"
            f"状态: {fg.state} | 区域: {fg.rect}",
            title=f"🖥 前台窗口",
        ))

    # 窗口列表
    windows = scanner.list_windows()
    table = Table(title=f"可见窗口 ({len(windows)} 个)")
    table.add_column("#", style="dim", width=4)
    table.add_column("标题", style="cyan")
    table.add_column("类名", style="green")
    table.add_column("框架", style="magenta")
    table.add_column("状态", style="yellow")
    table.add_column("前台", justify="center")

    for i, w in enumerate(windows[:20]):  # 最多显示20个
        table.add_row(
            str(i + 1),
            w.title[:50],
            w.class_name[:25],
            w.framework_id or "-",
            w.state,
            "✓" if w.is_foreground else "",
        )
    console.print(table)

    # 元素树
    console.print("\n[bold]🌳 前台窗口元素树 (前3层):[/bold]\n")
    if fg:
        tree = scanner.get_window_tree(fg.hwnd, max_depth=3)
        if tree:
            structured = scanner.to_structured_text(tree, compact=False)
            # 截断过长的输出
            lines = structured.split("\n")
            if len(lines) > 80:
                structured = "\n".join(lines[:80]) + f"\n... (共{len(lines)}行, {tree.count_elements()}个元素)"
            console.print(structured)
            
            # 交互元素统计
            interactive = tree.get_interactive_children()
            console.print(f"\n[dim]可交互元素: {len(interactive)}个[/dim]")
        else:
            console.print("[red]❌ 无法构建元素树[/red]")
    else:
        console.print("[yellow]⚠️ 无前台窗口[/yellow]")

    console.print(f"\n[bold green]✅ 扫描完成[/bold green]")
