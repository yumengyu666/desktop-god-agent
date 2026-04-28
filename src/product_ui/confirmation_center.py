"""
确认中心 - 任务确认层
AI接到任务后不直接做，先返回理解结果让用户确认

确认策略：
- 高频小事静默处理（打开文件夹、复制文本）
- 中风险轻提示（上传文件、发送邮件）
- 高风险强确认（删除文件、格式化磁盘）

风险等级由安全模块评估
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable, Any
from enum import Enum

logger = logging.getLogger("ProductUI.Confirmation")


class RiskLevel(str, Enum):
    SAFE = "safe"             # 静默执行，不需要确认
    LOW = "low"               # 轻提示，1秒自动继续
    MEDIUM = "medium"         # 需要用户确认，有默认选项
    HIGH = "high"             # 强制等待用户明确确认
    FORBIDDEN = "forbidden"   # 禁止执行


# 风险等级对应的默认行为
RISK_DEFAULTS = {
    RiskLevel.SAFE:     {"auto_confirm": True,  "timeout_s": 0},
    RiskLevel.LOW:      {"auto_confirm": True,  "timeout_s": 2},
    RiskLevel.MEDIUM:   {"auto_confirm": False, "timeout_s": 30},
    RiskLevel.HIGH:     {"auto_confirm": False, "timeout_s": 120},  # 等待确认
    RiskLevel.FORBIDDEN:{"auto_confirm": False, "timeout_s": -1},  # 不执行
}


@dataclass
class ConfirmationRequest:
    """确认请求"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    task_description: str = ""
    planned_actions: list = field(default_factory=list)      # 计划执行的步骤
    risk_level: RiskLevel = RiskLevel.MEDIUM
    affected_items: list = field(default_factory=list)       # 受影响的文件/对象
    estimated_time_s: float = 0.0
    created_at: float = field(default_factory=time.time)
    
    # 结果
    confirmed: bool = False
    denied: bool = False
    responded_at: Optional[float] = None
    user_note: str = ""                                     # 用户附加备注

    @property
    def is_pending(self) -> bool:
        return not self.confirmed and not self.denied
    
    @property
    def elapsed_s(self) -> float:
        return time.time() - self.created_at

    def to_user_message(self) -> str:
        """生成面向用户的确认消息"""
        parts = []
        
        # 开头
        prefix_map = {
            RiskLevel.SAFE: "🟢 即将执行:",
            RiskLevel.LOW: "🔵 准备执行:",
            RiskLevel.MEDIUM: "🟡 请确认:",
            RiskLevel.HIGH: "🔴 重要操作需确认:",
            RiskLevel.FORBIDDEN: "🚫 此操作被禁止:",
        }
        parts.append(prefix_map.get(self.risk_level, "") + f" {self.task_description}")
        
        # 计划动作（最多3条）
        if self.planned_actions:
            parts.append("\n计划步骤:")
            for i, action in enumerate(self.planned_actions[:3], 1):
                parts.append(f"  {i}. {action}")
            if len(self.planned_actions) > 3:
                parts.append(f"  ... 共{len(self.planned_actions)}步")
        
        # 受影响项
        if self.affected_items:
            count = len(self.affected_items)
            items_str = ", ".join(str(x) for x in self.affected_items[:5])
            if count > 5:
                items_str += f" 等{count}项"
            parts.append(f"\n涉及: {items_str}")
        
        # 预计时间
        if self.estimated_time_s > 0:
            parts.append(f"\n预计: 约{int(self.estimated_time_s)}秒")
        
        # 结尾提示
        suffix_map = {
            RiskLevel.SAFE: "",
            RiskLevel.LOW: "(如无异议将自动继续)",
            RiskLevel.MEDIUM: "\n回复 '确认' 或 '取消'",
            RiskLevel.HIGH: "\n⚠️ 此操作可能不可逆，请仔细确认",
            RiskLevel.FORBIDDEN: "\n出于安全原因此操作不被允许",
        }
        parts.append(suffix_map.get(self.risk_level, ""))
        
        return "\n".join(parts)


class ConfirmationCenter:
    """
    确认中心
    
    所有需要用户确认的操作都经过这里。
    支持自动超时、批量确认、历史记录。
    """

    def __init__(self):
        self._pending: dict[str, ConfirmationRequest] = {}
        self._history: list[ConfirmationRequest] = []
        
        # 配置
        self.auto_safe_mode = True      # SAFE/LOW级自动通过
        
    async def request_confirmation(
        self,
        task_desc: str,
        actions: list,
        risk_level: RiskLevel | str = "medium",
        affected_items: list | None = None,
        estimated_time: float = 0.0,
        auto_confirm_fn: Callable[[ConfirmationRequest], Awaitable[bool]] | None = None,
    ) -> ConfirmationRequest:
        """
        发起确认请求
        
        Args:
            task_desc: 任务描述
            actions: 计划的动作步骤列表
            risk_level: 风险等级
            affected_items: 受影响的对象列表
            estimated_time: 预计耗时(秒)
            auto_confirm_fn: 自动确认回调（用于非交互模式）
            
        Returns:
            包含结果的ConfirmationRequest
        """
        if isinstance(risk_level, str):
            risk_level = RiskLevel(risk_level.lower())

        req = ConfirmationRequest(
            task_description=task_desc,
            planned_actions=actions,
            risk_level=risk_level,
            affected_items=affected_items or [],
            estimated_time_s=estimated_time,
        )
        
        # SAFE/LOW 级别可配置为自动确认
        defaults = RISK_DEFAULTS.get(risk_level, RISK_DEFAULTS[RiskLevel.MEDIUM])
        
        if self.auto_safe_mode and defaults["auto_confirm"]:
            req.confirmed = True
            req.responded_at = time.time()
            logger.info(f"[Confirm][{risk_level.value}] Auto-confirmed: {task_desc[:60]}")
            return req
        
        # 有自动确认函数（非交互模式）
        if auto_confirm_fn:
            try:
                approved = await auto_confirm_fn(req)
                req.confirmed = approved
                req.denied = not approved
                req.responded_at = time.time()
                return req
            except Exception as e:
                logger.warning(f"Auto-confirm function error: {e}")

        # 需要人工确认 → 加入待确认队列
        self._pending[req.id] = req
        msg = req.to_user_message()
        logger.info(f"[Confirm][{risk_level.value}] Pending: {msg[:100]}")
        
        # TODO: 在GUI模式下这里会阻塞等待用户点击
        # CLI模式下直接返回pending状态，由调用者决定如何处理
        return req

    def respond(self, request_id: str, confirmed: bool, note: str = "") -> bool:
        """响应对户的确认请求"""
        req = self._pending.pop(request_id, None)
        if not req:
            logger.warning(f"[Confirm] Unknown request ID: {request_id}")
            return False
        
        req.confirmed = confirmed
        req.denied = not confirmed
        req.responded_at = time.time()
        req.user_note = note
        
        # 存入历史
        self._history.append(req)
        
        action = "confirmed" if confirmed else "denied"
        logger.info(f"[Confirm] Request '{request_id}' {action}: {note[:50]}")
        return True

    def get_pending_count(self) -> int:
        return len(self._pending)

    def get_all_pending(self) -> list[ConfirmationRequest]:
        return list(self._pending.values())
