"""
Desktop God Agent - 配置管理中心
统一管理所有环境变量和运行时配置
"""

import os
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ============================================================
# 项目根目录
# ============================================================
PROJECT_ROOT = Path(__file__).parent.parent


class Settings:
    """全局单例配置，从环境变量加载"""

    # ---- DeepSeek API ----
    DEEPSEEK_API_KEYS: list = [
        k.strip() for k in os.getenv("DEEPSEEK_API_KEY", "").split(",")
        if k.strip()
    ]
    if os.getenv("DEEPSEEK_API_KEY_2"):
        DEEPSEEK_API_KEYS.append(os.getenv("DEEPSEEK_API_KEY_2").strip())
    # 去重
    DEEPSEEK_API_KEYS = list(dict.fromkeys(DEEPSEEK_API_KEYS))

    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_FLASH_MODEL: str = os.getenv("DEEPSEEK_FLASH_MODEL", "deepseek-chat")
    DEEPSEEK_PRO_MODEL: str = os.getenv("DEEPSEEK_PRO_MODEL", "deepseek-reasoner")

    # ---- Google AI (Gemini) 视觉模型 ----
    GOOGLE_AI_API_KEY: str = os.getenv("GOOGLE_AI_API_KEY", "")
    GOOGLE_AI_MODEL: str = os.getenv("GOOGLE_AI_MODEL", "gemini-3-flash-preview")

    # ---- Ollama 本地模型 ----
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "deepseek-r1:8b")

    # ---- GitHub ----
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GITHUB_TOKEN_PAT: str = os.getenv("GITHUB_TOKEN_PAT", "")
    GITHUB_REPO: str = os.getenv("GITHUB_REPO", "")

    # ---- 感知系统 ----
    SCREEN_CAPTURE_INTERVAL_MS: int = int(os.getenv("SCREEN_CAPTURE_INTERVAL_MS", "100"))
    UIA_SCAN_INTERVAL_MS: int = int(os.getenv("UIA_SCAN_INTERVAL_MS", "500"))
    OCR_ENGINE: str = os.getenv("OCR_ENGINE", "paddleocr")

    # ---- 执行引擎 ----
    MOUSE_MOVE_DURATION_MS: int = int(os.getenv("MOUSE_MOVE_DURATION_MS", "300"))
    KEYBOARD_TYPE_DELAY_MS: int = int(os.getenv("KEYBOARD_TYPE_DELAY_MS", "50"))
    ACTION_VERIFY_TIMEOUT_MS: int = int(os.getenv("ACTION_VERIFY_TIMEOUT_MS", "3000"))

    # ---- 安全控制 ----
    EMERGENCY_STOP_KEY: str = os.getenv("EMERGENCY_STOP_KEY", "ctrl+alt+shift+q")
    AUDIT_LOG_DIR: str = os.getenv("AUDIT_LOG_DIR", "./logs/audit")
    MAX_ACTIONS_PER_TASK: int = int(os.getenv("MAX_ACTIONS_PER_TASK", "100"))

    # ---- 记忆系统 ----
    MEMORY_DB_PATH: str = os.getenv("MEMORY_DB_PATH", "./data/memory.db")
    MEMORY_PROMOTION_THRESHOLD: int = int(os.getenv("MEMORY_PROMOTION_THRESHOLD", "3"))

    # ---- 日志 ----
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("LOG_DIR", "./logs")

    # ---- 路径 ----
    DATA_DIR: Path = PROJECT_ROOT / "data"
    LOGS_DIR: Path = PROJECT_ROOT / "logs"
    CHECKPOINTS_DIR: Path = PROJECT_ROOT / "checkpoints"

    @classmethod
    def ensure_dirs(cls) -> None:
        """确保所有必要目录存在"""
        for d in [cls.DATA_DIR, cls.LOGS_DIR, cls.CHECKPOINTS_DIR,
                  cls.LOGS_DIR / "audit"]:
            d.mkdir(parents=True, exist_ok=True)

    @classmethod
    def validate(cls) -> list[str]:
        """验证关键配置是否完整，返回缺失项列表"""
        missing = []
        if not cls.DEEPSEEK_API_KEYS or not any(cls.DEEPSEEK_API_KEYS):
            missing.append("DEEPSEEK_API_KEY")
        if not cls.GOOGLE_AI_API_KEY:
            missing.append("GOOGLE_AI_API_KEY")
        if not cls.GITHUB_TOKEN and not cls.GITHUB_TOKEN_PAT:
            missing.append("GITHUB_TOKEN")
        return missing

    @classmethod
    def get_deepseek_key(cls) -> str:
        """轮询获取 DeepSeek API Key（负载均衡）"""
        if not cls.DEEPSEEK_API_KEYS:
            raise RuntimeError("No DeepSeek API key configured")
        import time
        idx = int(time.time()) % len(cls.DEEPSEEK_API_KEYS)
        return cls.DEEPSEEK_API_KEYS[idx]

    @classmethod
    def get_github_token(cls) -> str:
        """获取可用的 GitHub Token"""
        return cls.GITHUB_TOKEN or cls.GITHUB_TOKEN_PAT


settings = Settings()
