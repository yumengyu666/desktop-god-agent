"""
总控调度器 - 圈养体系的大脑
任务拆解 → 工种分配 → 并发编排 → 资源控制
"""

import asyncio
import logging
import time
import json
import re
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from collections import deque

from .workers import (
    BaseWorker,
    WorkerType,
    BrowserWorker, FileWorker, OfficeWorker,
    RecoveryWorker, ResearchWorker,
    Task as WorkerTask,
)

logger = logging.getLogger("Ranch.Controller")


@dataclass
class SubTask:
    """子任务单元"""
    id: str
    description: str
    worker_type: Optional[WorkerType] = None
    priority: int = 5              # 1~10
    context: Optional[Dict] = None
    depends_on: List[str] = field(default_factory=list)  # 依赖的task_id
    status: str = "pending"
    result: Optional[Dict] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    retries: int = 0


@dataclass
class ResourceQuota:
    """资源配额"""
    max_concurrent: int = 3
    cpu_limit_percent: float = 70.0
    idle_timeout_s: float = 300.0
    queue_max: int = 20


class RanchController:
    """
    圈养体系总控调度器
    
    用户指令进来后：
    1. 分析指令复杂度（单任务/多步骤/多工种协作）
    2. 拆解为子任务
    3. 分配给对应Worker（带专用system prompt的DeepSeek Flash）
    4. 并发执行有依赖关系的任务
    5. 汇总结果返回
    """

    # 关键词→工种自动映射
    KEYWORD_MAP: Dict[WorkerType, List[str]] = {
        WorkerType.BROWSER: [
            "打开", "访问", "浏览", "网页", "网站", "登录", "搜索", "下载",
            "点击", "链接", "url", "浏览器", "chrome", "edge", "标签页",
            "表单", "提交", "验证码", "邮箱", "上传", "baidu", "google",
        ],
        WorkerType.FILE: [
            "文件", "文件夹", "目录", "整理", "归档", "重命名", "删除",
            "移动", "复制", "压缩", "桌面", "下载文件夹", "文档", "图片",
            "视频", "批量", "分类", "清理", "zip", "rar",
        ],
        WorkerType.OFFICE: [
            "excel", "word", "ppt", "表格", "文档", "幻灯片", "报表",
            "日报", "周报", "公式", "图表", "数据透视", "模板",
            "格式", "排版", "邮件合并",
        ],
        WorkerType.RECOVERY: [
            "错误", "失败", "崩溃", "卡死", "未响应", "恢复", "修复",
            "报错", "异常", "重试", "出问题", "打不开", "找不到",
            "超时", "不行了",
        ],
        WorkerType.RESEARCH: [
            "搜索", "查找", "怎么", "如何", "教程", "方法", "学习",
            "了解", "研究", "查一下", "什么意思", "为什么",
        ],
    }

    def __init__(self, gateway=None, quota: Optional[ResourceQuota] = None):
        self.gateway = gateway
        self.quota = quota or ResourceQuota()

        # 工种实例池
        self._workers: Dict[WorkerType, BaseWorker] = {}
        
        # 任务管理
        self._pending: deque = deque()
        self._running: Dict[str, SubTask] = {}
        self._completed: Dict[str, SubTask] = {}
        self._task_counter = 0
        
        # 统计
        self.stats = {
            "total_dispatched": 0,
            "total_completed": 0,
            "total_failed": 0,
            "worker_usage": {wt.value: 0 for wt in WorkerType},
        }

    async def initialize(self):
        """初始化所有工种并岗前热身"""
        logger.info("Initializing worker pool...")
        
        classes = {
            WorkerType.BROWSER: BrowserWorker,
            WorkerType.FILE: FileWorker,
            WorkerType.OFFICE: OfficeWorker,
            WorkerType.RECOVERY: RecoveryWorker,
            WorkerType.RESEARCH: ResearchWorker,
        }
        
        for wtype, wcls in classes.items():
            worker = wcls()
            self._workers[wtype] = worker
            
            if self.gateway:
                try:
                    await worker.warmup(self.gateway)
                    logger.info(f"  [{wtype.value}] warmed up ✓")
                except Exception as e:
                    logger.warning(f"  [{wtype.value}] warmup failed: {e}")
    
    # ================================================================
    #  核心入口
    # ================================================================

    async def dispatch(self, instruction: str, context: Optional[Dict] = None) -> Dict:
        """
        分发用户指令
        
        Args:
            instruction: 自然语言指令
            context: 可选上下文
            
        Returns:
            统一结果字典
        """
        start = time.time()
        self.stats["total_dispatched"] += 1
        logger.info(f"Dispatch: {instruction[:100]}")

        # Step 1: 拆解任务
        sub_tasks = self._decompose(instruction)
        
        if len(sub_tasks) == 1:
            # 单任务直接执行
            result = await self._execute_single(sub_tasks[0], context)
        else:
            # 多任务编排
            result = await self._execute_orchestrated(sub_tasks, context, instruction)

        elapsed = (time.time() - start) * 1000
        result["_dispatch_time_ms"] = round(elapsed, 0)
        result["_sub_task_count"] = len(sub_tasks)

        return result

    # ================================================================
    #  任务拆解
    # ================================================================

    def _decompose(self, instruction: str) -> List[SubTask]:
        """
        将自然语言指令拆解为子任务
        
        策略：
        1. 检测是否包含多个动作（然后、之后、并且、同时）
        2. 检测是否需要多个工种协作
        3. 否则作为单任务处理
        """
        tasks = []
        lower_instr = instruction.lower()

        # 多任务检测关键词
        multi_task_markers = [
            ("然后", 0.8), ("之后", 0.8), ("接着", 0.7), 
            ("并且", 0.6), ("同时", 0.9), ("再", 0.5),
            ("然后发", 0.9), ("并整理", 0.85),
            ("，并", 0.7), ("，然后", 0.85),
        ]

        is_multi = False
        for marker, conf in multi_task_markers:
            if marker in instruction:
                is_multi = True
                break

        if not is_multi:
            # 单任务
            wt = self._classify_worker(instruction)
            tasks.append(SubTask(
                id=f"task_{self._new_id()}",
                description=instruction.strip(),
                worker_type=wt,
            ))
            return tasks

        # 多任务：按标记拆分
        # 先用最强标记分割
        parts = re.split(r'(?:然后|之后|接着|并|同时)', instruction)
        parts = [p.strip() for p in parts if p.strip()]

        prev_id = None
        for part in parts:
            wt = self._classify_worker(part)
            task = SubTask(
                id=f"task_{self._new_id()}",
                description=part,
                worker_type=wt,
            )
            if prev_id:
                task.depends_on = [prev_id]
            prev_id = task.id
            tasks.append(task)

        return tasks

    def _classify_worker(self, text: str) -> WorkerType:
        """根据文本内容分类到最合适的工种"""
        lower = text.lower()
        scores: Dict[WorkerType, float] = {wt: 0.0 for wt in WorkerType}

        for wt, keywords in self.KEYWORD_MAP.items():
            for kw in keywords:
                if kw in lower:
                    scores[wt] += 1.0

        # 找最高分
        best_wt = max(scores, key=scores.get)
        if scores[best_wt] > 0:
            return best_wt

        # 默认用搜索工分析后再分配
        return WorkerType.RESEARCH

    # ================================================================
    #  任务执行
    # ================================================================

    async def _execute_single(self, task: SubTask, context: Optional[Dict]) -> Dict:
        """执行单个子任务"""
        task.status = "running"
        task.started_at = time.time()

        worker = self._get_worker(task.worker_type)
        if not worker:
            return {"error": f"No worker for type {task.worker_type}", "status": "failed"}

        try:
            result = await worker.execute(task.description, context, self.gateway)
            task.result = result
            task.status = "done"
            task.completed_at = time.time()
            self.stats["total_completed"] += 1
            self.stats["worker_usage"][task.worker_type.value] += 1
            return result
        except Exception as e:
            task.status = "failed"
            self.stats["total_failed"] += 1
            logger.error(f"Task {task.id} failed: {e}")
            return {"error": str(e), "status": "failed"}

    async def _execute_orchestrated(
        self, tasks: List[SubTask], context: Optional[Dict], original: str
    ) -> Dict:
        """编排执行多个子任务（处理依赖关系）"""
        results_map: Dict[str, Dict] = {}
        completed_ids: set = set()
        
        while len(completed_ids) < len(tasks):
            # 找出所有可执行的（依赖已满足）
            ready = [
                t for t in tasks 
                if t.status == "pending" and all(d in completed_ids for d in t.depends_on)
            ]

            if not ready:
                # 检查是否有卡死的任务
                pending = [t for t in tasks if t.status == "pending"]
                if pending and not any(t.status == "running" for t in tasks):
                    # 所有剩余任务都是pending但没有在运行的=循环依赖或异常
                    break
                await asyncio.sleep(0.1)
                continue

            # 并行执行就绪任务（受并发限制）
            running_count = sum(1 for t in tasks if t.status == "running")
            available_slots = self.quota.max_concurrent - running_count
            batch = ready[:max(1, available_slots)]

            # 并发执行这批任务
            coros = [self._execute_single(t, context) for t in batch]
            batch_results = await asyncio.gather(*coros, return_exceptions=True)

            for task, result in zip(batch, batch_results):
                results_map[task.id] = result if isinstance(result, dict) else {"error": str(result)}
                completed_ids.add(task.id)

        # 汇总结果
        return {
            "original_instruction": original,
            "sub_results": results_map,
            "status": "done" if all(t.status == "done" for t in tasks) else "partial",
            "summary": self._summarize_results(tasks, results_map),
        }

    def _summarize_results(self, tasks: List[SubTask], results: Dict[str, Dict]) -> str:
        """生成多任务的摘要描述"""
        lines = []
        for t in tasks:
            r = results.get(t.id, {})
            status = r.get("status", "unknown")
            action = r.get("next_action", r.get("error", ""))
            lines.append(f"  • [{t.description[:40]}] → {status}: {action[:60]}")
        return "\n".join(lines)

    # ================================================================
    #  辅助
    # ================================================================

    def _get_worker(self, wt: WorkerType) -> Optional[BaseWorker]:
        return self._workers.get(wt)

    def _new_id(self) -> int:
        self._task_counter += 1
        return self._task_counter

    def get_status(self) -> Dict:
        """获取控制器状态面板信息"""
        return {
            "workers": {
                wt.value: {
                    "state": w.state,
                    "busy": w.busy,
                    "kpi": w.kpi.to_dict(),
                }
                for wt, w in self._workers.items()
            },
            "stats": self.stats,
            "quota": asdict(self.quota),
        }

    async def shutdown(self):
        """优雅关闭所有工种"""
        for wt, worker in self._workers.items():
            worker.recycle()
        logger.info("All workers recycled")
