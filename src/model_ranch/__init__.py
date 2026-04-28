"""
第06卷 - 本地模型圈养体系
多专家数字员工训练系统（DeepSeek Flash 多角色版）

核心思想：
- 同一个DeepSeek Flash底座，不同岗位人格、技能偏置、专属记忆池
- 岗前热身机制（10轮对话进入角色）
- 总控调度器拆解任务分配给最合适的工种

工种列表：
- BrowserWorker: 网页操作（登录/搜索/下载/表单）
- FileWorker: 文件管理（整理/归档/重命名/压缩）
- OfficeWorker: 办公软件（Excel/Word/PPT）
- RecoveryWorker: 异常恢复（报错处理/卡死恢复/路径重规划）
- ResearchWorker: 联网搜索（教程提炼/步骤归纳/可信度判断）

架构：
    用户指令 → RanchController(总控) → 任务拆解 → 分配给对应Worker(带专用system prompt)
                                                    ↓
                                            WorkerMetrics(KPI追踪)
                                                    ↓
                                            WarmupEngine(岗前热身)
"""

from .controller import RanchController
from .workers import (
    BrowserWorker,
    FileWorker,
    OfficeWorker,
    RecoveryWorker,
    ResearchWorker,
    WorkerType,
)
from .warmup_engine import WarmupEngine
from .metrics import WorkerMetrics, WorkerKPI

__all__ = [
    "RanchController",
    "BrowserWorker",
    "FileWorker",
    "OfficeWorker",
    "RecoveryWorker",
    "ResearchWorker",
    "WorkerType",
    "WarmupEngine",
    "WorkerMetrics",
    "WorkerKPI",
]
