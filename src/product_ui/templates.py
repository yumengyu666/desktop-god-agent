"""
模板系统 - 用户可保存常用操作为一键执行
例如：每天下午5点发日报、每周整理下载文件夹
"""

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Dict

logger = logging.getLogger("ProductUI.Template")


@dataclass
class TaskTemplate:
    """任务模板"""
    name: str                           # 模板名（如"每日日报"）
    description: str = ""
    command: str = ""                   # 执行的指令文本
    params: Dict[str, str] = field(default_factory=dict)  # 可变参数
    tags: List[str] = field(default_factory=list)
    schedule: Optional[str] = None      # cron表达式或固定时间
    created_at: float = field(default_factory=0)
    run_count: int = 0                  # 已执行次数
    avg_time_s: float = 0.0             # 平均耗时
    last_run: Optional[float] = None
    
    def to_dict(self) -> dict:
        return asdict(self)


# 内置模板库
BUILTIN_TEMPLATES: List[Dict] = [
    {
        "name": "日报生成",
        "description": "基于今日工作内容生成工作日报",
        "command": "生成今日工作日报，包含：完成的工作项、遇到的问题、明天的计划",
        "tags": ["办公", "日报", "日常"],
        "schedule": "17:00",
    },
    {
        "name": "桌面清理",
        "description": "按类型整理桌面文件到对应文件夹",
        "command": "整理桌面文件，按类型分类归档（图片/文档/视频/其他）",
        "tags": ["文件管理", "清理"],
    },
    {
        "name": "下载目录整理",
        "description": "清理并归类下载文件夹中的文件",
        "command": "整理下载文件夹，删除临时文件，按类型归档",
        "tags": ["文件管理", "清理"],
    },
    {
        "name": "发送邮件报告",
        "description": "找到最新的报告文件并发送给指定收件人",
        "command": "找到最近修改的报告文件，准备邮件发送给老板",
        "params": {"recipient": "老板邮箱"},
        "tags": ["邮件", "办公"],
    },
]


class TemplateManager:
    """
    模板管理器
    
    功能：
    - 内置模板 + 用户自定义模板
    - 一键运行
    - 运行统计
    - 导入导出
    """

    def __init__(self, save_path: Optional[str] = None):
        self.save_path = Path(save_path or "./data/templates.json")
        self._templates: Dict[str, TaskTemplate] = {}
        self._load()

    def _load(self):
        try:
            if self.save_path.exists():
                with open(self.save_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for name, tdict in data.items():
                        self._templates[name] = TaskTemplate(**tdict)
            else:
                # 首次使用，加载内置模板
                for bt in BUILTIN_TEMPLATES:
                    t = TaskTemplate(**bt)
                    self._templates[t.name] = t
        except Exception as e:
            logger.warning(f"Failed to load templates: {e}")
            # 加载内置模板作为后备
            for bt in BUILTIN_TEMPLATES:
                t = TaskTemplate(**bt)
                self._templates[t.name] = t

    def _save(self):
        try:
            self.save_path.parent.mkdir(parents=True, exist_ok=True)
            data = {name: t.to_dict() for name, t in self._templates.items()}
            with open(self.save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save templates: {e}")

    def list_all(self, tag_filter: Optional[str] = None) -> List[TaskTemplate]:
        """列出所有模板"""
        templates = list(self._templates.values())
        if tag_filter:
            templates = [t for t in templates if tag_filter in (t.tags or [])]
        return sorted(templates, key=lambda t: (-t.run_count, t.name))

    def get(self, name: str) -> Optional[TaskTemplate]:
        return self._templates.get(name)

    def create(
        self,
        name: str,
        command: str,
        description: str = "",
        tags: Optional[List[str]] = None,
        **kwargs,
    ) -> TaskTemplate:
        """创建新模板"""
        import time
        t = TaskTemplate(
            name=name,
            command=command,
            description=description,
            tags=tags or [],
            created_at=time.time(),
            **kwargs,
        )
        self._templates[name] = t
        self._save()
        logger.info(f"Template created: {name}")
        return t

    def delete(self, name: str) -> bool:
        if name in self._templates:
            del self._templates[name]
            self._save()
            return True
        return False

    def update_stats(self, name: str, time_spent_s: float):
        """更新模板的运行统计"""
        t = self._templates.get(name)
        if not t:
            return
        
        import time
        t.run_count += 1
        t.last_run = time.time()
        
        # 更新平均耗时（移动平均）
        if t.avg_time_s > 0:
            t.avg_time_s = t.avg_time_s * 0.7 + time_spent_s * 0.3
        else:
            t.avg_time_s = time_spent_s
        
        self._save()

    def search(self, query: str) -> List[TaskTemplate]:
        """搜索模板"""
        q = query.lower()
        results = []
        for t in self._templates.values():
            score = 0
            if q in t.name.lower(): score += 3
            if q in t.command.lower(): score += 2
            if q in (t.description or "").lower(): score += 1
            if any(q in tag.lower() for tag in (t.tags or [])): score += 1
            
            if score > 0:
                results.append((score, t))
        
        results.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in results]

    @property
    def count(self) -> int:
        return len(self._templates)
