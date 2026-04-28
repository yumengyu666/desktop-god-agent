"""
岗前热身引擎
系统启动时，不直接开工，先做10轮岗位训练对话进入角色

目的：
- 进入角色人格
- 稳定输出格式（JSON协议）
- 刷新常用知识
- 降低首轮失误
"""

import asyncio
import logging
import time
from typing import List, Callable, Awaitable

logger = logging.getLogger("Ranch.Warmup")


class WarmupEngine:
    """
    岗前热身引擎
    
    对每个Worker发送10个典型案例对话，
    使模型稳定进入该角色的system prompt语境。
    """

    def __init__(self, call_model_func: Callable[[str, str], Awaitable[str]]):
        """
        Args:
            call_model_func: 异步调用模型的函数(user_msg, system_prompt) -> response
        """
        self.call_model = call_model_func

    async def run_warmup(
        self,
        system_prompt: str,
        cases: List[str],
        worker_name: str = "",
        rounds: int = 10,
    ) -> dict:
        """
        执行岗前热身
        
        Args:
            system_prompt: 该工种的system prompt
            cases: 热身案例列表
            worker_name: 工种名称（用于日志）
            rounds: 最大轮次
            
        Returns:
            热身统计
        """
        start_time = time.time()
        stats = {
            "total": min(rounds, len(cases)),
            "success": 0,
            "fail": 0,
            "total_time_ms": 0,
            "errors": [],
        }

        logger.info(f"[{worker_name}] Warmup starting ({stats['total']} rounds)...")

        for i, case in enumerate(cases[:rounds]):
            try:
                round_start = time.time()
                response = await self.call_model(case, system_prompt)
                elapsed = (time.time() - round_start) * 1000

                stats["success"] += 1
                stats["total_time_ms"] += elapsed

                # 验证响应是否包含JSON（说明格式稳定了）
                has_json = "{" in response and "}" in response
                
                logger.debug(
                    f"[{worker_name}] Round {i+1}/{stats['total']} OK "
                    f"({elapsed:.0f}ms, json={has_json})"
                )

                # 间隔避免限流
                await asyncio.sleep(0.15)

            except Exception as e:
                stats["fail"] += 1
                stats["errors"].append(f"Round {i+1}: {e}")
                logger.warning(f"[{worker_name}] Round {i+1} failed: {e}")

        total_elapsed = (time.time() - start_time) * 1000
        stats["total_time_ms"] = total_elapsed
        stats["success_rate"] = (
            f"{stats['success'] / stats['total'] * 100:.0f}%"
            if stats["total"] > 0 else "N/A"
        )

        logger.info(
            f"[{worker_name}] Warmup complete | "
            f"{stats['success']}/{stats['total']} success | "
            f"{total_elapsed:.0f}ms total"
        )
        
        return stats
