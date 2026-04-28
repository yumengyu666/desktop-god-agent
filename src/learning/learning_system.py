"""
联网学习系统核心
把"不会做"变成触发学习流程，而不是失败
"""

import asyncio
import json
import logging
import time
import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from pathlib import Path

logger = logging.getLogger("Learning")

# 高风险操作黑名单（禁止自动学习+执行）
FORBIDDEN_ACTIONS = [
    "删除系统文件", "关闭安全软件", "修改账户权限",
    "格式化磁盘", "修改注册表启动项",
    "禁用杀毒", "关闭防火墙",
    "下载执行未知脚本", "修改系统环境变量",
]


@dataclass
class LearnedProcedure:
    """
    学习到的操作流程
    
    一个procedure = 解决某个问题的完整可执行步骤
    支持多方案（A/B/C）按成功率选择
    """
    task_name: str
    source: str = ""                    # 来源URL/描述
    steps: List[str] = field(default_factory=list)
    confidence: float = 0.0             # 信任度 0~1
    success_count: int = 0
    fail_count: int = 0
    last_used: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)
    alternatives: List[Dict] = field(default_factory=list)  # 备选方案
    
    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else self.confidence
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    def is_expired(self, max_age_days: int = 30) -> bool:
        """检查是否过期"""
        age_days = (time.time() - self.created_at) / 86400
        return age_days > max_age_days
    
    def is_high_risk(self) -> bool:
        """检查是否涉及高风险操作"""
        full_text = " ".join(self.steps).lower()
        for forbidden in FORBIDDEN_ACTIONS:
            if forbidden in full_text:
                return True
        return False


@dataclass
class LearningResult:
    """学习结果"""
    success: bool
    procedure: Optional[LearnedProcedure] = None
    raw_findings: List[Dict] = field(default_factory=list)
    error: str = ""
    time_spent_ms: float = 0.0
    sources_checked: int = 0


class LearningSystem:
    """
    联网学习系统主控
    
    与记忆系统和圈养模型联动：
    - 先查记忆（短期→长期），有现成方案直接用
    - 没有则联网学习：搜索→筛选→提炼→验证→沉淀
    - 学习结果写入记忆系统供后续复用
    """

    def __init__(self, gateway=None, memory=None):
        """
        Args:
            gateway: 模型网关实例
            memory: 记忆系统实例（用于查询和沉淀）
        """
        from .search_agent import SearchAgent
        from .procedure_extractor import ProcedureExtractor
        from .cache_store import LearningCache
        
        self.gateway = gateway
        self.memory = memory
        self.searcher = SearchAgent(gateway)
        self.extractor = ProcedureExtractor(gateway)
        self.cache = LearningCache()

        # 统计
        self.stats = {
            "total_learn_requests": 0,
            "cache_hits": 0,
            "new_learnings": 0,
            "learning_failures": 0,
            "avg_learning_time_ms": 0.0,
        }

    # ================================================================
    #  主入口
    # ================================================================

    async def learn(
        self,
        problem: str,
        context: Optional[Dict] = None,
        force_refresh: bool = False,
    ) -> LearningResult:
        """
        学习如何解决一个问题
        
        Args:
            problem: 问题描述（如"这个软件怎么导出PDF"）
            context: 可选上下文（当前屏幕、错误信息等）
            force_refresh: 强制忽略缓存重新搜索
            
        Returns:
            LearningResult包含学到的步骤流程
        """
        start_time = time.time()
        self.stats["total_learn_requests"] += 1
        
        logger.info(f"[Learning] Request: {problem[:80]}")

        # Step 1: 标准化问题表达
        standardized = await self._standardize_problem(problem, context)

        # Step 2: 查缓存/记忆（有现成方案直接返回）
        if not force_refresh:
            cached = self.cache.get(standardized)
            if cached and not cached.is_expired():
                logger.info("[Learning] Cache hit!")
                self.stats["cache_hits"] += 1
                cached.last_used = time.time()
                return LearningResult(
                    success=True,
                    procedure=cached,
                    time_spent_ms=(time.time() - start_time) * 1000,
                )

        # Step 3: 风险检查
        if self._is_high_risk_problem(problem):
            logger.warning(f"[Learning] High-risk problem detected: {problem}")
            return LearningResult(
                success=False,
                error="HIGH_RISK: 此问题涉及高风险操作，需要人工确认",
                time_spent_ms=(time.time() - start_time) * 1000,
            )

        # Step 4: 搜索资料
        search_results = await self.searcher.search(standardized)
        
        if not search_results:
            return LearningResult(
                success=False,
                error="未找到相关资料",
                time_spent_ms=(time.time() - start_time) * 1000,
            )

        # Step 5: 提取步骤流程
        procedure = await self.extractor.extract(
            problem=standardized,
            search_results=search_results,
            context=context,
        )

        elapsed = (time.time() - start_time) * 1000
        
        if procedure and len(procedure.steps) > 0:
            # Step 6: 写入缓存
            self.cache.put(procedure)
            
            # Step 7: 如果有记忆系统，也沉淀进去
            if self.memory:
                try:
                    await self.memory.store_procedure(procedure)
                except Exception as e:
                    logger.warning(f"Failed to store to memory: {e}")

            self.stats["new_learnings"] += 1
            logger.info(
                f"[Learning] Learned {len(procedure)} steps in {elapsed:.0f}ms"
            )
            
            return LearningResult(
                success=True,
                procedure=procedure,
                raw_findings=search_results,
                time_spent_ms=elapsed,
                sources_checked=len(search_results),
            )
        else:
            self.stats["learning_failures"] += 1
            return LearningResult(
                success=False,
                error="未能从搜索结果中提取有效步骤",
                raw_findings=search_results,
                time_spent_ms=elapsed,
                sources_checked=len(search_results),
            )

    # ================================================================
    #  内部方法
    # ================================================================

    async def _standardize_problem(
        self, problem: str, context: Optional[Dict]
    ) -> str:
        """标准化问题表达，便于搜索"""
        parts = [problem]

        # 加入上下文信息
        if context:
            if context.get("app_name"):
                parts.insert(0, f"软件:{context['app_name']}")
            if context.get("error_message"):
                parts.append(f"| 错误:{context['error_message']}")
            if context.get("os_version"):
                parts.append(f"| 系统:{context['os_version']}")

        return " ".join(parts)

    def _is_high_risk_problem(self, problem: str) -> bool:
        lower = problem.lower()
        for forbidden in FORBIDDEN_ACTIONS:
            if forbidden in lower:
                return True
        return False

    def get_stats(self) -> Dict:
        return dict(self.stats)

    def list_cached(self) -> List[Dict]:
        """列出所有已学习的流程"""
        return [p.to_dict() for p in self.cache.list_all()]
