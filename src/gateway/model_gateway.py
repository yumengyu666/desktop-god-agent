"""
模型网关核心 - 多模型自动路由（v2）
根据任务复杂度和类型，自动选择最优模型

支持的模型：
- deepseek-v4-flash  : 轻量快速文本（日常任务、简单判断、圈养工种）
- deepseek-v4-pro    : 复杂推理（长链规划、异常恢复、代码生成）
- gemini-2.5-flash   : 视觉理解（屏幕截图、OCR辅助、对象检测）

路由策略：
- 有图片 → Gemini
- 长文本/复杂推理 → Pro
- 其他 → Flash（默认）
"""

import base64
import time
import asyncio
from enum import Enum
from typing import Optional, Any, AsyncGenerator, List
from dataclasses import dataclass, field
import logging

logger = logging.getLogger("Gateway")

# ---- 延迟导入 ----
try:
    from openai import OpenAI as DeepSeekClient
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logger.warning("openai not installed, DeepSeek models unavailable")

try:
    from google import genai
    from google.genai import types as genai_types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    logger.warning("google-genai not installed, Gemini vision unavailable")


class ModelTier(str, Enum):
    """模型层级"""
    FLASH = "flash"           # DeepSeek V4 Flash (轻量快速)
    PRO = "pro"               # DeepSeek V4 Pro (深度推理)
    VISION = "vision"         # Google Gemini 2.5 Flash (视觉)


@dataclass
class ChatMessage:
    """标准消息格式"""
    role: str                          # system / user / assistant
    content: str | list                # 文本 或 [多模态内容]
    images: List[bytes] = field(default_factory=list)  # 附带图片(bytes)


@dataclass
class GatewayResponse:
    """网关统一响应"""
    content: str
    model_used: ModelTier
    model_name: str
    latency_ms: float = 0.0
    tokens_used: int = 0
    raw_response: Any = None


class ModelGateway:
    """
    统一模型网关 - v2
    
    三模型架构：
    ┌─────────────┬──────────────┬─────────────────┐
    │ Flash       │ Pro          │ Gemini Vision   │
    │ 日常/简单   │ 复杂/推理     │ 截图/视觉       │
    │ ~200ms      │ ~2s          │ ~1.5s           │
    └─────────────┴──────────────┴─────────────────┘
    
    支持：轮询负载均衡 + 故障转移链 + 异步调用
    """

    def __init__(self):
        from src.config.settings import settings
        self._settings = settings
        self._deepseek_clients: list[dict] = []
        self._gemini_client: Any = None
        self._request_count = 0
        self._init_clients()

        logger.info(
            f"ModelGateway v2 | "
            f"DeepSeek: {len(self._deepseek_clients)} clients | "
            f"Gemini: {'yes' if self._gemini_client else 'no'}"
        )

    def _init_clients(self):
        """初始化所有客户端"""
        # === DeepSeek 客户端（OpenAI兼容） ===
        if HAS_OPENAI and self._settings.DEEPSEEK_API_KEYS:
            for i, key in enumerate(self._settings.DEEPSEEK_API_KEYS):
                try:
                    client = DeepSeekClient(
                        api_key=key,
                        base_url=self._settings.DEPSEEK_BASE_URL,
                        timeout=60.0,
                    )
                    self._deepseek_clients.append({
                        "client": client,
                        "flash_model": self._settings.DEEPSEEK_FLASH_MODEL,
                        "pro_model": self._settings.DEEPSEEK_PRO_MODEL,
                    })
                    logger.info(f"DeepSeek client {i} OK")
                except Exception as e:
                    logger.error(f"DeepSeek client {i} init failed: {e}")

        # === Gemini 客户端（google-genai SDK） ===
        if HAS_GEMINI and self._settings.GOOGLE_AI_API_KEY:
            try:
                self._gemini_client = genai.Client(
                    api_key=self._settings.GOOGLE_AI_API_KEY
                )
                logger.info(f"Gemini client OK (model={self._settings.GOOGLE_AI_MODEL})")
            except Exception as e:
                logger.error(f"Gemini init failed: {e}")

    # ================================================================
    #  公开接口 - 同步版本（兼容旧代码）
    # ================================================================

    def chat(
        self,
        messages: list | None = None,         # 兼容旧格式: list[ChatMessage]
        *,
        # 新简化接口（推荐）
        user_message: str = "",
        system_prompt: str = "",
        images: List[bytes] | None = None,
        tier: ModelTier | str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict | None = None,  # JSON mode等
    ) -> GatewayResponse:
        """
        主聊天接口
        
        支持两种调用方式：
        1. 旧式: gateway.chat([ChatMessage(...)], tier=ModelTier.FLASH)
        2. 新式: gateway.chat(user_message="打开Chrome", tier="flash")
        
        Args:
            messages: 消息列表（旧式）
            user_message: 用户消息文本（新式，推荐）
            system_prompt: 系统提示词（新式）
            images: 图片数据列表（新式）
            tier: 模型层级，None=自动选择
            temperature: 温度
            max_tokens: 最大输出token
            response_format: OpenAI响应格式约束
        """
        # 统一新旧两种格式为内部格式
        if messages is not None:
            # 旧式调用：直接用messages
            msg_list = messages
        else:
            # 新式调用：构建消息列表
            msg_list = []
            if system_prompt:
                msg_list.append(ChatMessage(role="system", content=system_prompt))
            if images:
                msg_list.append(ChatMessage(
                    role="user", content=user_message, images=images or []
                ))
            else:
                msg_list.append(ChatMessage(role="user", content=user_message))

        # 自动选择模型
        if isinstance(tier, str) and tier:
            tier = ModelTier(tier)
        if tier is None:
            tier = self._auto_select(msg_list)

        start = time.perf_counter()

        try:
            match tier:
                case ModelTier.FLASH:
                    resp = self._call_deepseek(msg_list, "flash",
                                                temperature, max_tokens, response_format)
                case ModelTier.PRO:
                    resp = self._call_deepseek(msg_list, "pro",
                                                temperature, max_tokens, response_format)
                case ModelTier.VISION:
                    resp = self._call_gemini(msg_list, temperature, max_tokens)
                case _:
                    raise ValueError(f"Unknown tier: {tier}")
        except Exception as e:
            logger.error(f"[{tier.value}] call failed: {e}, fallback...")
            resp = self._fallback(msg_list, tier, temperature, max_tokens)

        latency = (time.perf_counter() - start) * 1000
        resp.latency_ms = latency

        logger.debug(
            f"[{resp.model_name}] {latency:.0f}ms | "
            f"{len(resp.content)} chars"
        )
        return resp

    # ================================================================
    #  公开接口 - 异步版本（圈养工种使用）
    # ================================================================

    async def chat_async(
        self,
        user_message: str,
        system_prompt: str = "",
        images: List[bytes] | None = None,
        tier: ModelTier | str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> GatewayResponse:
        """异步聊天接口 - 在线程池中执行同步调用"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.chat(
                user_message=user_message,
                system_prompt=system_prompt,
                images=images,
                tier=tier,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            ),
        )

    # 简化别名（给圈养系统用的便捷方法）
    async def ask_flash(self, prompt: str, system: str = "", **kwargs) -> str:
        """快速调用Flash并返回纯文本"""
        r = await self.chat_async(prompt, system, tier="flash", **kwargs)
        return r.content

    async def ask_pro(self, prompt: str, system: str = "", **kwargs) -> str:
        """快速调用Pro并返回纯文本"""
        r = await self.chat_async(prompt, system, tier="pro", **kwargs)
        return r.content

    async def vision(self, image_bytes: bytes, question: str = "") -> str:
        """快速调用Gemini视觉"""
        r = await self.chat_async(
            user_message=question or "描述这个屏幕截图的内容",
            images=[image_bytes],
            tier="vision",
        )
        return r.content

    async def detect_objects(self, image_bytes: bytes, prompt: str = "") -> list[dict]:
        """Gemini对象检测（返回边界框列表）"""
        if not HAS_GEMINI:
            return []
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, 
            lambda: self._gemini_detect(image_bytes, prompt))
        return result

    # ================================================================
    #  内部实现
    # ================================================================

    def _auto_select(self, messages: list[ChatMessage]) -> ModelTier:
        """自动选择最优模型"""

        # 有图片 → 必须走Gemini
        for m in messages:
            if getattr(m, 'images', None):
                return ModelTier.VISION

        # 合并用户消息
        combined = " ".join(
            (m.content if isinstance(m.content, str) else str(m.content))
            for m in messages if m.role in ("user", "assistant")
        ).lower()

        # 复杂推理关键词 → Pro
        complex_keywords = [
            "规划", "计划", "设计", "分析", "恢复", "异常", "错误处理",
            "plan", "design", "analyze", "recover", "debug",
            "为什么", "如何解决", "根因", "方案设计",
        ]
        long_text = len(combined) > 800
        is_complex = any(kw in combined for kw in complex_keywords)

        if long_text or is_complex:
            return ModelTier.PRO

        # 默认 Flash
        return ModelTier.FLASH

    def _get_deepseek(self) -> dict:
        """轮询获取DeepSeek客户端"""
        if not self._deepseek_clients:
            raise RuntimeError("No DeepSeek client available")
        idx = self._request_count % len(self._deepseek_clients)
        self._request_count += 1
        return self._deepseek_clients[idx]

    def _format_for_deepseek(self, messages: list[ChatMessage]) -> list[dict]:
        """转换为OpenAI格式"""
        result = []
        for m in messages:
            if getattr(m, 'images', None):
                parts = []
                text = m.content if isinstance(m.content, str) else str(m.content)
                if text:
                    parts.append({"type": "text", "text": text})
                for img in m.images:
                    b64 = base64.b64encode(img).decode()
                    parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    })
                result.append({"role": m.role, "content": parts})
            else:
                text = m.content if isinstance(m.content, str) else str(m.content)
                result.append({"role": m.role, "content": text})
        return result

    def _call_deepseek(
        self,
        messages: list[ChatMessage],
        mode: str,              # "flash" or "pro"
        temp: float,
        max_tok: int,
        response_format: dict | None = None,
    ) -> GatewayResponse:
        """调用DeepSeek API"""
        cfg = self._get_deepseek()
        model_name = cfg[f"{mode}_model"]
        formatted = self._format_for_deepseek(messages)

        kwargs = dict(
            model=model_name,
            messages=formatted,
            temperature=temp,
            max_tokens=max_tok,
        )
        if response_format:
            kwargs["response_format"] = response_format

        response = cfg["client"].chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""

        return GatewayResponse(
            content=content,
            model_used=ModelTier.FLASH if mode == "flash" else ModelTier.PRO,
            model_name=model_name,
            tokens_used=getattr(response.usage, 'total_tokens', 0),
            raw_response=response,
        )

    def _call_gemini(
        self,
        messages: list[ChatMessage],
        temp: float,
        max_tok: int,
    ) -> GatewayResponse:
        """
        调用Google Gemini 2.5 Flash（视觉模型）
        使用 google-genai SDK（非旧的 google.generativeai）
        """
        if not HAS_GEMINI or not self._gemini_client:
            raise RuntimeError("Gemini not available")

        # 构建contents
        contents = []
        for m in messages:
            parts = []

            # 文本部分
            text = m.content if isinstance(m.content, str) else str(m.content)
            if text:
                parts.append(text)

            # 图片部分（内嵌bytes）
            for img_bytes in getattr(m, 'images', []) or []:
                parts.append(genai_types.Part.from_bytes(
                    data=img_bytes,
                    mime_type="image/png",
                ))

            if parts:
                contents.append(parts)

        try:
            response = self._gemini_client.models.generate_content(
                model=self._settings.GOOGLE_AI_MODEL,
                contents=contents,
                config=genai_types.GenerateContentConfig(
                    temperature=temp,
                    max_output_tokens=max_tok,
                ),
            )
            content = response.text if hasattr(response, 'text') else str(response)

            return GatewayResponse(
                content=content,
                model_used=ModelTier.VISION,
                model_name=self._settings.GOOGLE_AI_MODEL,
                tokens_used=0,  # Gemini token统计方式不同
                raw_response=response,
            )
        except Exception as e:
            logger.error(f"Gemini call failed: {e}, falling back to Flash")
            # 视觉失败降级到纯文本Flash
            no_img_msgs = [ChatMessage(role=m.role, content=m.content) for m in messages]
            return self._call_deepseek(no_img_msgs, "flash", temp, max_tok)

    def _gemini_detect(
        self, image_bytes: bytes, custom_prompt: str = ""
    ) -> list[dict]:
        """
        使用Gemini进行对象检测
        返回边界框列表: [{"label": str, "box_2d": [ymin,xmin,ymax,xmax], "confidence": float}]
        """
        if not HAS_GEMINI or not self._gemini_client:
            return []

        prompt = custom_prompt or (
            "Detect all prominent UI elements (buttons, icons, text areas, inputs, links). "
            "Return a JSON list with label and box_2d normalized to 0-1000. "
            'Format: [{"label": "...", "box_2d": [ymin, xmin, ymax, xmax]}]'
        )

        try:
            image_part = genai_types.Part.from_bytes(data=image_bytes, mime_type="image/png")
            
            response = self._gemini_client.models.generate_content(
                model=self._settings.GOOGLE_AI_MODEL,
                contents=[image_part, prompt],
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
                ),
            )
            
            import json
            result = json.loads(response.text)
            if isinstance(result, list):
                return result
            return []
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Gemini object detection failed: {e}")
            return []

    def _fallback(
        self,
        messages: list[ChatMessage],
        failed_tier: ModelTier,
        temp: float,
        max_tok: int,
    ) -> GatewayResponse:
        """故障转移链"""
        chain: dict[ModelTier, list[ModelTier]] = {
            ModelTier.FLASH: [ModelTier.PRO],
            ModelTier.PRO: [ModelTier.FLASH],
            ModelTier.VISION: [ModelTier.FLASH],  # 视觉降级为纯文本
        }

        for fallback_tier in chain.get(failed_tier, []):
            try:
                logger.info(f"Fallback: {failed_tier.value} → {fallback_tier.value}")
                if fallback_tier == ModelTier.VISION:
                    return self._call_gemini(messages, temp, max_tok)
                else:
                    mode = "flash" if fallback_tier == ModelTier.FLASH else "pro"
                    return self._call_deepseek(messages, mode, temp, max_tok)
            except Exception as e2:
                logger.warning(f"Fallback {fallback_tier.value} also failed: {e2}")
                continue

        raise RuntimeError(f"All backends exhausted after {failed_tier.value} failure")

    def health_check(self) -> dict:
        """健康检查 - 测试各模型连通性"""
        results = {}
        
        # 测试Flash
        try:
            r = self.chat(user_message="ping", tier="flash", max_tokens=5)
            results["flash"] = {"ok": True, "model": r.model_name, "latency": r.latency_ms}
        except Exception as e:
            results["flash"] = {"ok": False, "error": str(e)}

        # 测试Pro
        try:
            r = self.chat(user_message="ping", tier="pro", max_tokens=5)
            results["pro"] = {"ok": True, "model": r.model_name, "latency": r.latency_ms}
        except Exception as e:
            results["pro"] = {"ok": False, "error": str(e)}

        # 测试Gemini
        try:
            r = self.chat(user_message="ping", tier="vision", max_tokens=5)
            results["vision"] = {"ok": True, "model": r.model_name, "latency": r.latency_ms}
        except Exception as e:
            results["vision"] = {"ok": False, "error": str(e)}

        return results


# ================================================================
# 全局单例
# ================================================================
_gateway_instance: Optional[ModelGateway] = None


def get_gateway() -> ModelGateway:
    """获取全局网关单例"""
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = ModelGateway()
    return _gateway_instance


# 给 workers.py 的异步兼容层（避免循环导入问题）
async def gateway_chat(user_msg, system="", images=None, tier="flash", **kw):
    """独立函数供外部模块直接调用，无需实例化"""
    g = get_gateway()
    return await g.chat_async(user_msg, system, images, tier=tier, **kw)
