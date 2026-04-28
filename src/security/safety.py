"""
安全控制系统实现

提供：
- 急停热键监听
- 操作风险评分
- 权限白名单/黑名单
- 审计日志记录
- 操作计数限制
"""

import time
import json
import threading
import os
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from typing import Optional, Callable
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """风险等级"""
    SAFE = "safe"               # 安全 - 自动执行
    LOW = "low"                 # 低风险 - 记录即可
    MEDIUM = "medium"           # 中风险 - 记录+提醒
    HIGH = "high"               # 高风险 - 需要确认
    CRITICAL = "critical"       # 极危险 - 禁止或特殊授权
    FORBIDDEN = "forbidden"     # 绝对禁止


@dataclass
class AuditLog:
    """审计日志条目"""
    timestamp: str              # ISO时间戳
    task_id: str                # 关联任务ID
    action_type: str            # 动作类型 (click/type/drag...)
    action_detail: str          # 动作详情
    risk_level: str             # 风险等级
    target_app: str             # 目标应用
    target_window: str          # 目标窗口
    success: bool               # 是否成功
    duration_ms: float          # 耗时
    extra: dict = field(default_factory=dict)  # 附加信息

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


@dataclass
class PermissionRule:
    """权限规则"""
    pattern: str                # 匹配模式（窗口名/进程名/文件路径）
    action_types: list[str]     # 适用动作类型，空=全部
    level: RiskLevel = RiskLevel.SAFE
    description: str = ""


class SafetySystem:
    """
    安全控制系统
    
    负责：
    1. 急停热键全局监听
    2. 操作风险评估和拦截
    3. 审计日志写入
    4. 权限规则匹配
    5. 操作频率限制
    """

    # ---- 高风险操作关键词 ----
    DANGEROUS_KEYWORDS = {
        'delete', 'remove', 'uninstall', '卸载', '删除',
        'format', '格式化',
        'shutdown', 'reboot', '重启', '关机',
        'send', 'submit', '提交', '发送',
        'payment', 'pay', '支付', '付款',
        'password', '密码', 'secret', '密钥',
        'registry', '注册表', 'system', '系统设置',
        'admin', '管理员', 'administrator',
    }

    # ---- 受保护应用（操作时提高警惕） ----
    PROTECTED_APPS = {
        'explorer.exe': ('file_manager', RiskLevel.MEDIUM),
        'cmd.exe': ('terminal', RiskLevel.HIGH),
        'powershell.exe': ('terminal', RiskLevel.HIGH),
        'regedit.exe': ('registry_editor', RiskLevel.CRITICAL),
        'taskmgr.exe': ('task_manager', RiskLevel.MEDIUM),
        'msiexec.exe': ('installer', RiskLevel.MEDIUM),
        'control.exe': ('control_panel', RiskLevel.MEDIUM),
    }

    def __init__(self, audit_dir: str = "./logs/audit"):
        self._audit_dir = Path(audit_dir)
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        
        self._emergency_stop_flag = threading.Event()
        self._stop_listener_thread: Optional[threading.Thread] = None
        
        # 自定义权限规则
        self._custom_rules: list[PermissionRule] = []
        
        # 当前任务上下文
        self._current_task_id = ""
        
        # 统计
        self._actions_since_start = 0
        
        logger.info(f"SafetySystem initialized | audit_dir={audit_dir}")

    # ================================================================
    # 急停系统
    # ================================================================

    def start_stop_listener(self, hotkey: str = "ctrl+alt+shift+q") -> None:
        """
        启动急停热键监听线程
        
        默认 Ctrl+Alt+Shift+Q 触发紧急停止。
        使用Win32全局钩子实现。
        """
        import ctypes
        from ctypes.wintypes import BOOL, DWORD, LPARAM

        user32 = ctypes.wind32.user32

        def listener_loop():
            """持续检查急停组合键是否被按下"""
            keys_to_check = []
            
            # 解析热键组合
            parts = hotkey.lower().replace(" ", "").split("+")
            key_map = {
                'ctrl': 0x11, 'control': 0x11,
                'alt': 0x12,
                'shift': 0x10,
                'win': 0x5C,
                'q': ord('Q'), 'escape': 0x1B, 'f12': 0x7B,
            }
            
            for part in parts:
                if part in key_map:
                    keys_to_check.append(key_map[part])
            
            if not keys_to_check:
                logger.warning(f"Invalid stop hotkey format: {hotkey}")
                return
            
            logger.info(f"E-stop listener started | hotkey={hotkey} | "
                       f"keys={[hex(k) for k in keys_to_check]}")
            
            while not self._emergency_stop_flag.is_set():
                try:
                    # 使用GetAsyncKeyState检查按键状态
                    all_pressed = True
                    for vk in keys_to_check:
                        state = user32.GetAsyncKeyState(vk)
                        if not (state & 0x8000):  # 最高位=1表示按下
                            all_pressed = False
                            break
                    
                    if all_pressed and len(keys_to_check) > 1:
                        # 至少需要一个修饰键+一个普通键才触发（避免误触）
                        has_modifier = any(
                            k in [0x11, 0x12, 0x10, 0x5C]
                            for k in keys_to_check
                        )
                        if has_modifier or len(keys_to_check) >= 2:
                            self.trigger_emergency_stop()
                    
                    time.sleep(0.05)  # 20fps检测
                
                except Exception as e:
                    logger.error(f"Stop listener error: {e}")
                    time.sleep(0.5)

        self._stop_listener_thread = threading.Thread(target=listener_loop, daemon=True)
        self._stop_listener_thread.start()

    def trigger_emergency_stop(self) -> None:
        """触发紧急停止"""
        self._emergency_stop_flag.set()
        logger.warning("=" * 60)
        logger.warning("!!! EMERGENCY STOP ACTIVATED !!!")
        logger.warning("=" * 60)

    @property
    def is_stopped(self) -> bool:
        return self._emergency_stop_flag.is_set()

    def reset_emergency(self) -> None:
        """重置急停状态（恢复后调用）"""
        self._emergency_stop_flag.clear()
        logger.info("Emergency stop state reset")

    # ================================================================
    # 风险评估
    # ================================================================

    def assess_risk(
        self,
        action_type: str,
        detail: str = "",
        target_app: str = "",
        target_window: str = "",
    ) -> tuple[RiskLevel, str]:
        """
        评估操作风险
        
        Returns:
            (risk_level, reason)
        """
        combined_text = f"{action_type} {detail} {target_app} {target_window}".lower()
        
        # 检查绝对禁止的操作
        forbidden_patterns = [
            'format c:', 'del /s /q', 'rm -rf /',
            'reg delete', 'netsh advfirewall',
            'bcdedit', 'diskpart clean',
        ]
        for pattern in forbidden_patterns:
            if pattern.lower() in combined_text:
                return (
                    RiskLevel.FORBIDDEN,
                    f"匹配禁止模式: '{pattern}'",
                )
        
        # 检查受保护应用
        for app_name, (category, base_level) in self.PROTECTED_APPS.items():
            if app_name.lower() in combined_text:
                return (
                    max(base_level, RiskLevel.MEDIUM),
                    f"受保护应用: {app_name} ({category})",
                )
        
        # 检查危险关键词
        matched_dangerous = [
            kw for kw in self.DANGEROUS_KEYWORDS if kw in combined_text
        ]
        if matched_dangerous:
            if any(kw in ['format', '格式化', 'registry', '注册表']
                   for kw in matched_dangerous):
                return (RiskLevel.CRITICAL,
                        f"高危操作关键词: {matched_dangerous}")
            elif any(kw in ['delete', '删除', 'uninstall', '卸载']
                     for kw in matched_dangerous):
                return (RiskLevel.HIGH,
                        f"中危操作关键词: {matched_dangerous}")
            else:
                return (RiskLevel.MEDIUM,
                        f"敏感操作关键词: {matched_dangerous}")
        
        # 默认安全
        return (RiskLevel.SAFE, "正常操作")

    def check_permission(
        self,
        action_type: str,
        detail: str = "",
        target_app: str = "",
        target_window: str = "",
    ) -> bool:
        """
        检查是否有权执行此操作
        
        自动评估风险并决定是否允许
        """
        risk_level, reason = self.assess_risk(
            action_type, detail, target_app, target_window
        )
        
        match risk_level:
            case RiskLevel.SAFE | RiskLevel.LOW:
                return True
            case RiskLevel.MEDIUM | RiskLevel.HIGH:
                # 记录但不阻止（未来可以加用户确认）
                logger.info(f"[RISK-{risk_level.value}] {reason}")
                return True
            case RiskLevel.CRITICAL:
                logger.error(f"[RISK-CRITICAL] BLOCKED: {reason}")
                return False
            case RiskLevel.FORBIDDEN:
                logger.critical(f"[FORBIDDEN] BLOCKED: {reason}")
                return False

    # ================================================================
    # 审计日志
    # ================================================================

    def log_action(
        self,
        action_type: str,
        action_detail: str,
        risk_level: RiskLevel = RiskLevel.SAFE,
        target_app: str = "",
        target_window: str = "",
        success: bool = True,
        duration_ms: float = 0,
        **extra,
    ) -> AuditLog:
        """
        写入审计日志
        
        日志文件按日期分割: audit_2026-04-28.jsonl
        """
        entry = AuditLog(
            timestamp=datetime.now().isoformat(),
            task_id=self._current_task_id or "no-task",
            action_type=action_type,
            action_detail=action_detail,
            risk_level=risk_level.value if isinstance(risk_level, RiskLevel) else risk_level,
            target_app=target_app,
            target_window=target_window,
            success=success,
            duration_ms=duration_ms,
            extra=extra,
        )
        
        # 写入当日日志文件
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = self._audit_dir / f"audit_{date_str}.jsonl"
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(entry.to_json() + '\n')
        
        # 同时写控制台（根据级别）
        log_fn = {
            RiskLevel.SAFE: logger.debug,
            RiskLevel.LOW: logger.debug,
            RiskLevel.MEDIUM: logger.info,
            RiskLevel.HIGH: logger.warning,
            RiskLevel.CRITICAL: logger.error,
            RiskLevel.FORBIDDEN: logger.critical,
        }.get(risk_level, logger.info)
        
        log_fn(f"[AUDIT] [{risk_level.value}] {action_type}: {action_detail[:80]}")
        
        return entry

    def set_task_context(self, task_id: str) -> None:
        """设置当前任务上下文（用于关联日志）"""
        self._current_task_id = task_id

    def get_today_log_count(self) -> int:
        """获取今日日志条目数"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = self._audit_dir / f"audit_{date_str}.jsonl"
        if log_file.exists():
            with open(log_file, 'r', encoding='utf-8') as f:
                return sum(1 for _ in f)
        return 0

    # ================================================================
    # 权限规则管理
    # ================================================================

    def add_rule(self, rule: PermissionRule) -> None:
        """添加自定义权限规则"""
        self._custom_rules.append(rule)

    def remove_rule(self, pattern: str) -> None:
        """移除权限规则"""
        self._custom_rules = [
            r for r in self._custom_rules if r.pattern != pattern
        ]

    def get_rules(self) -> list[PermissionRule]:
        return list(self._custom_rules)


def get_safety() -> SafetySystem:
    from src.config.settings import settings
    return SafetySystem(audit_dir=settings.AUDIT_LOG_DIR)
