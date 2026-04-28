"""
学习成果缓存存储
管理已学习到的操作流程，支持持久化和快速检索
"""

import json
import logging
import time
from pathlib import Path
from typing import List, Optional, Dict

logger = logging.getLogger("Learning.Cache")


class LearningCache:
    """
    学习成果缓存 - 内存+文件双存储
    
    存储位置: ./data/learned_procedures.json
    """

    def __init__(self, save_path: Optional[str] = None):
        self.save_path = Path(save_path or "./data/learned_procedures.json")
        self._cache: Dict[str, Dict] = {}
        self._load()

    def put(self, procedure) -> None:
        """存入一条学习成果"""
        key = self._make_key(procedure.task_name)
        self._cache[key] = procedure.to_dict()
        self._save()
        logger.debug(f"Cached: {key}")

    def get(self, query: str) -> Optional[Dict]:
        """根据查询检索最匹配的学习成果"""
        # 精确匹配
        key = self._make_key(query)
        if key in self._cache:
            return self._cache[key]

        # 模糊匹配（词重叠）
        best_match = None
        best_score = 0.0
        query_lower = query.lower()

        for stored_key, proc_dict in self._cache.items():
            name = proc_dict.get("task_name", "")
            score = self._similarity(query_lower, name.lower())
            if score > best_score:
                best_score = score
                best_match = proc_dict

        if best_match and best_score > 0.3:
            return best_match
        return None

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """模糊搜索多条"""
        query_lower = query.lower()
        scored = []
        for key, d in self._cache.items():
            name = d.get("task_name", "")
            steps_str = " ".join(d.get("steps", []))
            combined = f"{name} {steps_str}".lower()
            score = self._similarity(query_lower, combined)
            if score > 0.1:
                scored.append((score, d))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[:top_k]]

    def delete(self, task_name: str) -> bool:
        key = self._make_key(task_name)
        if key in self._cache:
            del self._cache[key]
            self._save()
            return True
        return False

    def list_all(self) -> List[Dict]:
        return list(self._cache.values())

    def cleanup_expired(self, max_age_days: int = 90) -> int:
        now = time.time()
        expired_keys = [
            k for k, d in self._cache.items()
            if (now - d.get("created_at", 0)) / 86400 > max_age_days
        ]
        for k in expired_keys:
            del self._cache[k]
        if expired_keys:
            self._save()
        return len(expired_keys)

    @property
    def size(self) -> int:
        return len(self._cache)

    # ---- 内部方法 ----

    def _make_key(self, text: str) -> str:
        return "".join(text.lower().split())[:80]

    def _similarity(self, a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        sa, sb = set(a.split()), set(b.split())
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    def _load(self):
        try:
            if self.save_path.exists():
                with open(self.save_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._cache = data
                        logger.info(f"Loaded {len(self._cache)} cached procedures")
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")

    def _save(self):
        try:
            self.save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.save_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")
