"""
工种定义 - 5个专职数字员工
每个工种 = 固定system prompt + 专属技能偏置 + 独立记忆池 + 统一输出协议

输出协议统一格式：
{
    "goal": "任务目标",
    "next_action": "下一步动作",
    "confidence": 0.92,       # 0~1
    "verify": "验证方式",
    "fallback": "失败备选路径"
}
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import time
import json
import logging

logger = logging.getLogger("ModelRanch.Workers")


class WorkerType(Enum):
    """工种枚举"""
    BROWSER = "browser"
    FILE = "file"
    OFFICE = "office"
    RECOVERY = "recovery"
    RESEARCH = "research"


@dataclass
class WorkerKPI:
    """工种绩效指标"""
    total_tasks: int = 0
    success_count: int = 0
    fail_count: int = 0
    retry_count: int = 0
    user_interrupt_count: int = 0
    total_time_ms: float = 0.0
    avg_confidence: float = 0.0
    # 资源消耗
    api_calls: int = 0
    tokens_used: int = 0
    
    @property
    def success_rate(self) -> float:
        if self.total_tasks == 0:
            return 1.0
        return self.success_count / self.total_tasks
    
    @property
    def avg_time_ms(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.total_time_ms / self.total_tasks
    
    @property
    def interrupt_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.user_interrupt_count / self.total_tasks
    
    def to_dict(self) -> dict:
        return {
            "total_tasks": self.total_tasks,
            "success_rate": f"{self.success_rate:.1%}",
            "fail_count": self.fail_count,
            "retry_count": self.retry_count,
            "interrupt_rate": f"{self.interrupt_rate:.1%}",
            "avg_time_ms": round(self.avg_time_ms, 0),
            "avg_confidence": f"{self.avg_confidence:.2f}",
            "api_calls": self.api_calls,
            "tokens_used": self.tokens_used,
        }


# ============================================================
# 每个工种的 System Prompt 定义（人格固化）
# ============================================================

WORKER_SYSTEM_PROMPTS: Dict[WorkerType, str] = {
    WorkerType.BROWSER: """你是浏览器操作专家（BrowserWorker）。

## 你的职责
- 登录网站、搜索信息、下载文件、填写表单、网页导航
- DOM元素理解与按钮识别
- 多标签页管理
- 验证码检测与处理策略
- 网站登录经验复用

## 你的技能偏置
你特别擅长：识别网页结构、理解按钮功能、管理浏览器状态、处理表单输入。
你不擅长：本地文件操作、复杂推理计算。

## 输出要求
每次回复必须是JSON格式：
{
    "goal": "当前任务目标",
    "next_action": "下一步具体动作（可被执行引擎理解的指令）",
    "confidence": 0.0~1.0的置信度,
    "verify": "如何验证动作成功",
    "fallback": "如果失败该怎么做",
    "thinking": "简短思考过程（可选）"
}

## 行为规则
1. 操作前先描述你要做什么，等确认后再做
2. 遇到验证码立即暂停并通知用户
3. 同一网站登录失败不超过2次就换策略
4. 下载文件后必须确认文件存在
5. 多标签页操作时始终跟踪当前活跃标签""",

    WorkerType.FILE: """你是文件管理专家（FileWorker）。

## 你的职责
- 整理文件、重命名、归档、压缩、上传、同步目录
- 路径理解与命名规则判断
- 批量文件操作
- 目录结构分析
- 文件类型识别与分类

## 你的技能偏置
你特别擅长：理解Windows路径结构、设计批量重命名规则、安全整理文件。
你不擅长：网页操作、复杂文档内容编辑。

## 安全铁律（最高优先级）
1. **禁止误删** - 任何删除操作必须二次确认
2. **先备份再移动** - 大规模文件操作前先记录原始位置
3. **不碰系统目录** - C:\\Windows, C:\\Program Files 等目录只读不写
4. **保留回收站** - 删除走回收站，不走永久删除

## 输出要求
每次回复必须是JSON格式：
{
    "goal": "任务目标",
    "next_action": "具体文件操作指令",
    "confidence": 0.0~1.0,
    "verify": "验证方式（如检查文件是否存在）",
    "fallback": "备选方案",
    "risk_level": "SAFE/LOW/MEDIUM/HIGH",   // 必须标注风险等级
    "affected_files": ["受影响文件列表"]     // 列出所有将操作的文件
}

## 行为规则
1. 整理前先扫描并列出所有文件清单
2. 按类型/日期/大小等维度提出分类方案供用户确认
3. 批量操作每10个文件报告一次进度
4. 发现重复文件时列出但不自动删除
5. 压缩时使用标准格式(zip/7z/rar)，命名含日期戳""",

    WorkerType.OFFICE: """你是办公软件专家（OfficeWorker）。

## 你的职责
- Excel表格处理（公式/图表/数据透视表/格式化）
- Word文档编辑（排版/模板/邮件合并）
- PPT幻灯片制作（布局/动画/图表）
- 报表生成与导出
- 日报/周报自动化模板

## 你的技能偏置
你特别擅长：Excel公式编写、表格美化、报表模板应用、数据可视化。
你不擅长：系统管理、网络操作、编程开发。

## 输出要求
每次回复必须是JSON格式：
{
    "goal": "任务目标",
    "next_action": "具体办公软件操作步骤",
    "confidence": 0.0~1.0,
    "verify": "如何验证结果正确",
    "fallback": "备选方案",
    "file_format": "xlsx/docx/pptx",      // 使用的文件格式
    "estimated_rows": 100                  // 预估影响的数据量
}

## 行为规则
1. 打开文件前先确认文件存在且未被锁定
2. 大量数据操作前建议用户备份原文件
3. 公式使用前先在少量单元格测试
4. 图表标题和轴标签必须有明确含义
5. 导出的文件名包含日期和用途说明""",

    WorkerType.RECOVERY: """你是异常恢复专家（RecoveryWorker）。

## 你的职责
- 报错分析与处理
- 应用卡死恢复
- 任务失败后的路径重规划
- 失败复盘与经验沉淀
- 系统异常诊断

## 你的技能偏置
你特别擅长：错误信息解读、根因分析、最小代价修复方案、冷静决策。
你不擅长：创造性工作、日常效率操作。

## 核心原则
1. **最小代价修复** - 能重启解决的不重装，能跳过的不回滚
2. **先诊断再动手** - 不盲目重试，先搞清楚为什么失败
3. **保护现场** - 失败时的屏幕截图/日志都要保留
4. **禁止盲目重试超过3次** - 同一方法连续失败3次必须换策略

## 输出要求
每次回复必须是JSON格式：
{
    "goal": "恢复目标（让什么恢复正常）",
    "root_cause": "分析的失败原因",
    "next_action": "恢复动作",
    "confidence": 0.0~1.0,
    "verify": "如何确认已恢复",
    "fallback": "如果此方案也失败的下一方案",
    "retry_count": 0,          // 当前是第几次尝试
    "max_retries": 3           // 最大重试次数
}

## 行为规则
1. 收到恢复请求时先获取当前屏幕截图和最近日志
2. 分析错误类型：用户错误/系统错误/网络错误/权限错误
3. 给出修复方案的风险评估
4. 修复后运行基本验证确保问题确实解决
5. 将成功/失败经验写入恢复知识库""",

    WorkerType.RESEARCH: """你是搜索研究专家（ResearchWorker）。

## 你的职责
- 联网搜索信息
- 教程提炼与步骤归纳
- 信息可信度判断
- 多源交叉验证
- 技术资料整理

## 你的技能偏置
你特别擅长：精准搜索关键词构建、信息质量评估、从长文提炼要点、多源对比。
你不擅长：实际操作执行、实时交互。

## 信息质量评分标准（满分10分）
- 官方文档/帮助中心：+3分
- 有截图/视频演示：+2分
- 发布时间近1年：+2分
- 步骤完整可执行：+2分
- 来源权威（知名技术社区）：+1分
- 含广告/推广内容：-2分
- 内容过时（>3年）：-2分

## 输出要求
每次回复必须是JSON格式：
{
    "goal": "研究目标",
    "search_query": "使用的搜索词",
    "findings": [
        {
            "title": "结果标题",
            "source": "来源URL",
            "relevance_score": 8.5,     // 相关性评分 0~10
            "credibility_score": 7.0,   // 可信度评分 0~10
            "key_points": ["要点1", "要点2"],
            "caveats": ["注意事项"]
        }
    ],
    "recommended_action": "基于研究结果推荐的行动",
    "confidence": 0.0~1.0,
    "need_more_info": false   // 是否需要更多信息
}

## 行为规则
1. 至少搜索2-3个不同来源进行交叉验证
2. 区分事实信息和观点意见
3. 注明信息的时效性
4. 对不确定的信息明确标出"待验证"
5. 提供原文链接供用户查阅""",
}


class BaseWorker:
    """
    数字员工基类
    每个工种共享同一套生命周期和接口
    """
    
    def __init__(self, worker_type: WorkerType):
        self.worker_type = worker_type
        self.name = worker_type.value
        self.system_prompt = WORKER_SYSTEM_PROMPTS[worker_type]
        
        # 专属记忆池（按工种隔离）
        self.memory_pool: List[Dict] = []
        self.max_memory_pool = 200
        
        # KPI追踪
        self.kpi = WorkerKPI()
        
        # 状态
        self.state = "cold"  # cold -> warming -> ready -> working -> idle -> recycled
        self.warmup_progress = 0  # 0~10
        self.last_active_time: float = 0.0
        
        # 并发控制
        self.busy = False
        self.current_task_id: Optional[str] = None
        
        logger.info(f"[{self.name}] Worker initialized")
    
    async def warmup(self, gateway) -> bool:
        """
        岗前热身 - 发送10轮训练对话进入角色
        目的：稳定输出格式、刷新常用知识、降低首轮失误
        """
        if self.state == "ready":
            logger.info(f"[{self.name}] Already warmed up, skipping")
            return True
        
        logger.info(f"[{self.name}] Starting warmup (10 rounds)...")
        self.state = "warming"
        
        warmup_cases = self._get_warmup_cases()
        
        for i, case in enumerate(warmup_cases[:10]):
            try:
                start = time.time()
                response = await gateway.chat(
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": case},
                    ],
                    model="flash",  # 全部用DeepSeek Flash
                    temperature=0.3,
                )
                elapsed = (time.time() - start) * 1000
                
                self.warmup_progress = i + 1
                self.kpi.api_calls += 1
                
                logger.debug(
                    f"[{self.name}] Warmup {i+1}/10 OK ({elapsed:.0f}ms) "
                    f"- response length: {len(response)}"
                )
                
                # 短暂间隔避免限流
                await asyncio.sleep(0.2)
                
            except Exception as e:
                logger.warning(f"[{self.name}] Warmup {i+1}/10 failed: {e}")
                continue
        
        self.state = "ready"
        self.last_active_time = time.time()
        logger.info(f"[{self.name}] Warmup complete, ready for work")
        return True
    
    def _get_warmup_cases(self) -> List[str]:
        """返回该工种的岗前热身案例"""
        raise NotImplementedError
    
    async def execute(
        self,
        task: str,
        context: Optional[Dict] = None,
        gateway=None,
    ) -> Dict:
        """
        执行任务 - 核心方法
        
        Args:
            task: 用户指令
            context: 上下文（屏幕截图、UIA树、历史记忆等）
            gateway: 模型网关实例
            
        Returns:
            统一JSON输出协议
        """
        if not gateway:
            raise ValueError(f"[{self.name}] Gateway required")
        
        start_time = time.time()
        self.busy = True
        self.state = "working"
        self.kpi.total_tasks += 1
        
        try:
            # 构建带上下文的prompt
            full_prompt = self._build_task_prompt(task, context)
            
            # 调用模型
            raw_response = await gateway.chat(
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": full_prompt},
                ],
                model="flash",
                temperature=0.4,
                max_tokens=2048,
            )
            
            self.kpi.api_calls += 1
            
            # 解析JSON响应
            result = self._parse_response(raw_response)
            
            # 记录到专属记忆池
            self._record_to_memory(task, result)
            
            # 更新KPI
            elapsed = (time.time() - start_time) * 1000
            self.kpi.total_time_ms += elapsed
            self.kpi.avg_confidence = (
                (self.kpi.avg_confidence * (self.kpi.total_tasks - 1) + 
                 result.get("confidence", 0.5)) / self.kpi.total_tasks
            )
            
            self.kpi.success_count += 1
            
            logger.info(
                f"[{self.name}] Task done in {elapsed:.0f}ms, "
                f"conf={result.get('confidence', 0):.2f}"
            )
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"[{self.name}] JSON parse error: {e}")
            self.kpi.fail_count += 1
            return {
                "goal": task,
                "next_action": "wait_for_user_input",
                "confidence": 0.0,
                "verify": "none",
                "fallback": "ask_user_for_help",
                "error": f"Response parsing failed: {e}",
            }
        except Exception as e:
            logger.error(f"[{self.name}] Task failed: {e}")
            self.kpi.fail_count += 1
            return {
                "goal": task,
                "next_action": "report_error",
                "confidence": 0.0,
                "verify": "none",
                "fallback": "handover_to_recovery_worker",
                "error": str(e),
            }
        finally:
            self.busy = False
            self.state = "idle"
            self.last_active_time = time.time()
    
    def _build_task_prompt(self, task: str, context: Optional[Dict]) -> str:
        """构建完整的任务提示"""
        parts = [task]
        
        if context:
            # 加入相关上下文
            if context.get("screen_text"):
                parts.append(f"\n\n当前屏幕文字:\n{context['screen_text'][:500]}")
            if context.get("uia_tree"):
                parts.append(f"\n\n界面元素:\n{context['uia_tree'][:300]}")
            if context.get("relevant_memories"):
                mem_text = "\n".join(
                    f"- {m['summary']}" for m in context["relevant_memories"][:5]
                )
                parts.append(f"\n\n相关经验:\n{mem_text}")
            if context.get("error_message"):
                parts.append(f"\n\n错误信息:\n{context['error_message']}")
        
        return "\n".join(parts)
    
    def _parse_response(self, raw: str) -> Dict:
        """解析模型的JSON响应，容错处理"""
        # 尝试直接解析
        try:
            return json.loads(raw.strip())
        except json.JSONDecodeError:
            pass
        
        # 尝试提取markdown中的JSON块
        import re
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass
        
        # 尝试找到最外层{}对
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                pass
        
        # 全部失败，包装成通用响应
        return {
            "goal": "unknown",
            "next_action": "interpret_and_execute",
            "confidence": 0.6,
            "verify": "visual_check",
            "fallback": "ask_user",
            "raw_response": raw[:500],
        }
    
    def _record_to_memory(self, task: str, result: Dict):
        """记录任务到专属记忆池"""
        entry = {
            "timestamp": time.time(),
            "task": task[:200],
            "action": result.get("next_action", "")[:200],
            "success": result.get("confidence", 0) > 0.5,
            "confidence": result.get("confidence", 0),
        }
        self.memory_pool.append(entry)
        
        # 保持记忆池大小
        if len(self.memory_pool) > self.max_memory_pool:
            self.memory_pool = self.memory_pool[-self.max_memory_pool:]
    
    def get_relevant_memories(self, query: str, top_k: int = 5) -> List[Dict]:
        """从记忆池检索相关经验（简单关键词匹配）"""
        query_lower = query.lower()
        scored = []
        
        for mem in self.memory_pool:
            score = 0
            task_lower = mem["task"].lower()
            
            # 关键词匹配
            for word in query_lower.split():
                if word in task_lower:
                    score += 1
            
            # 成功的经验加分
            if mem["success"]:
                score += 0.5
            
            # 近期经验加分
            age = time.time() - mem["timestamp"]
            if age < 3600:  # 1小时内
                score += 0.3
            
            if score > 0:
                scored.append((score, mem))
        
        # 按分数排序取top_k
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:top_k]]
    
    def idle_timeout_check(self, max_idle_seconds: float = 300.0) -> bool:
        """检查是否超时空闲，适合回收"""
        if self.state in ("cold", "recycled"):
            return False
        if self.busy:
            return False
        idle = time.time() - self.last_active_time
        return idle > max_idle_seconds
    
    def recycle(self):
        """回收工种实例"""
        self.state = "recycled"
        self.memory_pool.clear()
        logger.info(f"[{self.name}] Recycled")


# ============================================================
# 5个具体工种实现
# ============================================================

class BrowserWorker(BaseWorker):
    """浏览器操作专家"""
    
    def __init__(self):
        super().__init__(WorkerType.BROWSER)
        self.name = "BrowserWorker"
        # 浏览器工专属扩展
        self.known_sites: Dict[str, Dict] = {}  # site_url -> login_info/form_patterns
        self.tab_tracker: Dict[str, str] = {}  # tab_id -> url
    
    def _get_warmup_cases(self) -> List[str]:
        return [
            "我需要打开Chrome浏览器并访问baidu.com",
            "帮我分析这个网页的结构，找出登录按钮在哪里",
            "我需要在一个表单中填写姓名和邮箱然后提交",
            "页面加载很慢，我应该怎么判断它是否还在加载？",
            "下载按钮点击后没有反应，可能的原因有哪些？",
            "我需要同时管理多个标签页，如何在它们之间切换？",
            "遇到了一个弹窗广告，应该如何关闭它？",
            "页面有滚动条，但我要找的内容可能在下方，怎么办？",
            "文件下载完成后，如何确认文件已经保存到正确的位置？",
            "遇到验证码了，我应该怎么做？",
        ]


class FileWorker(BaseWorker):
    """文件管理专家"""
    
    def __init__(self):
        super().__init__(WorkerType.FILE)
        self.name = "FileWorker"
        # 文件工专属扩展
        self.known_directories: Dict[str, str] = {}  # alias -> path
        self.naming_rules: Dict[str, str] = {}  # pattern -> template
    
    def _get_warmup_cases(self) -> List[str]:
        return [
            "桌面上有50个杂乱文件，请帮我想想怎么分类整理",
            "我有一批图片文件需要按日期重命名，格式应该是怎样的？",
            "需要把一个文件夹压缩成zip，应该注意什么？",
            "用户误删了一个重要文件，有没有办法恢复？（不要真的去删）",
            "如何快速找出一个文件夹里最大的10个文件？",
            "一批PDF文件的命名很不规范，需要统一改成'日期_标题'格式",
            "需要把下载文件夹里的临时文件清理掉，哪些可以安全删除？",
            "如何把分散在不同文件夹的同类型文件归拢到一个地方？",
            "文件夹里有重复文件，如何识别出来？",
            "需要给一批文件加上统一的日期前缀，批量操作怎么做？",
        ]


class OfficeWorker(BaseWorker):
    """办公软件专家"""
    
    def __init__(self):
        super().__init__(WorkerType.OFFICE)
        self.name = "OfficeWorker"
        # Office工专属扩展
        self.excel_templates: Dict[str, str] = {}
        self.report_formats: Dict[str, Dict] = {}
    
    def _get_warmup_cases(self) -> List[str]:
        return [
            "打开一个Excel文件，帮我把A列的数据求和放到最后一行",
            "需要在Excel中创建一个数据透视表，数据范围是A1:D100",
            "Word文档中需要插入一个目录，应该怎么做？",
            "PPT中要把一组数据做成柱状图，数据如下...",
            "日报模板应该包含哪些字段？帮我设计一个Excel日报模板",
            "Excel中有一些重复数据需要去重，怎么做最快？",
            "Word中需要对全文进行统一的字体和段落格式设置",
            "需要在Excel中用VLOOKUP函数关联两个表的数据",
            "PPT的幻灯片母版如何修改才能应用到所有页面？",
            "一份周报需要汇总多个人的日报数据，如何高效完成？",
        ]


class RecoveryWorker(BaseWorker):
    """异常恢复专家"""
    
    def __init__(self):
        super().__init__(WorkerType.RECOVERY)
        self.name = "RecoveryWorker"
        # 恢复工专属扩展
        self.recovery_kb: List[Dict] = []  # 经验知识库
        self.common_errors: Dict[str, str] = {}  # error_pattern -> solution
    
    def _get_warmup_cases(self) -> List[str]:
        return [
            "应用程序显示'未响应'，可能的原因和解决方案是什么？",
            "文件操作时报'文件被占用无法访问'，该怎么处理？",
            "网络连接突然中断，正在进行的下载会怎样？",
            "点击按钮后没有任何反应，排查思路是什么？",
            "程序崩溃了，如何获取有用的错误信息来分析原因？",
            "磁盘空间不足导致操作失败，紧急释放空间的方法？",
            "权限不足的错误，如何在不降低安全性的前提下解决？",
            "一个操作执行了很久没返回，应该等多久才判定超时？",
            "之前的脚本今天突然跑不动了，环境可能发生了什么变化？",
            "用户打断了正在执行的任务，如何安全地中断并恢复？",
        ]


class ResearchWorker(BaseWorker):
    """搜索研究专家"""
    
    def __init__(self):
        super().__init__(WorkerType.RESEARCH)
        self.name = "ResearchWorker"
        # 搜索工专属扩展
        self.search_cache: Dict[str, Dict] = {}  # query_hash -> cached_result
        self.trusted_sources: List[str] = []     # 高信誉来源列表
    
    def _get_warmup_cases(self) -> List[str]:
        return [
            "用户问'Python怎么读取Excel文件'，请构建最佳搜索关键词",
            "'如何在Windows上配置环境变量'这个问题的搜索结果如何评价？",
            "同一个技术问题有3个不同答案，如何判断哪个最可靠？",
            "一篇教程发布于2019年，现在还适用吗？如何判断？",
            "搜索结果中混入了广告内容，如何识别和过滤？",
            "用户的问题比较模糊（'我的电脑好慢'），如何细化搜索方向？",
            "找到了两个互相矛盾的解决方案，交叉验证的方法？",
            "官方文档和社区教程冲突时，应该以哪个为准？",
            "某个问题的中文搜索结果质量不高，是否应该换英文搜？",
            "搜索到的信息部分过时了，如何提取仍然有效的部分？",
        ]
