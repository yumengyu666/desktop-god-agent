"""
第07卷 - 联网学习系统
不会做就学，会做就沉淀

核心流程：
    任务遇阻 → 问题识别 → 搜索引擎 → 资料筛选 → 步骤提炼 → 沙盒验证 → 执行 → 记忆沉淀
    
触发条件：
- 未知软件/界面
- 流程失效（旧按钮消失）
- 连续失败3次
- 用户明确要求学习

安全边界：
- 禁止自动学习并执行高风险操作（删系统文件、关安全软件等）
- 多源交叉验证防错误信息
"""

from .learning_system import LearningSystem, LearnedProcedure
from .search_agent import SearchAgent
from .procedure_extractor import ProcedureExtractor
from .cache_store import LearningCache

__all__ = [
    "LearningSystem",
    "LearnedProcedure",
    "SearchAgent",
    "ProcedureExtractor", 
    "LearningCache",
]
