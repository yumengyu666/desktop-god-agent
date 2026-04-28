"""
OCR 引擎 - 屏幕文字识别

支持多种后端：
  PaddleOCR (默认): 中文+英文混合识别效果好
  Tesseract: 备选方案
  Google Gemini: 高精度视觉理解（带位置信息）

输出格式统一：包含文字、置信度、边界框坐标
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional
from PIL import Image
import io

logger = logging.getLogger(__name__)

try:
    from paddleocr import PaddleOCR
    HAS_PADDLE_OCR = True
except ImportError:
    HAS_PADDLE_OCR = False
    logger.warning("PaddleOCR not installed")


@dataclass
class OCREntry:
    """单条OCR识别结果"""
    text: str                       # 识别出的文字
    confidence: float               # 置信度 0.0~1.0
    bbox: tuple[int, int, int, int]  # (left, top, right, bottom)
    
    @property
    def center(self) -> tuple[int, int]:
        l, t, r, b = self.bbox
        return ((l + r) // 2, (t + b) // 2)
    
    @property 
    def area(self) -> int:
        l, t, r, b = self.bbox
        return max(0, (r - l) * (b - t))


@dataclass
class OCRResult:
    """完整OCR结果"""
    entries: list[OCREntry]
    full_text: str                  # 所有文字拼接
    image_size: tuple[int, int]     # 原图尺寸
    elapsed_ms: float
    
    @property
    def text_count(self) -> int:
        return len(self.entries)
    
    def filter_by_confidence(self, threshold: float = 0.7) -> 'OCRResult':
        """过滤低置信度结果"""
        filtered = [e for e in self.entries if e.confidence >= threshold]
        return OCRResult(
            entries=filtered,
            full_text="\n".join(e.text for e in filtered),
            image_size=self.image_size,
            elapsed_ms=self.elapsed_ms,
        )
    
    def find_text(self, keyword: str, case_sensitive: bool = False) -> list[OCREntry]:
        """按关键词搜索"""
        results = []
        kw = keyword if case_sensitive else keyword.lower()
        for entry in self.entries:
            text = entry.text if case_sensitive else entry.text.lower()
            if kw in text:
                results.append(entry)
        return results
    
    def get_region_text(
        self,
        region: tuple[int, int, int, int],
    ) -> str:
        """提取指定区域的文字"""
        rl, rt, rr, rb = region
        texts = []
        for entry in self.entries:
            el, et, er, eb = entry.bbox
            # 判断是否有重叠
            if el < rr and er > rl and et < rb and eb > rt:
                texts.append(entry.text)
        return " ".join(texts)


class OCREngine:
    """
    统一OCR引擎
    
    自动选择最佳后端，提供一致的API
    """
    
    def __init__(self, engine: str = "paddleocr"):
        self._engine_name = engine
        self._ocr_instance: Optional[Any] = None
        self._initialized = False
        
        if engine == "paddleocr":
            self._init_paddle()
        else:
            logger.warning(f"Unknown engine '{engine}', defaulting to paddleocr")
            self._init_paddle()

    def _init_paddle(self) -> None:
        """初始化PaddleOCR"""
        if not HAS_PADDLE_OCR:
            raise RuntimeError("PaddleOCR required: pip install paddleocr paddlepaddle")
        
        try:
            self._ocr_instance = PaddleOCR(
                use_angle_cls=True,
                lang='ch',           # 中英文混合
                show_log=False,
                use_gpu=False,       # 默认CPU模式
                det_db_thresh=0.3,   # 降低阈值提高召回
            )
            self._initialized = True
            logger.info("PaddleOCR initialized successfully")
        except Exception as e:
            logger.error(f"PaddleOCR init failed: {e}")
            self._initialized = False

    def recognize(self, image: Image.Image, region: Optional[tuple] = None) -> OCRResult:
        """
        对图片执行OCR识别
        
        Args:
            image: PIL Image对象
            region: 可选的区域裁剪 (left, top, width, height)
            
        Returns:
            OCRResult 完整识别结果
        """
        start = time.perf_counter()
        
        if region:
            image = image.crop(region)
        
        if not self._initialized:
            return OCRResult(
                entries=[],
                full_text="(OCR未初始化)",
                image_size=image.size,
                elapsed_ms=(time.perf_counter() - start) * 1000,
            )
        
        try:
            # PaddleOCR需要numpy数组或文件路径
            img_array = self._pil_to_numpy(image)
            result = self._ocr_instance.ocr(img_array, cls=True)
            
            entries = []
            full_texts = []
            
            if result and result[0]:
                for line in result[0]:
                    bbox_coords = line[0]     # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                    text, conf = line[1]
                    
                    # 计算边界框
                    xs = [p[0] for p in bbox_coords]
                    ys = [p[1] for p in bbox_coords]
                    bbox = (
                        int(min(xs)), int(min(ys)),
                        int(max(xs)), int(max(ys)),
                    )
                    
                    entries.append(OCREntry(
                        text=text,
                        confidence=float(conf),
                        bbox=bbox,
                    ))
                    full_texts.append(text)
            
            elapsed = (time.perf_counter() - start) * 1000
            logger.debug(f"OCR done | {len(entries)} texts | {elapsed:.0f}ms")
            
            return OCRResult(
                entries=entries,
                full_text="\n".join(full_texts),
                image_size=image.size,
                elapsed_ms=elapsed,
            )
            
        except Exception as e:
            logger.error(f"OCR recognition failed: {e}")
            return OCRResult(
                entries=[],
                full_text=f"(OCR错误: {e})",
                image_size=image.size,
                elapsed_ms=(time.perf_counter() - start) * 1000,
            )

    def recognize_screen(
        self,
        region: Optional[tuple] = None,
    ) -> OCRResult:
        """直接截屏并OCR（快捷方式）"""
        from .screenshot import get_screencap
        screencap = get_screencap()
        frame = screencap.capture(region=region)
        return self.recognize(frame.image)

    @staticmethod
    def _pil_to_numpy(image: Image.Image):
        """PIL Image → numpy数组"""
        import numpy as np
        return np.array(image.convert('RGB'))


# 全局单例
_ocr_instance: Optional[OCREngine] = None


def get_ocr() -> OCREngine:
    """获取全局OCR引擎"""
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = OCREngine()
    return _ocr_instance
