"""
第12卷 - 产品交互系统（Desktop God Agent 的用户界面层）
让用户真正愿意每天使用的交互设计

五层架构：
┌─────────────────────┐
│ 输入层（自然语言/快捷指令/拖拽/指向）│
├─────────────────────┤
│ 反馈层（执行中状态/进度/双鼠标可视化）│
├─────────────────────┤
│ 控制层（暂停/停止/接管/加速）       │
├─────────────────────┤
│ 结果层（结构化展示/失败诊断/成长提示）│
├─────────────────────┤
│ 成长层（记忆学习/模板/历史/信任感）  │
└─────────────────────┘

核心原则：
- 清晰: 用户始终知道AI在干什么
- 可信: 能随时打断，结果可验证
- 低打扰: 高频小事静默，高风险才确认
- 高效率: 减少不必要的确认步骤
"""

from .command_input import CommandInput
from .overlay_panel import OverlayPanel
from .task_feedback import TaskFeedback
from .confirmation_center import ConfirmationCenter
from .result_cards import ResultCards
from .templates import TemplateManager
from .task_history import TaskHistoryCenter

__all__ = [
    "CommandInput",
    "OverlayPanel",
    "TaskFeedback", 
    "ConfirmationCenter",
    "ResultCards",
    "TemplateManager",
    "TaskHistoryCenter",
]
