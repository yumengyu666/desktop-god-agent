"""
三层记忆系统实现

使用 SQLite 作为持久化后端，
支持结构化经验存储、晋升机制、智能检索。
"""

import time
import json
import sqlite3
import hashlib
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from typing import Optional
from pathlib import Path
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class MemoryTier(str, Enum):
    """记忆层级"""
    TEMPORARY = "temporary"       # 临时记忆 (session)
    SHORT_TERM = "short_term"     # 短期记忆 (working)
    LONG_TERM = "long_term"       # 长期记忆 (knowledge)


class MemoryType(str, Enum):
    """记忆类型"""
    TASK_RESULT = "task_result"     # 任务执行结果
    OPERATION_STEP = "operation"     # 操作步骤
    ERROR_CASE = "error_case"        # 错误案例
    USER_PREFERENCE = "preference"   # 用户偏好
    APP_KNOWLEDGE = "app_knowledge"  # 软件知识
    GENERIC = "generic"              # 通用


@dataclass
class MemoryEntry:
    """单条记忆条目"""
    id: Optional[int] = None
    tier: MemoryTier = MemoryTier.TEMPORARY
    mem_type: MemoryType = MemoryType.GENERIC
    
    title: str = ""                  # 简短标题
    content: str = ""                # 详细内容（可以是JSON）
    
    # 元数据
    tags: list[str] = field(default_factory=list)
    context_app: str = ""            # 相关应用名
    context_window: str = ""         # 相关窗口标题
    
    # 统计
    success_count: int = 0           # 使用成功次数
    failure_count: int = 0           # 失败次数
    access_count: int = 0            # 访问次数
    last_accessed: float = field(default_factory=time.time)
    
    # 时间戳
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None  # 过期时间（None=不过期）

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.5  # 无数据时中性
        return self.success_count / total

    @property
    def score(self) -> float:
        """综合评分（用于排序）"""
        recency = max(0, 1 - (time.time() - self.last_accessed) / 86400 / 30)
        freq = min(1, self.access_count / 20)
        quality = self.success_rate
        return recency * 0.3 + freq * 0.3 + quality * 0.4

    def to_dict(self) -> dict:
        d = asdict(self)
        d['tier'] = self.tier.value if isinstance(self.tier, MemoryTier) else self.tier
        d['mem_type'] = self.mem_type.value if isinstance(self.mem_type, MemoryType) else self.mem_type
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'MemoryEntry':
        if 'tier' in data and isinstance(data['tier'], str):
            data['tier'] = MemoryTier(data['tier'])
        if 'mem_type' in data and isinstance(data['mem_type'], str):
            data['mem_type'] = MemoryType(data['mem_type'])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class MemorySystem:
    """
    三层记忆管理系统
    
    核心能力：
    - 三层独立存储 + 自动晋升/降级
    - 全文搜索 + 标签过滤
    - 过期自动清理
    - 经验统计与评分排序
    """

    def __init__(self, db_path: str = "./data/memory.db"):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._conn: Optional[sqlite3.Connection] = None
        self._promotion_threshold = 3  # 晋升短期所需成功次数
        self._long_term_threshold = 10 # 晋升长期所需次数
        
        self._init_db()
        logger.info(f"MemorySystem initialized | db={db_path}")

    # ================================================================
    # 数据库初始化
    # ================================================================

    def _init_db(self) -> None:
        """创建表结构"""
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        
        cursor = self._conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tier TEXT NOT NULL DEFAULT 'temporary',
                mem_type TEXT NOT NULL DEFAULT 'generic',
                title TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                tags TEXT DEFAULT '[]',           -- JSON array
                context_app TEXT DEFAULT '',
                context_window TEXT DEFAULT '',
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                access_count INTEGER DEFAULT 0,
                last_accessed REAL,
                created_at REAL,
                updated_at REAL,
                expires_at REAL
            );
            
            -- 索引加速查询
            CREATE INDEX IF NOT EXISTS idx_tier ON memories(tier);
            CREATE INDEX IF NOT EXISTS idx_type ON memories(mem_type);
            CREATE INDEX IF NOT EXISTS idx_tags ON memories(tags);
            CREATE INDEX IF NOT EXISTS idx_last_access ON memories(last_accessed);
            
            -- 全文搜索虚拟表（SQLite FTS5）
            CREATE VIRTUAL TABLE IF NOT USING fts5(
                memories_fts(title, content, tags, 
                            content=memories, content_rowid=id);
            );
            
            -- 晋升触发器：临时→短期
            CREATE TRIGGER IF NOT EXISTS promote_to_short_term
            AFTER UPDATE OF success_count ON memories
            WHEN new.tier = 'temporary' AND new.success_count >= 3
            BEGIN
                UPDATE memories SET tier='short_term' WHERE id=new.id;
            END;
            
            -- 晋升触发器：短期→长期
            CREATE TRIGGER IF NOT EXISTS promote_to_long_term
            AFTER UPDATE OF success_count ON memories
            WHEN new.tier = 'short_term' AND new.success_count >= 10
            BEGIN
                UPDATE memories SET tier='long_term' WHERE id=new.id;
            END;
        """)
        self._conn.commit()

    # ================================================================
    # 增删改查
    # ================================================================

    def add(
        self,
        title: str,
        content: str,
        *,
        tier: MemoryTier = MemoryTier.TEMPORARY,
        mem_type: MemoryType = MemoryType.GENERIC,
        tags: list[str] | None = None,
        context_app: str = "",
        context_window: str = "",
        expires_hours: Optional[int] = None,
    ) -> MemoryEntry:
        """添加一条新记忆"""
        now = time.time()
        expires = (now + expires_hours * 3600) if expires_hours else None
        
        entry = MemoryEntry(
            tier=tier,
            mem_type=mem_type,
            title=title,
            content=content,
            tags=tags or [],
            context_app=context_app,
            context_window=context_window,
            created_at=now,
            updated_at=now,
            expires_at=expires,
        )
        
        cur = self._conn.cursor()
        cur.execute("""
            INSERT INTO memories (
                tier, mem_type, title, content, tags,
                context_app, context_window,
                created_at, updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry.tier.value, entry.mem_type.value, entry.title, entry.content,
            json.dumps(entry.tags),
            entry.context_app, entry.context_window,
            entry.created_at, entry.updated_at, entry.expires_at,
        ))
        entry.id = cur.lastrowid
        self._conn.commit()
        
        logger.debug(f"[MEMORY ADD] [{entry.tier.value}] {entry.title} (id={entry.id})")
        return entry

    def get(self, entry_id: int) -> Optional[MemoryEntry]:
        """按ID获取记忆"""
        cur = self._conn.execute("SELECT * FROM memories WHERE id=?", (entry_id,))
        row = cur.fetchone()
        if row is None:
            return None
        
        # 更新访问统计
        self._access(entry_id)
        return self._row_to_entry(row)

    def update(self, entry_id: int, **kwargs) -> bool:
        """更新记忆条目"""
        allowed = {'title', 'content', 'tags', 'context_app', 'context_window'}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
            
        if 'tags' in updates and isinstance(updates['tags'], list):
            updates['tags'] = json.dumps(updates['tags'])
        
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [entry_id]
        
        self._conn.execute(
            f"UPDATE memories SET {set_clause}, updated_at=? WHERE id=?",
            values + [time.time(), entry_id],
        )
        self._conn.commit()
        return True

    def delete(self, entry_id: int) -> bool:
        """删除记忆"""
        cur = self._conn.execute("DELETE FROM memories WHERE id=?", (entry_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # ================================================================
    # 检索
    # ================================================================

    def search(
        self,
        query: str = "",
        *,
        tier: Optional[MemoryTier] = None,
        mem_type: Optional[MemoryType] = None,
        tags: list[str] | None = None,
        limit: int = 20,
        sort_by: str = "score",  # score / recency / frequency / quality
    ) -> list[MemoryEntry]:
        """
        搜索记忆
        
        Args:
            query: 搜索关键词（全文）
            tier: 过滤层级
            mem_type: 过滤类型
            tags: 过滤标签（任一匹配即可）
            limit: 返回数量上限
            sort_by: 排序方式
        """
        conditions = ["expires_at IS NULL OR expires_at > ?", time.time()]
        params: list = []
        
        if tier:
            conditions.append("tier=?")
            params.append(tier.value)
        if mem_type:
            conditions.append("mem_type=?")
            params.append(mem_type.value)
        if query:
            conditions.append("(title LIKE ? OR content LIKE ?)")
            q = f"%{query}%"
            params.extend([q, q])
        if tags:
            tag_conditions = [f"tags LIKE ?" for _ in tags]
            conditions.append(f"({' OR '.join(tag_conditions)})")
            params.extend([f"%{t}%" for t in tags])
        
        where = " AND ".join(conditions)
        
        order_map = {
            "score": "((success_count/(success_count+failure_count+1)) * 0.4 + "
                      "(access_count/20.0) * 0.3 + "
                      "(1-(?-last_accessed)/86400/30) * 0.3) DESC",
            "recency": "last_accessed DESC",
            "frequency": "access_count DESC",
            "quality": "(success_count*1.0/GREATEST(success_count+failure_count,1)) DESC",
        }
        
        # score排序需要当前时间参数
        extra_params = [time.time()] if sort_by == "score" else []
        
        sql = f"""SELECT * FROM memories 
                 WHERE {where} 
                 ORDER BY {order_map.get(sort_by, order_map['score'])}
                 LIMIT ?"""
        
        rows = self._conn.execute(sql, params + extra_params + [limit]).fetchall()
        
        entries = [self._row_to_entry(row) for row in rows]
        
        # 批量更新访问计数
        ids = [e.id for e in entries if e.id]
        if ids:
            placeholders = ",".join("?" * len(ids))
            self._conn.execute(
                f"UPDATE memories SET access_count=access_count+1, "
                f"last_accessed=? WHERE id IN ({placeholders})",
                [time.time()] + ids,
            )
            self._conn.commit()
        
        return entries

    def get_similar(self, text: str, limit: int = 5) -> list[MemoryEntry]:
        """获取相似记忆（基于关键词匹配的简化版向量检索）"""
        words = set(text.lower().split())
        if not words:
            return []
        
        # 对每个词打分
        scored = []
        for entry in self.search(limit=100):
            entry_text = (f"{entry.title} {entry.content}").lower()
            match_count = sum(1 for w in words if w in entry_text)
            if match_count > 0:
                scored.append((match_count / len(words), entry))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]

    def get_recent(self, n: int = 10, tier: Optional[MemoryTier] = None) -> list[MemoryEntry]:
        """获取最近添加的记忆"""
        if tier:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE tier=? ORDER BY created_at DESC LIMIT ?",
                (tier.value, n),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?",
                (n,),
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    # ================================================================
    # 晋升/降级
    # ================================================================

    def record_success(self, entry_id: int) -> None:
        """记录一次成功使用（可能触发晋升）"""
        self._conn.execute(
            "UPDATE memories SET success_count=success_count+1, "
            "last_accessed=?, updated_at=? WHERE id=?",
            (time.time(), time.time(), entry_id),
        )
        self._conn.commit()
        
        # 检查是否需要晋升
        entry = self.get(entry_id)
        if entry and entry.tier == MemoryTier.TEMPORARY and entry.success_count >= self._promotion_threshold:
            self._promote(entry_id, MemoryTier.SHORT_TERM)
            logger.info(f"[PROMOTE] {entry.title}: temp→short")
        elif entry and entry.tier == MemoryTier.SHORT_TERM and entry.success_count >= self._long_term_threshold:
            self._promote(entry_id, MemoryTier.LONG_TERM)
            logger.info(f"[PROMOTE] {entry.title}: short→long")

    def record_failure(self, entry_id: int) -> None:
        """记录一次失败使用（多次失败则降级）"""
        self._conn.execute(
            "UPDATE memories SET failure_count=failure_count+1, "
            "last_accessed=?, updated_at=? WHERE id=?",
            (time.time(), time.time(), entry_id),
        )
        self._conn.commit()
        
        entry = self.get(entry_id)
        if not entry:
            return
            
        # 失败率过高则降级
        if entry.failure_count > 5 and entry.success_rate < 0.2:
            if entry.tier == MemoryTier.LONG_TERM:
                self._demote(entry_id, MemoryTier.SHORT_TERM)
                logger.info(f"[DEMOTE] {entry.title}: long→short")
            elif entry.tier == MemoryTier.SHORT_TERM:
                self._demote(entry_id, MemoryTier.TEMPORARY)
                logger.info(f"[DEMOTE] {entry.title}: short→temp")

    def _promote(self, entry_id: int, target_tier: MemoryTier) -> None:
        self._conn.execute(
            "UPDATE memories SET tier=?, updated_at=? WHERE id=?",
            (target_tier.value, time.time(), entry_id),
        )
        self._conn.commit()

    def _demote(self, entry_id: int, target_tier: MemoryTier) -> None:
        self._conn.execute(
            "UPDATE memories SET tier=?, updated_at=? WHERE id=?",
            (target_tier.value, time.time(), entry_id),
        )
        self._conn.commit()

    def _access(self, entry_id: int) -> None:
        """更新访问统计"""
        self._conn.execute(
            "UPDATE memories SET access_count=access_count+1, last_accessed=? WHERE id=?",
            (time.time(), entry_id),
        )

    # ================================================================
    # 清理
    # ================================================================

    def cleanup_expired(self) -> int:
        """清理过期记忆"""
        cur = self._conn.execute(
            "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < ?",
            (time.time(),),
        )
        count = cur.rowcount
        self._conn.commit()
        if count > 0:
            logger.info(f"[CLEANUP] Removed {count} expired memories")
        return count

    def clear_temporary(self) -> int:
        """清除所有临时记忆"""
        cur = self._conn.execute("DELETE FROM memories WHERE tier=?", ("temporary",))
        self._conn.commit()
        return cur.rowcount

    def get_stats(self) -> dict:
        """获取记忆系统统计信息"""
        stats = {}
        for tier in MemoryTier:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM memories WHERE tier=?", (tier.value,)
            ).fetchone()[0]
            stats[f"{tier.value}_count"] = count
        
        stats['total'] = sum(stats.values())
        stats['db_size_bytes'] = self._db_path.stat().st_size if self._db_path.exists() else 0
        return stats

    @staticmethod
    def _row_to_entry(row) -> MemoryEntry:
        return MemoryEntry.from_dict(dict(row))

    def close(self) -> None:
        if self._conn:
            self._conn.close()


# 全局单例
_memory_instance: Optional[MemorySystem] = None


def get_memory() -> MemorySystem:
    global _memory_instance
    from src.config.settings import settings
    if _memory_instance is None:
        _memory_instance = MemorySystem(db_path=settings.MEMORY_DB_PATH)
    return _memory_instance
