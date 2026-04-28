"""
高速屏幕截图模块 - 100ms级截图能力

使用 mss 库实现跨显示器的高性能截图，
支持区域裁剪、格式转换、增量比较。
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Optional, Callable
import logging
from PIL import Image
import io

logger = logging.getLogger(__name__)

# ---- 延迟导入 mss ----
try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False
    logger.warning("mss not installed, screen capture unavailable")


@dataclass
class ScreenshotResult:
    """截图结果"""
    image: Image.Image              # PIL Image对象
    width: int
    height: int
    timestamp: float                # time.time()
    bytes_size: int                 # PNG字节大小
    region: Optional[tuple] = None  # 截图区域 (left, top, right, bottom)


@dataclass
class ScreenChange:
    """屏幕变化检测结果"""
    changed: bool                   # 是否有变化
    change_ratio: float             # 变化比例 (0.0 ~ 1.0)
    diff_image: Optional[Image.Image] = None
    hotspots: list[tuple[int, int]] = field(default_factory=list)  # 变化热点坐标


class ScreenshotCapture:
    """
    高速屏幕截图器
    
    特性：
    - 使用 mss 实现 100ms 级截图
    - 支持全屏 / 区域 / 多显示器
    - 增量检测（像素级别diff）
    - 线程安全，可后台持续监控
    """

    def __init__(
        self,
        monitor: int | str | dict = 1,  # 1=主显示器, "all"=全部, dict=自定义区域
        interval_ms: int = 100,
    ):
        if not HAS_MSS:
            raise RuntimeError("mss library required: pip install mss")

        self._sct = mss.mss()
        self._monitor = monitor
        self._interval_ms = interval_ms
        self._lock = threading.Lock()
        self._last_frame: Optional[bytes] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callbacks: list[Callable[[ScreenshotResult], None]] = []

        logger.info(f"ScreenshotCapture init | monitor={monitor} interval={interval_ms}ms")

    @property
    def screen_size(self) -> tuple[int, int]:
        """获取当前监视器分辨率"""
        mon = self._get_monitor_info()
        return mon["width"], mon["height"]

    def _get_monitor_info(self) -> dict:
        """获取监视器信息"""
        if isinstance(self._monitor, dict):
            return self._monitor
        elif isinstance(self._monitor, int):
            monitors = self._sct.monitors
            if self._monitor < len(monitors):
                return monitors[self._monitor]
            return monitors[1]
        else:
            return self._sct.monitors[1]

    def capture(self, region: Optional[tuple] = None) -> ScreenshotResult:
        """
        截取一帧画面
        
        Args:
            region: 可选的区域 (left, top, width, height)，None则截全屏
            
        Returns:
            ScreenshotResult 包含PIL图像和元数据
        """
        start = time.perf_counter()

        with self._lock:
            try:
                if region:
                    screenshot = self._sct.grab({
                        "left": region[0],
                        "top": region[1],
                        "width": region[2],
                        "height": region[3],
                    })
                else:
                    mon_info = self._get_monitor_info()
                    screenshot = self._sct.grab(mon_info)

                # 转为PIL Image
                img = Image.frombytes(
                    "RGB",
                    screenshot.size,
                    screenshot.bgra,  # BGRA
                    "raw", "BGRX",
                )

                # 保存原始bytes用于增量对比
                png_bytes = io.BytesIO()
                img.save(png_bytes, format="PNG")
                raw_bytes = png_bytes.getvalue()

                result = ScreenshotResult(
                    image=img,
                    width=img.width,
                    height=img.height,
                    timestamp=time.time(),
                    bytes_size=len(raw_bytes),
                    region=region,
                )
                
                latency = (time.perf_counter() - start) * 1000
                logger.debug(f"Screenshot captured | {img.width}x{img.height} "
                            f"| {latency:.1f}ms | {len(raw_bytes)//1024}KB")
                return result

            except Exception as e:
                logger.error(f"Screenshot failed: {e}")
                raise

    def detect_change(self, threshold: float = 0.01) -> ScreenChange:
        """
        检测屏幕是否有显著变化
        
        Args:
            threshold: 变化阈值，0.01表示1%像素变化即视为有变化
            
        Returns:
            ScreenChange 变化检测结果
        """
        current = self.capture()

        if self._last_frame is None:
            self._last_frame = current.image.tobytes()
            return ScreenChange(changed=False, change_ratio=0.0)

        current_bytes = current.image.tobytes()

        # 像素级比较（采样优化：每隔16个像素比较一次）
        sample_rate = 4  # 每4个通道(1像素RGB)采一个
        total_samples = len(current_bytes) // sample_rate
        diffs = sum(
            1 for i in range(0, len(current_bytes), sample_rate)
            if i < len(self._last_frame) and current_bytes[i] != self._last_frame[i]
        )
        
        ratio = diffs / max(total_samples, 1)
        changed = ratio > threshold

        self._last_frame = current_bytes

        return ScreenChange(
            changed=changed,
            change_ratio=ratio,
        )

    def to_bytes(self, img: Optional[Image.Image] = None, format: str = "PNG") -> bytes:
        """将图片转为字节流（用于发给Gemini等模型）"""
        target = img or self.capture().image
        buf = io.BytesIO()
        target.save(buf, format=format)
        return buf.getvalue()

    def add_callback(self, callback: Callable[[ScreenshotResult], None]) -> None:
        """注册截图回调（用于持续监控模式）"""
        self._callbacks.append(callback)

    def _monitor_loop(self) -> None:
        """后台监控循环"""
        logger.info(f"Screen monitoring started | interval={self._interval_ms}ms")
        while self._running:
            try:
                frame = self.capture()
                for cb in self._callbacks:
                    cb(frame)
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")

            time.sleep(self._interval_ms / 1000.0)

    def start_monitoring(self) -> None:
        """开始后台持续监控"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("Screen monitoring started")

    def stop_monitoring(self) -> None:
        """停止后台监控"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("Screen monitoring stopped")

    def close(self) -> None:
        """释放资源"""
        self.stop_monitoring()
        self._sct.close()


# 全局单例
_capture_instance: Optional[ScreenshotCapture] = None


def get_screencap() -> ScreenshotCapture:
    """获取全局截图器实例"""
    global _capture_instance
    if _capture_instance is None:
        _capture_instance = ScreenshotCapture()
    return _capture_instance
