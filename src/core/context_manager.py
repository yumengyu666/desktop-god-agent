"""
上下文采集器 — 为AI决策提供完整的环境信息

整合三大感知通道：
1. 📸 屏幕截图 (mss) → 视觉像素数据
2. 🌳 UIA元素树 (IUIAutomation) → 结构化控件信息
3. 🔤 OCR文字识别 (PaddleOCR) → 屏幕上的文字内容

输出: ExecutionContext — 统一的结构化上下文，可直接注入LLM prompt
"""

import time
import threading
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum, IntEnum
import logging

logger = logging.getLogger(__name__)


class CollectionLevel(IntEnum):
    """采集深度级别——按需选择，平衡速度和信息量"""
    
    # ---- L1-L3 基础层（纯本地，<200ms） ----
    L1_DESKTOP = 1      # 仅桌面信息（窗口列表+进程概览）
    L2_UIA_TEXT = 2     # 结构化UIA文本 + 窗口列表（推荐默认）
    L3_FULL_TREE = 3    # 完整UIA树 + 文字提取
    
    # ---- L4-L6 高级层（可能涉及模型调用） ----
    L4_BROWSER_CDP = 4  # 浏览器CDP协议（DOM/Console/Network）
    L5_VISION_FIND = 5  # Gemini视觉定位元素
    L6_VISION_FULL = 6  # Gemini全屏理解


@dataclass
class ScreenInfo:
    """屏幕基础信息"""
    width: int = 0
    height: int = 0
    dpi_scale: float = 1.0
    primary_monitor_rect: tuple[int, int, int, int] = (0, 0, 0, 0)


@dataclass
class WindowContext:
    """前台窗口上下文"""
    title: str = ""
    class_name: str = ""
    hwnd: int = 0
    pid: int = 0
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)
    framework_id: str = ""       # Win32 / WPF / Electron / Chrome
    state: str = "normal"        # normal/minimized/maximized
    is_browser: bool = False     # 是否浏览器
    browser_url: str = ""        # 浏览器当前URL(如可获取)


@dataclass
class UIAContext:
    """UIA元素树上下文"""
    total_elements: int = 0
    interactive_count: int = 0
    structured_text: str = ""         # 给LLM看的结构化文本
    text_content: str = ""            # 提取的所有文字
    element_summary: str = ""         # 一句话摘要
    engine_used: str = "win32"        # uia or win32
    scan_duration_ms: float = 0.0


@dataclass
class ScreenshotContext:
    """截图上下文"""
    image_path: Optional[str] None = None
    image_size_bytes: int = 0
    capture_duration_ms: float = 0.0
    has_image: bool = False


@dataclass
class OCRContext:
    """OCR识别上下文"""
    raw_text: str = ""               # OCR原始结果
    confidence: float = 0.0          # 平均置信度
    word_count: int = 0              # 识别到的文字数
    duration_ms: float = 0.0
    merged_with_uia: bool = False    # 是否与UIA文字合并


@dataclass
class ProcessContext:
    """关键进程信息"""
    cpu_usage: float = 0.0
    memory_usage_mb: float = 0.0
    top_processes: list[dict] = field(default_factory=list)   # [{name, pid, mem_pct}]
    network_active: bool = False


@dataclass
class DeltaChanges:
    """自上次采集以来的变化"""
    window_opened: list[str] = field(default_factory=list)
    window_closed: list[str] = field(default_factory=list)
    focus_changed: bool = False
    ui_elements_changed: bool = False
    screen_content_changed: bool = False


@dataclass
class ExecutionContext:
    """
    完整执行上下文 —— AI决策的全部环境信息
    
    这是感知系统的核心产出，直接喂给：
    - CommanderAgent（指令分析）
    - PlannerAgent（任务规划）
    - 模型网关的chat()调用
    """
    # 元信息
    timestamp: float = 0.0
    collection_level: CollectionLevel = CollectionLevel.L2_UIA_TEXT
    total_collection_ms: float = 0.0
    
    # 屏幕
    screen: ScreenInfo = field(default_factory=ScreenInfo)
    
    # 前台窗口
    foreground_window: WindowContext = field(default_factory=WindowContext)
    
    # 所有可见窗口
    all_windows: list[dict] = field(default_factory=list)   # [title, class, hwnd, state]
    
    # UIA元素树
    uia: UIAContext = field(default_factory=UIAContext)
    
    # 截图
    screenshot: ScreenshotContext = field(default_factory=ScreenshotContext)
    
    # OCR
    ocr: OCRContext = field(default_factory=OCRContext)
    
    # 进程
    process: ProcessContext = field(default_factory=ProcessContext)
    
    # 变化检测
    delta: DeltaChanges = field(default_factory=DeltaChanges)

    def to_prompt_text(self, max_chars: int = 4000) -> str:
        """
        转为适合注入LLM prompt的文本
        
        格式经过优化：信息密度高、token效率好、结构清晰
        """
        parts = []
        
        # 1. 时间与窗口
        parts.append(f"## 当前状态 ({time.strftime('%H:%M:%S')})")
        
        if self.foreground_window.title:
            fw = self.foreground_window
            parts.append(
                f"**前台窗口**: {fw.title} | "
                f"类型:{fw.class_name} | "
                f"框架:{fw.framework_id or '未知'} | "
                f"状态:{fw.state}"
            )
            if fw.is_browser and fw.browser_url:
                parts.append(f"**URL**: {fw.browser_url}")
        
        if len(self.all_windows) > 1:
            win_names = [w.get('title', '?') for w in self.all_windows[:8]]
            parts.append(f"**打开的窗口**: {', '.join(win_names)}")

        # 2. UI元素结构（最关键的信息）
        if self.uia.structured_text:
            # 截断到合理长度
            uia_text = self.uia.structured_text
            if len(uia_text) > max_chars * 0.7:
                lines = uia_text.split('\n')
                uia_text = '\n'.join(lines[:60]) + \
                    f"\n... (共{self.uia.total_elements}个元素)"
            
            parts.append(f"\n## UI元素结构 ({self.uia.engine_used}引擎)")
            parts.append("```\n" + uia_text + "\n```")

        # 3. 可交互元素摘要
        if self.uia.interactive_count > 0:
            parts.append(
                f"\n**可交互元素**: {self.uia.interactive_count}个 | "
                f"总元素: {self.uia.total_elements}"
            )

        # 4. 屏幕文字（UIA提取 + OCR合并）
        text_parts = []
        if self.uia.text_content:
            text_parts.append(self.uia.text_content[:500])
        if self.ocr.raw_text:
            ocr_part = self.ocr.raw_text[:500]
            if ocr_part not in (text_parts or ['']):
                text_parts.append(f"[OCR] {ocr_part}")
        
        if text_parts:
            combined = '\n'.join(text_parts)
            if len(combined) > max_chars * 0.25:
                combined = combined[:int(max_chars * 0.25)] + "..."
            parts.append(f"\n## 屏幕文字\n{combined}")

        # 5. 变化提示
        changes = []
        if self.delta.window_opened:
            changes.append(f"新窗口: {', '.join(self.delta.window_opened)}")
        if self.delta.window_closed:
            changes.append(f"关闭窗口: {', '.join(self.delta.window_closed)}")
        if self.delta.focus_changed:
            changes.append("焦点切换")
        if changes:
            parts.append(f"\n## 最近变化\n{'; '.join(changes)}")

        result = '\n'.join(parts)
        
        # 最终截断
        if len(result) > max_chars:
            result = result[:max_chars-50] + "\n...(上下文已截断)"
        
        return result

    def to_dict(self) -> dict:
        return asdict(self)


class ContextCollector:
    """
    上下文采集器 — 协调所有感知子系统，统一输出ExecutionContext
    
    设计原则：
    - 按需采集：不同任务需要不同的信息深度
    - 并行化：截图、UIA、OCR尽可能并行执行
    - 缓存策略：短时间内的重复请求返回缓存
    - 降级容错：任何子模块失败不影响整体流程
    """

    # 单例
    _instance: Optional['ContextCollector'] = None
    _lock = threading.Lock()

    CACHE_TTL_SECONDS = 3.0   # 3秒缓存

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # 子系统引用（延迟初始化）
        self._uia_scanner = None
        self._screencap = None
        self._ocr_engine = None
        self._world_model = None
        
        # 缓存
        self._cache: Optional[ExecutionContext] = None
        self._cache_time: float = 0.0
        
        # 上一次的状态（用于变化检测）
        self._last_window_titles: set[str] = set()
        self._last_fg_hwnd: int = 0
        
        # 配置
        self.default_level = CollectionLevel.L2_UIA_TEXT
        self.enable_ocr = True           # 是否启用OCR
        self.enable_screenshot = True    # 是否启用截图
        self.merge_ocr_with_uia = True   # 合并OCR和UIA文字
        
        self._initialized = True
        logger.info("ContextCollector initialized")

    # ----------------------------------------------------------------
    # 子系统获取（延迟加载）
    # ----------------------------------------------------------------

    def _get_uia_scanner(self):
        from src.perception.uia_scanner import get_uia_scanner
        if self._uia_scanner is None:
            self._uia_scanner = get_uia_scanner()
        return self._uia_scanner

    def _get_screencap(self):
        from src.perception.screenshot import get_screencap
        if self._screencap is None:
            self._screencap = get_screencap()
        return self._screencap

    def _get_ocr_engine(self):
        try:
            from src.perception.ocr_engine import get_ocr_engine
            if self._ocr_engine is None:
                self._ocr_engine = get_ocr_engine()
            return self._ocr_engine
        except Exception as e:
            logger.warning(f"OCR engine unavailable: {e}")
            return None

    def _get_world_model(self):
        try:
            from src.world_model.world_model import WorldModel
            if self._world_model is None:
                self._world_model = WorldModel()
            return self._world_model
        except Exception as e:
            logger.warning(f"WorldModel unavailable: {e}")
            return None

    # ----------------------------------------------------------------
    # 核心采集接口
    # ----------------------------------------------------------------

    def collect(
        self,
        level: CollectionLevel | int | None = None,
        *,
        use_cache: bool = True,
        hwnd: Optional[int] = None,
    ) -> ExecutionContext:
        """
        执行完整上下文采集
        
        Args:
            level: 采集深度级别
            use_cache: 是否使用短时缓存
            hwnd: 指定窗口句柄（None=前台窗口）
            
        Returns:
            完整的ExecutionContext
        """
        t0 = time.perf_counter()

        # 缓存检查
        if use_cache and self._cache:
            age = time.time() - self._cache_time
            if age < self.CACHE_TTL_SECONDS:
                logger.debug(f"Context cache hit (age={age:.1f}s)")
                return self._cache

        level = CollectionLevel(level or self.default_level)
        ctx = ExecutionContext(timestamp=time.time(), collection_level=level)

        # ---- 并行采集各路信息 ----
        ctx.screen = self._collect_screen_info()
        ctx.foreground_window, ctx.all_windows = self._collect_window_info(hwnd)
        ctx.uia = self._collect_uia(level, ctx.foreground_window.hwnd)
        
        if self.enable_screenshot and level.value >= CollectionLevel.L2_UIA_TEXT.value:
            ctx.screenshot = self._collect_screenshot()
        
        if self.enable_ocr and level.value >= CollectionLevel.L2_UIA_TEXT.value:
            ctx.ocr = self._collect_ocr(ctx.screenshot)
        
        if level.value >= CollectionLevel.L3_FULL_TREE.value:
            ctx.process = self._collect_process_info()

        # ---- 变化检测 ----
        ctx.delta = self._detect_changes(ctx)

        # ---- 更新缓存 ----
        self._cache = ctx
        self._cache_time = time.time()

        ctx.total_collection_ms = (time.perf_counter() - t0) * 1000
        
        logger.info(
            f"Context collected | level=L{level.value} | "
            f"{ctx.uia.total_elements} elements | "
            f"{ctx.uia.interactive_count} interactive | "
            f"{ctx.total_collection_ms:.0f}ms"
        )

        return ctx

    def collect_quick(self) -> ExecutionContext:
        """快速采集（L2级别，适合大多数决策场景）"""
        return self.collect(CollectionLevel.L2_UIA_TEXT)

    def collect_minimal(self) -> ExecutionContext:
        """最小采集（L1级别，仅窗口信息）"""
        return self.collect(CollectionLevel.L1_DESKTOP)

    # ----------------------------------------------------------------
    # 各路采集实现
    # ----------------------------------------------------------------

    def _collect_screen_info(self) -> ScreenInfo:
        """收集屏幕基础信息"""
        import ctypes
        user32 = ctypes.windll.user32
        
        width = user32.GetSystemMetrics(0)   # SM_CXSCREEN
        height = user32.GetSystemMetrics(1)  # SM_CYSCREEN
        
        # DPI缩放（Windows 10+）
        dpi_scale = 1.0
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            dpi = ctypes.windll.shcore.GetDpiForMonitor
            # DPI/96 = scale factor
        except Exception:
            pass
        
        return ScreenInfo(
            width=width,
            height=height,
            dpi_scale=dpi_scale,
            primary_monitor_rect=(0, 0, width, height),
        )

    def _collect_window_info(self, target_hwnd=None) -> tuple[WindowContext, list[dict]]:
        """收集窗口信息"""
        scanner = self._get_uia_scanner()
        
        fg_win = scanner.get_foreground_window_info()
        if target_hwnd and fg_win:
            # 覆盖为目标窗口
            for w in scanner.list_windows():
                if w.hwnd == target_hwnd:
                    fg_win = w
                    break
        
        fw_ctx = WindowContext()
        if fg_win:
            fw_ctx = WindowContext(
                title=fg_win.title,
                class_name=fg_win.class_name,
                hwnd=fg_win.hwnd,
                pid=fg_win.pid,
                rect=fg_win.rect,
                framework_id=fg_win.framework_id,
                state=fg_win.state,
                is_browser=fg_win.framework_id in ("Chrome", "Edge", "MozillaFirefox", "Webkit"),
            )

        all_wins = []
        for w in scanner.list_windows():
            all_wins.append({
                "title": w.title,
                "class": w.class_name,
                "hwnd": w.hwnd,
                "state": w.state,
                "framework": w.framework_id,
                "is_foreground": w.is_foreground,
            })

        return fw_ctx, all_wins

    def _collect_uia(self, level: CollectionLevel, hwnd: int) -> UIAContext:
        """采集UIA元素树"""
        ctx = UIAContext()
        scanner = self._get_uia_scanner()
        
        try:
            if level.value <= CollectionLevel.L1_DESKTOP.value:
                # L1: 不采UIA
                return ctx
            
            max_depth = min(level.value, 8)  # 最多8层
            
            snap = scanner.take_snapshot(hwnd=hwnd, max_depth=max_depth)
            
            ctx.total_elements = snap.total_elements
            ctx.interactive_count = len(snap.interactive_elements)
            ctx.engine_used = snap.engine
            ctx.scan_duration_ms = snap.scan_duration_ms
            
            if snap.element_tree:
                # 结构化文本（给LLM看）
                ctx.structured_text = scanner.to_structured_text(snap.element_tree)
                
                # 提取的文字
                ctx.text_content = snap.text_content
                
                # 一句话摘要
                fw = snap.foreground_window
                if fw:
                    ctx.element_summary = (
                        f"{fw.title} ({fw.framework_id or 'Win32'}) "
                        f"— {snap.total_elements}个元素, "
                        f"{len(snap.interactive_elements)}个可交互"
                    )
                    
        except Exception as e:
            logger.error(f"UIA collection failed: {e}")
            ctx.structured_text = "(UIA采集失败)"
            ctx.engine_used = "error"

        return ctx

    def _collect_screenshot(self) -> ScreenshotContext:
        ctx = ScreenshotContext()
        try:
            screencap = self._get_screencap()
            img = screencap.capture()
            
            if img:
                # 保存临时文件
                import os
                tmp_dir = os.path.join(os.getcwd(), ".temp", "screenshots")
                os.makedirs(tmp_dir, exist_ok=True)
                
                timestamp = time.strftime("%H%M%S")
                path = os.path.join(tmp_dir, f"context_{timestamp}.png")
                img.save(path)
                
                ctx.image_path = path
                ctx.image_size_bytes = os.path.getsize(path) if os.path.exists(path) else 0
                ctx.has_image = True
                
        except Exception as e:
            logger.warning(f"Screenshot failed: {e}")
        
        return ctx

    def _collect_ocr(self, screenshot_ctx: ScreenshotContext) -> OCRContext:
        ctx = OCRContext()
        
        if not screenshot_ctx.has_image:
            return ctx
        
        ocr = self._get_ocr_engine()
        if ocr is None:
            return ctx
        
        try:
            t0 = time.perf_counter()
            result = ocr.recognize(screenshot_ctx.image_path)
            
            if result:
                ctx.raw_text = result.get('text', '')
                ctx.confidence = result.get('confidence', 0.0)
                ctx.word_count = len(ctx.raw_text.split()) if ctx.raw_text else 0
                ctx.duration_ms = (time.perf_counter() - t0) * 1000
                
        except Exception as e:
            logger.warning(f"OCR failed: {e}")
        
        return ctx

    def _collect_process_info(self) -> ProcessContext:
        ctx = ProcessContext()
        try:
            import psutil
            
            ctx.cpu_usage = psutil.cpu_percent(interval=0.1)
            ctx.memory_usage_mb = psutil.virtual_memory().used / (1024 * 1024)
            
            # Top CPU进程
            procs = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
                try:
                    info = proc.info
                    if info.get('cpu_percent', 0) > 0.1:
                        procs.append({
                            'name': info.get('name', '?'),
                            'pid': info.get('pid', 0),
                            'cpu': info.get('cpu_percent', 0),
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            procs.sort(key=lambda x: x.get('cpu', 0), reverse=True)
            ctx.top_processes = procs[:8]
            ctx.network_active = len(psutil.net_connections()) > 10
            
        except Exception as e:
            logger.debug(f"Process info failed: {e}")
        
        return ctx

    # ----------------------------------------------------------------
    # 变化检测
    # ----------------------------------------------------------------

    def _detect_changes(self, ctx: ExecutionContext) -> DeltaChanges:
        delta = DeltaChanges()
        
        current_titles = {w.get('title') for w in ctx.all_windows}
        
        # 新开的窗口
        delta.window_opened = list(current_titles - self._last_window_titles)
        
        # 关闭的窗口
        delta.window_closed = list(self._last_window_titles - current_titles)
        
        # 焦点变化
        if ctx.foreground_window.hwnd != self._last_fg_hwnd:
            if self._last_fg_hwnd != 0:  # 非首次
                delta.focus_changed = True
        
        # 保存当前状态供下次比较
        self._last_window_titles = current_titles
        self._last_fg_hwnd = ctx.foreground_window.hwnd
        
        return delta

    # ----------------------------------------------------------------
    # 清理
    # ----------------------------------------------------------------

    def invalidate_cache(self):
        """清除缓存，强制下次重新采集"""
        self._cache = None
        self._cache_time = 0

    def set_target_window(self, hwnd: int):
        """设置后续采集的目标窗口"""
        self._target_hwnd = hwnd
        self.invalidate_cache()


# ================================================================
# 便捷函数
# ================================================================

def get_context_collector() -> ContextCollector:
    """获取全局上下文采集器实例"""
    return ContextCollector()


def quick_context() -> ExecutionContext:
    """一行代码获取上下文（L2级别）"""
    collector = get_context_collector()
    return collector.collect_quick()


def context_for_llm(max_chars: int = 4000) -> str:
    """获取给LLM用的格式化上下文文本"""
    collector = get_context_collector()
    ctx = collector.collect_quick()
    return ctx.to_prompt_text(max_chars)


# ============================================================
# CLI测试入口
# ============================================================

if __name__ == "__main__":
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    console.print("\n[bold cyan]🔍 Desktop God Agent — Context Collector Test[/bold cyan]\n")

    collector = ContextCollector()

    # 测试各级别
    for level in [CollectionLevel.L1_DESKTOP, CollectionLevel.L2_UIA_TEXT]:
        console.print(f"[yellow]Testing Level L{level.value}: {level.name}[/yellow]")
        ctx = collector.collect(level, use_cache=False)

        table = Table(title=f"L{level.value} Result ({ctx.total_collection_ms:.0f}ms)")
        table.add_column("项目", style="cyan")
        table.add_column("值", style="green")

        table.add_row("屏幕", f"{ctx.screen.width}×{ctx.screen.height}")
        table.add_row("前台窗口", ctx.foreground_window.title or "(无)")
        table.add_row("框架", ctx.foreground_window.framework_id or "(未知)")
        table.add_row("可见窗口数", str(len(ctx.all_windows)))
        table.add_row("UIA元素数", str(ctx.uia.total_elements))
        table.add_row("可交互元素", str(ctx.uia.interactive_count))
        table.add_row("UIA引擎", ctx.uia.engine_used)
        table.add_row("文字长度", f"{len(ctx.uia.text_content)} chars")
        table.add_row("截图", "✅" if ctx.screenshot.has_image else "❌")
        table.add_row("OCR字数", str(ctx.ocr.word_count))

        console.print(table)

        if ctx.delta.window_opened or ctx.delta.window_closed:
            console.print(f"[dim]变化: +{len(ctx.delta.window_opened)} -{len(ctx.delta.window_closed)}[/dim]")

    # 测试LLM prompt格式
    console.print("\n[bold]📝 LLM Prompt Preview:[/bold]\n")
    prompt_text = context_for_llm(max_chars=3000)
    console.print(Panel(prompt_text[:2000], title="to_prompt_text() 输出"))

    console.print(f"\n[green]✅ 全部测试完成[/green]")
