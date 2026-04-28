"""
步骤提炼器 - 从搜索结果中提取可执行的步骤
这是联网学习的核心环节：把网页内容变成结构化动作序列
"""

import json
import logging
import re
import time
from typing import List, Dict, Optional

logger = logging.getLogger("Learning.Extractor")


class ProcedureExtractor:
    """
    步骤提炼器
    
    输入：搜索结果的文本内容（网页/教程/文档）
    输出：LearnedProcedure（结构化步骤列表）
    
    核心能力：
    1. 从长文中提取有序步骤
    2. 把模糊描述转换为具体动作（鼠标/键盘操作）
    3. 标注每步的验证方式和失败备选
    """

    ACTION_PATTERNS = [
        # 点击类
        r"(点击|单击|双击|右键|选择|勾选)(.+?)(按钮|选项|菜单|链接|标签|复选框|图标)",
        r"click\s+(?:on\s+)?(?:the\s+)?(.+?)(?:button|link|tab|menu|icon|option)",
        # 输入类
        r"(输入|填写|键入|敲入|输入框)(.+?)(文字|文本|内容|名称|地址|密码)",
        r"(?:type|enter)\s+(.+?)(?:into|in\s+the?\s+(?:input|field|box))",
        # 导航类  
        r"(打开|进入|访问|导航到|切换到|转到)(.+?)(页面|窗口|目录|文件夹|标签)",
        r"(?:open|go\s+to|navigate|switch\s+to)\s+(.+?)",
        # 等待类
        r"(等待|等待.*?(加载|完成|就绪))",
        r"(?:wait|等待).+?(?:to\s+)?(?:load|complete|finish)",
        # 快捷键类
        r"按(.+?)(快捷键|组合键)",
        r"press\s+(.+?)(?:shortcut|hotkey|key\s+combination)",
    ]

    def __init__(self, gateway=None):
        self.gateway = gateway

    async def extract(
        self,
        problem: str,
        search_results: List[Dict],
        context: Optional[Dict] = None,
    ) -> Optional[LearnedProcedure]:
        """
        从搜索结果中提取操作步骤
        
        Args:
            problem: 原始问题
            search_results: 搜索代理返回的结果列表
            context: 当前上下文
            
        Returns:
            LearnedProcedure 或 None
        """
        if not search_results:
            return None

        # 收集所有文本内容
        texts = []
        for sr in search_results:
            if isinstance(sr, dict):
                texts.append(sr.get("snippet", "") or sr.get("title", ""))
            elif hasattr(sr, 'snippet'):
                texts.append(sr.snippet)

        combined_text = "\n---\n".join(texts[:5])  # 取前5条结果

        if not combined_text.strip():
            return None

        # 使用AI模型提取步骤
        if self.gateway:
            return await self._ai_extract(problem, combined_text, context)
        else:
            return self._rule_extract(problem, combined_text)

    async def _ai_extract(
        self, problem: str, content: str, context: Optional[Dict]
    ) -> Optional[LearnedProcedure]:
        """使用AI模型提取结构化步骤"""
        prompt = f"""你是一个操作步骤提取专家。以下是从多个来源收集到的关于"{problem}"的资料：

{content[:3000]}

请从中提取出清晰、可执行的操作步骤。

要求：
1. 步骤必须是具体的动作（可以由自动化系统执行鼠标键盘操作的）
2. 每步要简短明确
3. 按正确顺序排列
4. 包含验证方式
5. 如果有多种方法，标注为备选方案

以JSON格式返回：
{{
    "task_name": "简洁的任务名",
    "steps": [
        "步骤1: 具体动作描述",
        "步骤2: 具体动作描述"
    ],
    "confidence": 0.85,
    "source_summary": "主要参考了哪些来源",
    "verification": "最终如何确认成功",
    "fallback": "如果标准方法失败的备选路径",
    "risk_level": "SAFE/LOW/MEDIUM/HIGH"
}}"""

        try:
            response = await self.gateway.chat_async(
                user_message=prompt,
                system_prompt="你是操作步骤提取专家，擅长从教程文档中提取精确的可执行步骤。",
                tier="pro",  # 提炼步骤用Pro更准确
                temperature=0.3,
                max_tokens=2048,
                response_format={"type": "json_object"},
            )

            data = json.loads(response.content)
            
            procedure = LearnedProcedure(
                task_name=data.get("task_name", problem)[:100],
                steps=data.get("steps", []),
                confidence=float(data.get("confidence", 0.5)),
                source=data.get("source_summary", ""),
                tags=self._extract_tags(problem),
            )

            # 备选方案
            if data.get("fallback"):
                procedure.alternatives.append({
                    "name": "备选方案",
                    "steps": [data["fallback"]],
                })

            # 风险检查
            if procedure.is_high_risk():
                logger.warning(f"Extracted procedure has high-risk actions!")

            logger.info(
                f"Extracted {len(procedure)} steps for '{procedure.task_name}' "
                f"(conf={procedure.confidence:.2f})"
            )

            return procedure

        except json.JSONDecodeError as e:
            logger.warning(f"AI extraction JSON parse failed: {e}")
            return self._rule_extract(problem, content)
        except Exception as e:
            logger.error(f"AI extraction failed: {e}")
            return self._rule_extract(problem, content)

    def _rule_extract(self, problem: str, content: str) -> Optional[LearnedProcedure]:
        """基于规则的后备提取（不需要AI）"""
        steps = []
        
        # 按行分割找步骤标记
        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if not line or len(line) < 5:
                continue
            
            # 匹配编号步骤
            if re.match(r'^(\d+)[\.、\:\)]', line):
                clean = re.sub(r'^(\d+)[\.、\:\)]\s*', '', line)
                if len(clean) > 3:
                    steps.append(clean)

            # 匹配动作模式
            for pattern in self.ACTION_PATTERNS:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    action = line[:120]
                    if action not in steps:
                        steps.append(action)

        if not steps:
            return None

        return LearnedProcedure(
            task_name=problem[:80],
            steps=steps[:15],  # 最多15步
            confidence=0.5,   # 规则提取置信度较低
            source="rule_based_extraction",
            tags=self._extract_tags(problem),
        )

    def _extract_tags(self, text: str) -> List[str]:
        """从问题描述提取标签"""
        tags = []
        tag_keywords = {
            "Excel": ["excel", "表格", "xlsx"],
            "Word": ["word", "文档", "docx"],
            "PPT": ["ppt", "幻灯片", "演示"],
            "浏览器": ["浏览器", "chrome", "edge", "网页", "网站"],
            "文件": ["文件", "文件夹", "整理"],
            "PDF": ["pdf"],
            "安装": ["安装", "install"],
            "导出": ["导出", "export"],
        }
        lower = text.lower()
        for tag, keywords in tag_keywords.items():
            if any(kw in lower for kw in keywords):
                tags.append(tag)
        return tags[:5]
