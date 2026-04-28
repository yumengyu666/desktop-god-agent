"""
模型网关核心 - 多模型自动路由
根据任务复杂度和类型，自动选择最优模型
"""

import base64
import time
from enum import Enum
from typing import Optional, Any, AsyncGenerator
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)

# ---- 延迟导入，避免启动时缺少依赖报错 ----
try:
    from openai import OpenAI as DeepSeekClient
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logger.warning("openai not installed, DeepSeek models unavailable")

try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    logger.warning("google-generativeai not installed, Gemini unavailable")

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


class ModelTier(str, Enum):
    """模型层级"""
    LOCAL = "local"           # Ollama本地模型
    FLASH = "flash"           # DeepSeek Flash (轻量)
    PRO = "pro"               # DeepSeek V4 Pro (重量)
    VISION = "vision"         # Google Gemini (视觉)


@dataclass
class ChatMessage:
    """标准消息格式"""
    role: str                 # system / user / assistant
    content: str | list       # 文本 或 [多模态内容]
    images: list[bytes] = field(default_factory=list)  # 附带图片(bytes)


@dataclass
class GatewayResponse:
    """网关统一响应"""
    content: str
    model_used: ModelTier
    model_name: str
    latency_ms: float
    tokens_used: int = 0
    raw_response: Any = None


class ModelGateway:
    """
    统一模型网关
    根据任务类型自动选择最优模型，支持负载均衡和故障转移
    """

    def __init__(self):
        from src.config.settings import settings
        self._settings = settings
        self._clients: dict[str, Any] = {}
        self._init_clients()
        # 请求计数（用于轮询）
        self._request_count = 0

        logger.info(f"ModelGateway initialized | "
                     f"DeepSeek: {len(self._settings.DEEPSEEK_API_KEYS)} keys | "
                     f"Gemini: {'yes' if HAS_GEMINI else 'no'}")

    def _init_clients(self) -> None:
        """初始化所有模型客户端"""
        # DeepSeek 客户端（OpenAI兼容协议）
        if HAS_OPENAI and self._settings.DEEPSEEK_API_KEYS:
            for i, key in enumerate(self._settings.DEEPSEEK_API_KEYS):
                try:
                    client = DeepSeekClient(
                        api_key=key,
                        base_url=self._settings.DEPSEEK_BASE_URL,
                        timeout=60.0,
                    )
                    self._clients[f"deepseek_{i}"] = {
                        "client": client,
                        "flash_model": self._settings.DEEPSEEK_FLASH_MODEL,
                        "pro_model": self._settings.DEEPSEEK_PRO_MODEL,
                    }
                    logger.info(f"DeepSeek client {i} initialized")
                except Exception as e:
                    logger.error(f"Failed to init DeepSeek client {i}: {e}")

        # Gemini 客户端
        if HAS_GEMINI and self._settings.GOOGLE_AI_API_KEY:
            try:
                genai.configure(api_key=self._settings.GOOGLE_AI_API_KEY)
                self._clients["gemini"] = genai.GenerativeModel(
                    self._settings.GOOGLE_AI_MODEL
                )
                logger.info("Gemini client initialized")
            except Exception as e:
                logger.error(f"Failed to init Gemini client: {e}")

        # Ollama 客户端（本地）
        ollama_url = self._settings.OLLAMA_BASE_URL
        if HAS_HTTPX and ollama_url:
            self._clients["ollama"] = {
                "base_url": ollama_url,
                "model": self._settings.OLLAMA_MODEL,
            }

    # ================================================================
    # 公开接口
    # ================================================================

    def chat(
        self,
        messages: list[ChatMessage],
        tier: Optional[ModelTier] = None,
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
    ) -> GatewayResponse:
        """
        主聊天接口 - 自动或手动选择模型

        Args:
            messages: 对话消息列表
            tier: 指定模型层级，None则自动选择
            temperature: 温度参数
            max_tokens: 最大输出token
            stream: 是否流式返回
        """
        # 自动选择模型
        if tier is None:
            tier = self._auto_select_tier(messages)

        start = time.perf_counter()

        try:
            match tier:
                case ModelTier.LOCAL:
                    resp = self._call_ollama(messages, temperature, max_tokens, stream)
                case ModelTier.FLASH:
                    resp = self._call_deepseek_flash(messages, temperature, max_tokens, stream)
                case ModelTier.PRO:
                    resp = self._call_deepseek_pro(messages, temperature, max_tokens, stream)
                case ModelTier.VISION:
                    resp = self._call_gemini(messages, temperature, max_tokens)
                case _:
                    raise ValueError(f"Unknown model tier: {tier}")
        except Exception as e:
            logger.error(f"[{tier.value}] call failed: {e}, attempting fallback...")
            resp = self._fallback(messages, tier, temperature, max_tokens)

        latency = (time.perf_counter() - start) * 1000
        resp.latency_ms = latency
        logger.info(f"[{resp.model_name}] {latency:.0f}ms | "
                     f"{len(resp.content)} chars | tier={tier.value}")
        return resp

    async def chat_async(
        self,
        messages: list[ChatMessage],
        tier: Optional[ModelTier] = None,
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> GatewayResponse:
        """异步版本（未来扩展用）"""
        return self.chat(messages, tier, temperature=temperature, max_tokens=max_tokens)

    def chat_stream(
        self,
        messages: list[ChatMessage],
        tier: Optional[ModelTier] = None,
    ) -> AsyncGenerator[str, None]:
        """流式聊天接口"""
        raise NotImplementedError("Stream mode coming soon")

    # ================================================================
    # 内部实现 - 各模型调用
    # ================================================================

    def _auto_select_tier(self, messages: list[ChatMessage]) -> ModelTier:
        """根据消息内容自动选择最佳模型"""

        # 有图片 → 必须走视觉模型
        for msg in messages:
            if msg.images:
                return ModelTier.VISION

        # 合并所有用户消息做判断
        combined_text = " ".join(
            m.content if isinstance(m.content, str) else str(m.content)
            for m in messages if m.role == "user"
        )

        # 长文本 / 复杂任务 → Pro
        if len(combined_text) > 1000 or any(kw in combined_text.lower() for kw in [
            "规划", "计划", "设计", "分析", "恢复", "异常", "错误",
            "plan", "design", "analyze", "recover", "error",
        ]):
            return ModelTier.PRO

        # 简短判断 → 本地模型优先
        if len(combined_text) < 200 and any(kw in combined_text.lower() for kw in [
            "是什么", "哪个", "是否", "状态", "当前",
            "what", "which", "is it", "status", "current",
        ]):
            return ModelTier.LOCAL

        # 默认 Flash（性价比最高）
        return ModelTier.FLASH

    def _get_deepseek_client(self) -> tuple[Any, dict]:
        """轮询获取 DeepSeek 客户端"""
        deepseek_keys = [k for k in self._clients.keys() if k.startswith("deepseek_")]
        if not deepseek_keys:
            raise RuntimeError("No DeepSeek client available")
        idx = self._request_count % len(deepseek_keys)
        self._request_count += 1
        key_name = deepseek_keys[idx]
        return key_name, self._clients[key_name]

    def _format_messages_for_openai(
        self, messages: list[ChatMessage]
    ) -> list[dict]:
        """转换为 OpenAI 格式"""
        result = []
        for msg in messages:
            if msg.images:
                # 多模态消息
                content_parts = []
                if isinstance(msg.content, str) and msg.content:
                    content_parts.append({"type": "text", "text": msg.content})
                elif isinstance(msg.content, list):
                    content_parts.extend(msg.content)
                for img_bytes in msg.images:
                    b64 = base64.b64encode(img_bytes).decode()
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    })
                result.append({"role": msg.role, "content": content_parts})
            else:
                text = msg.content if isinstance(msg.content, str) else str(msg.content)
                result.append({"role": msg.role, "content": text})
        return result

    def _call_deepseek_flash(
        self, messages: list[ChatMessage], temp: float, max_tok: int, stream: bool
    ) -> GatewayResponse:
        """调用 DeepSeek Flash 模型"""
        _, cfg = self._get_deepseek_client()
        formatted = self._format_messages_for_openai(messages)

        response = cfg["client"].chat.completions.create(
            model=cfg["flash_model"],
            messages=formatted,
            temperature=temp,
            max_tokens=max_tok,
            stream=stream,
        )

        if stream:
            # 流式收集
            chunks = []
            for chunk in response:
                if chunk.choices[0].delta.content:
                    chunks.append(chunk.choices[0].delta.content)
            content = "".join(chunks)
        else:
            content = response.choices[0].message.content or ""

        return GatewayResponse(
            content=content,
            model_used=ModelTier.FLASH,
            model_name=cfg["flash_model"],
            latency_ms=0,
            tokens_used=getattr(response.usage, 'total_tokens', 0),
            raw_response=response,
        )

    def _call_deepseek_pro(
        self, messages: list[ChatMessage], temp: float, max_tok: int, stream: bool
    ) -> GatewayResponse:
        """调用 DeepSeek V4 Pro 模型"""
        _, cfg = self._get_deepseek_client()
        formatted = self._format_messages_for_openai(messages)

        response = cfg["client"].chat.completions.create(
            model=cfg["pro_model"],
            messages=formatted,
            temperature=temp,
            max_tokens=max_tok * 2,  # Pro模型通常需要更多token思考
            stream=stream,
        )

        if stream:
            chunks = []
            for chunk in response:
                if chunk.choices[0].delta.content:
                    chunks.append(chunk.choices[0].delta.content)
            content = "".join(chunks)
        else:
            content = response.choices[0].message.content or ""

        return GatewayResponse(
            content=content,
            model_used=ModelTier.PRO,
            model_name=cfg["pro_model"],
            latency_ms=0,
            tokens_used=getattr(response.usage, 'total_tokens', 0),
            raw_response=response,
        )

    def _call_ollama(
        self, messages: list[ChatMessage], temp: float, max_tok: int, stream: bool
    ) -> GatewayResponse:
        """调用 Ollama 本地模型"""
        if not HAS_HTTPX:
            raise RuntimeError("httpx required for Ollama calls")

        cfg = self._clients.get("ollama")
        if not cfg:
            raise RuntimeError("Ollama not configured")

        formatted = []
        for msg in messages:
            text = msg.content if isinstance(msg.content, str) else str(msg.content)
            formatted.append({"role": msg.role, "content": text})

        try:
            resp = httpx.post(
                f"{cfg['base_url']}/api/chat",
                json={
                    "model": cfg["model"],
                    "messages": formatted,
                    "options": {"temperature": temp, "num_predict": min(max_tok, 2048)},
                    "stream": False,
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["message"]["content"]

            return GatewayResponse(
                content=content,
                model_used=ModelTier.LOCAL,
                model_name=cfg["model"],
                latency_ms=0,
                tokens_used=data.get("eval_count", 0),
                raw_response=data,
            )
        except Exception as e:
            logger.warning(f"Ollama call failed: {e}, falling back to Flash")
            # 本地失败时降级到Flash
            return self._call_deepseek_flash(messages, temp, max_tok, stream)

    def _call_gemini(
        self, messages: list[ChatMessage], temp: float, max_tok: int
    ) -> GatewayResponse:
        """调用 Google Gemini 视觉模型"""
        if not HAS_GEMINI:
            raise RuntimeError("google-generativeai not installed")

        model: genai.GenerativeModel = self._clients.get("gemini")
        if not model:
            raise RuntimeError("Gemini not configured")

        # 构建Gemini格式的对话
        gemini_contents = []
        for msg in messages:
            parts = []

            # 文本部分
            if isinstance(msg.content, str) and msg.content:
                parts.append(msg.content)
            elif isinstance(msg.content, list):
                parts.extend([str(p) for p in msg.content])

            # 图片部分
            for img_bytes in msg.images:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(img_bytes))
                parts.append(img)

            if parts:
                gemini_contents.append(
                    {"role": "user" if msg.role != "assistant" else "model", "parts": parts}
                )

        try:
            response = model.generate_content(
                gemini_contents,
                generation_config=genai.types.GenerationConfig(
                    temperature=temp,
                    max_output_tokens=max_tok,
                ),
            )
            content = response.text if hasattr(response, "text") else str(response.candidates[0].content)

            return GatewayResponse(
                content=content,
                model_used=ModelTier.VISION,
                model_name=self._settings.GOOGLE_AI_MODEL,
                latency_ms=0,
                tokens_used=getattr(response.usage_metadata, 'total_token_count', 0),
                raw_response=response,
            )
        except Exception as e:
            logger.error(f"Gemini call failed: {e}")
            # 视觉模型失败时尝试用纯文本描述
            no_img_msgs = [
                ChatMessage(role=m.role, content=m.content) for m in messages
            ]
            return self._call_deepseek_flash(no_img_msgs, temp, max_tok, False)

    def _fallback(
        self,
        messages: list[ChatMessage],
        failed_tier: ModelTier,
        temp: float,
        max_tok: int,
    ) -> GatewayResponse:
        """故障转移策略"""
        fallback_chain: dict[ModelTier, list[ModelTier]] = {
            ModelTier.LOCAL: [ModelTier.FLASH, ModelTier.PRO],
            ModelTier.FLASH: [ModelTier.PRO, ModelTier.LOCAL],
            ModelTier.PRO: [ModelTier.FLASH, ModelTier.LOCAL],
            ModelTier.VISION: [ModelTier.PRO, ModelTier.FLASH],
        }

        for fallback_tier in fallback_chain.get(failed_tier, []):
            try:
                logger.info(f"Fallback: {failed_tier.value} -> {fallback_tier.value}")
                match fallback_tier:
                    case ModelTier.LOCAL:
                        return self._call_ollama(messages, temp, max_tok, False)
                    case ModelTier.FLASH:
                        return self._call_deepseek_flash(messages, temp, max_tok, False)
                    case ModelTier.PRO:
                        return self._call_deepseek_pro(messages, temp, max_tok, False)
            except Exception:
                continue

        raise RuntimeError(f"All model backends failed after {failed_tier.value} failure")


# 全局单例
_gateway_instance: Optional[ModelGateway] = None


def get_gateway() -> ModelGateway:
    """获取全局模型网关单例"""
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = ModelGateway()
    return _gateway_instance
