"""
任务管理器

管理用户的分析任务生命周期。使用 SQLite 持久化存储。

任务状态机：
  pending → running → completed
                    → failed

约束：
  - 每个用户同一时间只能有一个 pending 或 running 状态的任务
  - 任务报告文件按 user_id/task_id/ 目录隔离
"""

import sqlite3
from pathlib import Path
from datetime import datetime
from uuid import uuid4

from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)

TASKS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    product_name TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    progress TEXT DEFAULT '',
    report_md_path TEXT DEFAULT '',
    report_pdf_path TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

TASKS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_tasks_user_status
ON tasks(user_id, status);
"""

TASKS_LIST_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_tasks_user_time
ON tasks(user_id, created_at DESC);
"""


class TaskManager:
    """异步任务管理器"""

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    def __init__(self, db_path: str = None):
        self.db_path = Path(db_path or settings.task_db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.execute(TASKS_TABLE_SQL)
            conn.execute(TASKS_INDEX_SQL)
            conn.execute(TASKS_LIST_INDEX_SQL)
            conn.commit()
        finally:
            conn.close()

    def has_running_task(self, user_id: str) -> bool:
        """检查用户是否有正在运行或等待中的任务"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT id FROM tasks WHERE user_id=? AND status IN ('pending', 'running')",
                (user_id,),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def create_task(self, user_id: str, product_name: str) -> str:
        """创建新任务

        Args:
            user_id: 用户 ID
            product_name: 商品名称

        Returns:
            任务 ID

        Raises:
            RuntimeError: 用户已有活跃任务
        """
        if self.has_running_task(user_id):
            raise RuntimeError("用户已有进行中的任务，请等待完成")

        task_id = str(uuid4())
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO tasks (id, user_id, product_name) VALUES (?, ?, ?)",
                (task_id, user_id, product_name),
            )
            conn.commit()
            logger.info("任务已创建: id=%s, user=%s, product=%s", task_id, user_id, product_name)
            return task_id
        finally:
            conn.close()

    def update_task(self, task_id: str, **kwargs):
        """更新任务字段

        Args:
            task_id: 任务 ID
            **kwargs: 要更新的字段和值
        """
        if not kwargs:
            return
        fields = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [task_id]
        conn = self._get_conn()
        try:
            conn.execute(
                f"UPDATE tasks SET {fields}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                values,
            )
            conn.commit()
        finally:
            conn.close()

    def get_task(self, task_id: str) -> dict | None:
        """获取任务详情"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def delete_task(self, task_id: str, user_id: str) -> bool:
        """删除任务（校验所有权）

        Args:
            task_id: 任务 ID
            user_id: 用户 ID

        Returns:
            是否成功删除
        """
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT id FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)
            ).fetchone()
            if not row:
                return False
            conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
            conn.commit()
            logger.info("任务已删除: id=%s, user=%s", task_id, user_id)
            return True
        finally:
            conn.close()

    def list_user_tasks(
        self, user_id: str, limit: int = 20, offset: int = 0
    ) -> list[dict]:
        """获取用户的任务列表（按创建时间倒序）"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
