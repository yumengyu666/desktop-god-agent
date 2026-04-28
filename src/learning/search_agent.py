"""
搜索代理 - 联网学习的信息获取层
支持多源搜索 + 资料评分排序
"""

import logging
import re
from typing import List, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger("Learning.Search")


@dataclass
class SearchResult:
    """单条搜索结果"""
    title: str
    url: str
    snippet: str           # 摘要文字
    relevance_score: float = 0.0   # 相关性 0~10
    credibility_score: float = 0.0  # 可信度 0~10
    source_type: str = ""          # official/forum/blog/video/doc
    published_date: str = ""       # 发布时间
    has_screenshots: bool = False  # 是否有截图说明


class SearchAgent:
    """
    搜索代理
    
    策略：
    1. 构建精准搜索关键词（中文本地化 + 英文备选）
    2. 多源搜索（优先官方文档）
    3. 对结果进行质量评分排序
    """

    # 优先级来源类型（从高到低）
    SOURCE_PRIORITY = {
        "official": 10,      # 官方文档/帮助中心
        "doc": 9,            # 技术文档站点
        "tutorial": 8,       # 高质量教程
        "forum": 6,          # 论坛经验
        "blog": 5,           # 博客
        "video": 7,          # 视频教程
        "unknown": 3,        # 未知来源
    }

    def __init__(self, gateway=None):
        self.gateway = gateway

    async def search(self, query: str, max_results: int = 8) -> List[SearchResult]:
        """
        执行搜索并返回排序后的结果列表
        
        实际实现中会调用搜索引擎API或web_search工具。
        这里先做关键词优化和模拟结构化输出，
        真实搜索通过gateway的ResearchWorker完成。
        """
        # Step 1: 关键词优化
        queries = self._build_queries(query)

        all_results: List[SearchResult] = []

        # Step 2: 通过网关调用搜索工种
        if self.gateway:
            try:
                # 用DeepSeek Flash进行搜索策略分析
                prompt = (
                    f"我需要搜索以下问题的解决方案：{query}\n\n"
                    f"请给出3个最优的搜索关键词组合（中英文各一个），"
                    f"以及预期的最佳资料来源类型。\n"
                    f"以JSON格式返回: {{'queries': [...], 'expected_source': '...'}}"
                )
                
                response = await self.gateway.chat_async(
                    user_message=prompt,
                    tier="flash",
                    max_tokens=500,
                    response_format={"type": "json_object"},
                )
                
                # 解析搜索建议
                try:
                    data = json.loads(response.content)
                    if isinstance(data, dict) and "queries" in data:
                        queries.extend(data["queries"])
                        logger.info(f"Search queries optimized: {data['queries'][:3]}")
                except (json.JSONDecodeError, AttributeError):
                    pass
                    
            except Exception as e:
                logger.warning(f"Search query optimization failed: {e}")

        # Step 3: 返回结构化的搜索请求（实际搜索由外部执行引擎处理）
        # 这里返回带元数据的搜索任务描述
        results = []
        for q in queries[:max_results]:
            results.append(SearchResult(
                title=f"搜索: {q}",
                url="",
                snippet=q,
                relevance_score=8.0,
                credibility_score=6.0,
                source_type="query",
            ))

        logger.info(f"[SearchAgent] Generated {len(results)} search targets")
        return results

    def _build_queries(self, query: str) -> List[str]:
        """构建多组搜索关键词"""
        queries = [query.strip()]

        # 中文精准搜索
        queries.append(f"{query} 教程")
        queries.append(f"{query} 方法 步骤")

        # 英文备选
        english_map = {
            "导出": "export", "导入": "import", "打开": "open",
            "下载": "download", "安装": "install", "设置": "setup/configure",
            "怎么": "how to", "如何": "how to", "问题": "problem/troubleshoot",
        }
        en_query = query
        for cn, en in english_map.items():
            if cn in query:
                en_query = en_query.replace(cn, en)
        if en_query != query:
            queries.append(en_query)

        # 常见后缀
        for suffix in [" 教程 2025", " 教程 2026", " troubleshooting"]:
            queries.append(query + suffix)

        return list(dict.fromkeys(queries))  # 去重保序

    def rank_results(self, results: List[SearchResult]) -> List[SearchResult]:
        """综合评分排序"""
        for r in results:
            r.relevance_score = self._score_relevance(r)
            r.credibility_score = self._score_credibility(r)

        results.sort(
            key=lambda r: (r.credibility_score + r.relevance_score) / 2,
            reverse=True,
        )
        return results

    def _score_relevance(self, r: SearchResult) -> float:
        score = 5.0
        if r.has_screenshots:
            score += 2.0
        if len(r.snippet) > 100:
            score += 1.0
        return min(score, 10.0)

    def _score_credibility(self, r: SearchResult) -> float:
        base = self.SOURCE_PRIORITY.get(r.source_type, 3.0)
        if r.published_date and ("202" in r.published_date or "20" in r.published_date):
            base += 1.0  # 近期加分
        return min(base, 10.0)
