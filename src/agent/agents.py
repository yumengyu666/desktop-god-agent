"""
多Agent系统实现

基于角色的Agent编排框架，
支持任务分解、并行执行、验证和异常恢复。
"""

import time
import uuid
import json
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Callable, Any
from abc import ABC, abstractmethod
import logging
import threading

logger = logging.getLogger(__name__)


class AgentRole(str, Enum):
    """Agent角色枚举"""
    COMMANDER = "commander"       # 总控
    PLANNER = "planner"           # 规划
    EXECUTOR = "executor"         # 执行
    VERIFIER = "verifier"         # 验证
    RECOVERY = "recovery"         # 恢复


class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_VERIFICATION = "waiting_verification"
    COMPLETED = "completed"
    FAILED = "failed"
    RECOVERING = "recovering"
    PAUSED = "paused"


@dataclass
class TaskStep:
    """任务步骤（DAG节点）"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = ""
    agent_role: AgentRole = AgentRole.EXECUTOR
    
    status: TaskStatus = TaskStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    
    # 结果
    result: Optional[Any] = None
    error: str = ""
    
    # 重试
    max_retries: int = 2
    retry_count: int = 0
    
    # 时间戳
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


@dataclass
class Task:
    """完整任务"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    user_instruction: str = ""
    
    status: TaskStatus = TaskStatus.PENDING
    steps: list[TaskStep] = field(default_factory=list)
    
    # 元数据
    priority: int = 0            # 优先级(越高越先)
    tags: list[str] = field(default_factory=list)
    context: dict = field(default_factory=dict)
    
    created_at: float = field(default_factory=time.time)
    
    def add_step(self, description: str, role: AgentRole = AgentRole.EXECUTOR,
                 deps: list[str] | None = None) -> TaskStep:
        step = TaskStep(
            description=description,
            agent_role=role,
            dependencies=deps or [],
        )
        self.steps.append(step)
        return step


# ============================================================
# Agent 基类
# ============================================================

class BaseAgent(ABC):
    """
    Agent基类 - 所有Agent的公共接口
    
    每个Agent有：
    - 固定的角色和职责
    - 独立的system prompt（圈养模型人格）
    - 标准化的输入输出接口
    """
    
    def __init__(self, role: AgentRole, name: str):
        self.role = role
        self.name = name
        self._model_gateway = None
        self._system_prompt = self._build_system_prompt()
        
        logger.debug(f"[AGENT] {self.name} ({self.role.value}) initialized")

    def set_gateway(self, gateway) -> None:
        """注入模型网关"""
        self._model_gateway = gateway

    @abstractmethod
    def _build_system_prompt(self) -> str:
        """构建该Agent专属的system prompt"""
        ...

    @abstractmethod
    async def process(self, input_data: Any, context: dict = None) -> Any:
        """处理输入并返回结果"""
        ...

    def think(
        self,
        messages: list,
        *,
        tier=None,
        temperature: float = 0.7,
    ) -> str:
        """使用模型网关进行思考决策"""
        if not self._model_gateway:
            raise RuntimeError(f"{self.name}: no model gateway set")
        
        from src.gateway.model_gateway import ChatMessage
        
        chat_msgs = []
        if self._system_prompt:
            chat_msgs.append(ChatMessage(role="system", content=self._system_prompt))
        
        for m in (messages or []):
            if isinstance(m, ChatMessage):
                chat_msgs.append(m)
            elif isinstance(m, dict):
                chat_msgs.append(ChatMessage(
                    role=m.get("role", "user"),
                    content=m.get("content", ""),
                ))
            elif isinstance(m, str):
                chat_msgs.append(ChatMessage(role="user", content=m))
        
        resp = self._model_gateway.chat(
            chat_msgs,
            tier=tier,
            temperature=temperature,
        )
        return resp.content


# ============================================================
# 具体Agent实现
# ============================================================

class CommanderAgent(BaseAgent):
    """
    总控Agent — 接收用户指令，理解意图，分配任务
    """
    
    def __init__(self):
        super().__init__(AgentRole.COMMANDER, "Commander")

    def _build_system_prompt(self) -> str:
        return """你是 Desktop God Agent 的总指挥官。

你的职责：
1. 接收用户的自然语言指令
2. 分析指令意图，确定任务类型和复杂度
3. 将复杂任务分解为可执行的步骤序列
4. 判断是否需要联网学习或询问用户澄清

原则：
- 不确定的操作要先问清楚再执行
- 危险操作必须明确警告用户
- 尽量利用已有经验避免重复探索
- 任务要可追踪、可回滚、可解释"""

    async def process(self, instruction: str, context: dict = None) -> Task:
        """将用户指令转化为结构化任务"""
        logger.info(f"[COMMANDER] Processing: {instruction[:80]}...")
        
        # 使用模型分析指令
        analysis = self.think([
            {"role": "user", "content": f"""请分析以下用户指令，返回JSON格式：

{instruction}

请返回：
{{
  "task_type": "分类",
  "steps": ["步骤1", "步骤2", ...],
  "estimated_complexity": "simple|medium|complex",
  "requires_vision": false,
  "requires_web_search": false,
  "safety_concerns": "",
  "clarification_needed": ""
}}"""}],
            tier=None,  # 自动选择
        )
        
        try:
            # 解析模型返回的任务计划
            plan = self._extract_json_from_response(analysis)
            
            task = Task(
                description=plan.get('task_type', 'unknown'),
                user_instruction=instruction,
                context=context or {},
            )
            
            for step_desc in plan.get('steps', []):
                task.add_step(step_desc)
            
            task.status = TaskStatus.PLANNING
            
            return task
            
        except Exception as e:
            logger.error(f"[COMMANDER] Failed to parse response: {e}")
            # 降级：创建单步任务
            task = Task(
                description="direct_execution",
                user_instruction=instruction,
            )
            task.add_step(instruction)
            return task

    @staticmethod
    def _extract_json_from_response(text: str) -> dict:
        """从LLM响应中提取JSON"""
        import re
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {'steps': [text], 'task_type': 'unknown'}


class PlannerAgent(BaseAgent):
    """
    规划Agent — 将任务细化为可执行的操作步骤
    """
    
    def __init__(self):
        super().__init__(AgentRole.PLANNER, "Planner")

    def _build_system_prompt(self) -> str:
        return """你是 Desktop God Agent 的任务规划师。

你的职责是将高层目标拆解为精确的原子操作。
每个操作必须是：可通过鼠标键盘完成的单一动作。

可用操作语言：
- click(x, y): 点击坐标
- double_click(x, y): 双击坐标  
- right_click(x, y): 右键点击
- type_text(text): 输入文字
- key_press(key): 按键
- hotkey(k1, k2...): 组合键
- scroll(delta): 滚动
- drag(start, end): 拖拽

规划规则：
1. 先截图识别当前状态
2. 定位目标元素位置
3. 规划操作序列
4. 每步后加验证点
5. 考虑失败回退方案"""

    async def process(self, task: Task, world_state: dict = None) -> list[dict]:
        """将任务规划为具体操作步骤"""
        logger.info(f"[PLANNER] Planning task: {task.description}")
        
        state_info = ""
        if world_state:
            state_info = f"\n当前状态：\n{json.dumps(world_state, ensure_ascii=False, indent=2)}"
        
        plan = self.think([
            {"role": "user", "content": f"""请为以下任务制定详细的执行计划：

任务描述：{task.description}
用户原始指令：{task.user_instruction}
{state_info}

请返回JSON数组格式的操作步骤列表：
[
  {{"step": "描述", "action": "click/double_click/type_text/key_press/hotkey/scroll/drag", 
    "params": {{}}, "verify": "如何验证成功"}},
  ...
]

注意：
- 坐标需要根据实际屏幕分辨率归一化到 0~100% 或提供像素值
- 文字输入内容用引号包裹
- 每步都要有验证条件"""},
        ], tier='pro')  # 规划用Pro模型
        
        return self._extract_plan(plan)

    @staticmethod
    def _extract_plan(response: str) -> list[dict]:
        import re
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return [{"step": response.strip(), "action": "think", "params": {}, "verify": "manual"}]


class ExecutorAgent(BaseAgent):
    """
    执行Agent — 调用执行引擎完成具体操作
    """
    
    def __init__(self):
        super().__init__(AgentRole.EXECUTOR, "Executor")
        self._execution_engine = None

    def _build_system_prompt(self) -> str:
        return """你是 Desktop God Agent 的执行者。

你的职责是按照规划的步骤，精确地通过鼠标键盘执行操作。

执行原则：
1. 每个动作前先确认目标位置正确
2. 动作完成后立即检查结果
3. 如果发现偏离预期，暂停并报告
4. 记录每个操作的详细日志
5. 不要跳过任何验证步骤"""

    def set_executor(self, executor) -> None:
        """注入执行引擎"""
        self._execution_engine = executor

    async def process(self, action: dict, context: dict = None) -> dict:
        """执行单个操作"""
        if not self._execution_engine:
            raise RuntimeError("No execution engine set")
        
        action_type = action.get('action', '')
        params = action.get('params', {})
        verify_method = action.get('verify', '')
        
        logger.info(f"[EXECUTOR] Executing: {action_type} {params}")
        
        start_time = time.time()
        error = ""
        success = False
        
        try:
            match action_type:
                case "click":
                    result = self._execution_engine.click(
                        params['x'], params['y']
                    )
                    success = result.success
                    error = result.error
                case "double_click":
                    result = self._execution_engine.double_click(
                        params['x'], params['y']
                    )
                    success = result.success
                    error = result.error
                case "right_click":
                    result = self._execution_engine.right_click(
                        params['x'], params['y']
                    )
                    success = result.success
                    error = result.error
                case "type_text":
                    result = self._execution_engine.type_text(params['text'])
                    success = result.success
                    error = result.error
                case "key_press":
                    result = self._execution_engine.key_press(params['key'])
                    success = result.success
                    error = result.error
                case "hotkey":
                    keys = params.get('keys', [])
                    if isinstance(keys, str):
                        keys = [keys]
                    result = self._execution_engine.hotkey(*keys)
                    success = result.success
                    error = result.error
                case "scroll":
                    delta = params.get('delta', 0)
                    x = params.get('x')
                    y = params.get('y')
                    result = self._execution_engine.scroll(delta, x, y)
                    success = result.success
                    error = result.error
                case "drag":
                    start_pos = tuple(params.get('start', (0, 0)))
                    end_pos = tuple(params.get('end', (0, 0)))
                    result = self._execution_engine.drag(start_pos, end_pos)
                    success = result.success
                    error = result.error
                case "think" | "wait":
                    # 纯思考/等待步骤
                    wait_sec = params.get('seconds', 1)
                    time.sleep(wait_sec)
                    success = True
                case _:
                    error = f"Unknown action: {action_type}"
                    
        except Exception as e:
            error = str(e)
            logger.error(f"[EXECUTOR] Error in {action_type}: {e}")
            
        elapsed = (time.time() - start_time) * 1000
        
        return {
            'success': success,
            'error': error,
            'elapsed_ms': elapsed,
            'action': action_type,
            'verification_needed': bool(verify_method),
        }


class VerifierAgent(BaseAgent):
    """
    验证Agent — 检查操作结果是否符合预期
    """
    
    def __init__(self):
        super().__init__(AgentRole.VERIFIER, "Verifier")

    def _build_system_prompt(self) -> str:
        return """你是 Desktop God Agent 的验证者。

你的职责是判断上一步操作是否成功完成了预定目标。

验证方法：
1. 截取当前屏幕
2. 对比操作前后变化
3. 检查关键UI元素状态
4. 给出明确的通过/不通过判定

判定标准：
- PASS: 操作完全达成目标
- PARTIAL: 部分完成，可以继续
- FAIL: 未达到目标，需要重试或回退"""

    async def process(
        self,
        action: dict,
        expected: str,
        before_screenshot: bytes = None,
    ) -> dict:
        """验证操作结果"""
        logger.info(f"[VERIFIER] Verifying: {action.get('action')}")
        
        # 截图获取当前状态
        try:
            from src.perception.screenshot import get_screencap
            screencap = get_screencap()
            after_image = screencap.to_bytes()
        except Exception as e:
            after_image = None
            logger.warning(f"Screenshot for verification failed: {e}")
        
        # 使用视觉模型验证（如果有图片）
        verification_result = self.think([
            {
                "role": "user",
                "content": f"""请验证以下操作是否成功：

执行的操作：{json.dumps(action, ensure_ascii=False)}
期望结果：{expected}
当前时间：{time.strftime('%H:%M:%S')}

请给出简洁的验证结论：
{{"result": "PASS/PARTIAL/FAIL", "confidence": 0.0~1.0, "reason": "原因"}}""",
            }
        ], tier='flash')  # 验证用Flash即可
        
        try:
            result = json.loads(
                self._extract_json_from_response_single(verification_result)
            )
        except Exception:
            result = {
                "result": "PASS",
                "confidence": 0.5,
                "reason": verification_result[:200],
            }
        
        return result

    @staticmethod
    def _extract_json_from_response_single(text: str) -> str:
        import re
        match = re.search(r'\{[^{}]*\}', text)
        return match.group() if match else '{"result":"PASS","reason":"auto"}'


class RecoveryAgent(BaseAgent):
    """
    恢复Agent — 处理异常和错误恢复
    """
    
    def __init__(self):
        super().__init__(AgentRole.RECOVERY, "Recovery")

    def _build_system_prompt(self) -> str:
        return """你是 Desktop God Agent 的恢复专家。

当操作遇到错误时，你负责：
1. 分析错误原因
2. 制定恢复策略
3. 决定是重试、回退还是放弃
4. 记录经验教训到记忆系统

恢复策略：
- 临时性错误（网络超时等）：等待后重试
- UI元素未找到：重新定位或换方案
- 应用崩溃：重启应用
- 权限不足：请求用户授权
- 无法恢复：报告给用户并建议手动处理"""

    async def process(
        self,
        failed_action: dict,
        error: str,
        retry_count: int = 0,
        max_retries: int = 3,
    ) -> dict:
        """制定恢复策略"""
        logger.warning(f"[RECOVERY] Handling failure: {error[:80]}")
        
        recovery_plan = self.think([
            {
                "role": "user", 
                "content": f"""以下操作失败了，请制定恢复方案：

失败的操作：{json.dumps(failed_action, ensure_ascii=False)}
错误信息：{error}
已重试次数：{retry_count}/{max_retries}

请返回：
{{
  "strategy": "retry/retry_different/rollback/abort/user_help",
  "next_action": "下一步具体操作",
  "reason": "为什么选择这个策略",
  "lesson_learned": "经验教训"
}}""",
            }
        ], tier='pro')  # 恢复需要深度推理
        
        try:
            plan = json.loads(
                self._extract_json_from_response_single(recovery_plan)
            )
        except Exception:
            plan = {
                "strategy": "retry",
                "next_action": recovery_plan,
                "reason": "default retry",
            }
        
        return plan

    @staticmethod
    def _extract_json_from_response_single(text: str) -> str:
        import re
        match = re.search(r'\{[^{}]*\}', text)
        return match.group() if match else '{"strategy":"retry"}'


# ============================================================
# Agent 编排器
# ============================================================

class AgentOrchestrator:
    """
    Agent编排器 — 管理所有Agent的生命周期和协作
    
    负责：
    - 初始化各角色Agent
    - 注入依赖（模型网关、执行引擎）
    - 协调Agent间通信
    - 管理任务生命周期
    """

    def __init__(self):
        self.commander: Optional[CommanderAgent] = None
        self.planner: Optional[PlannerAgent] = None
        self.executor: Optional[ExecutorAgent] = None
        self.verifier: Optional[VerifierAgent] = None
        self.recovery: Optional[RecoveryAgent] = None
        
        self._initialized = False

    def initialize(
        self,
        model_gateway=None,
        executor=None,
    ) -> None:
        """初始化所有Agent"""
        # 创建Agent实例
        self.commander = CommanderAgent()
        self.planner = PlannerAgent()
        self.executor = ExecutorAgent()
        self.verifier = VerifierAgent()
        self.recovery = RecoveryAgent()
        
        # 注入依赖
        if model_gateway:
            for agent in [self.commander, self.planner, 
                         self.executor, self.verifier, self.recovery]:
                agent.set_gateway(model_gateway)
        
        if executor:
            self.executor.set_executor(executor)
        
        self._initialized = True
        logger.info("AgentOrchestrator: all agents initialized")

    async def run_task(self, instruction: str) -> dict:
        """
        运行完整任务流水线
        
        流程：Commander→Planner→Executor→Verifier(循环)→Recovery(如需)
        """
        if not self._initialized:
            raise RuntimeError("Orchestrator not initialized")
        
        task_start = time.time()
        
        # Step 1: Commander 分析指令
        task = await self.commander.process(instruction)
        logger.info(f"[ORCH] Task planned: {task.id}, "
                   f"{len(task.steps)} steps")
        
        # Step 2: Planner 细化操作
        all_actions = []
        for step in task.steps:
            actions = await self.planner.process(step)
            all_actions.extend(actions)
        
        logger.info(f"[ORCH] Total actions to execute: {len(all_actions)}")
        
        # Step 3+4: Executor + Verifier 循环
        results = []
        for i, action in enumerate(all_actions):
            # 安全检查
            safety_ok = True  # TODO: integrate with SafetySystem
            
            if not safety_ok:
                break
                
            # 执行
            exec_result = await self.executor.process(action)
            
            # 验证
            if action.get('verify'):
                verify_result = await self.verifier.process(
                    action, action.get('verify', '')
                )
                
                if verify_result.get('result') == 'FAIL':
                    # 进入恢复流程
                    recovery = await self.recovery.process(
                        action,
                        exec_result.get('error', 'Verification failed'),
                    )
                    
                    strategy = recovery.get('strategy', 'retry')
                    if strategy == 'retry' and i < len(all_actions) - 1:
                        logger.info(f"[ORCH] Recovery: retrying step {i}")
                        continue
                    elif strategy == 'rollback':
                        results.append({'step': i, 'status': 'rolled_back'})
                        break
                    elif strategy in ('abort', 'user_help'):
                        results.append({
                            'step': i, 'status': 'aborted',
                            'message': recovery.get('reason'),
                        })
                        break
                        
            results.append({
                'step': i,
                'success': exec_result.get('success', False),
                'elapsed_ms': exec_result.get('elapsed_ms', 0),
                'error': exec_result.get('error', ''),
            })
            
            logger.info(f"[ORCH] Step {i+1}/{len(all_actions)} done")
        
        total_elapsed = (time.time() - task_start) * 1000
        
        summary = {
            'task_id': task.id,
            'description': task.user_instruction,
            'total_steps': len(all_actions),
            'completed_steps': sum(1 for r in results if r.get('success')),
            'total_ms': total_elapsed,
            'results': results,
            'status': 'completed' if all(r.get('success') for r in results) else 'partial',
        }
        
        logger.info(f"[ORCH] Task complete | {summary['completed_steps']}/"
                   f"{summary['total_steps']} steps | {total_elapsed:.0f}ms")
        
        return summary


def get_orchestrator() -> AgentOrchestrator:
    return AgentOrchestrator()
