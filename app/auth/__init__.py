"""
用户认证模块

提供 JWT 令牌签发/验证、密码哈希/校验、用户注册/登录功能。
使用 bcrypt 密码哈希和 HS256 JWT 签名。

数据库使用 SQLite，表结构：
- users: id, username, password_hash, display_name, created_at, last_login
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from uuid import uuid4

import bcrypt
import jwt

from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)

USERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT DEFAULT '',
    avatar_url TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);
"""


def _get_db() -> sqlite3.Connection:
    """获取认证数据库连接"""
    db_path = Path(settings.auth_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(USERS_TABLE_SQL)
    conn.row_factory = sqlite3.Row
    return conn


# ==================== 密码处理 ====================


def hash_password(password: str) -> str:
    """对密码进行 bcrypt 哈希"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """校验密码是否匹配哈希"""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ==================== JWT 令牌 ====================


def create_token(user_id: str) -> str:
    """创建 JWT 令牌，24 小时有效期

    Args:
        user_id: 用户 ID

    Returns:
        JWT 字符串
    """
    payload = {
        "sub": user_id,
        "jti": str(uuid4()),
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


def verify_token(token: str) -> dict:
    """验证 JWT 令牌

    Args:
        token: JWT 字符串

    Returns:
        payload 字典（含 sub, jti, exp 等字段）

    Raises:
        jwt.ExpiredSignatureError: 令牌已过期
        jwt.InvalidTokenError: 令牌无效
    """
    return jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])


# ==================== 用户操作 ====================


def register_user(username: str, password: str, display_name: str = "") -> dict:
    """注册新用户

    Args:
        username: 用户名（唯一）
        password: 明文密码
        display_name: 显示名称（可选）

    Returns:
        用户信息字典

    Raises:
        ValueError: 用户名已存在
    """
    conn = _get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM users WHERE username=?", (username,)
        ).fetchone()
        if existing:
            raise ValueError("用户名已存在")

        user_id = str(uuid4())
        pwd_hash = hash_password(password)
        conn.execute(
            "INSERT INTO users (id, username, password_hash, display_name) VALUES (?, ?, ?, ?)",
            (user_id, username, pwd_hash, display_name or username),
        )
        conn.commit()
        logger.info("用户注册成功: username=%s, id=%s", username, user_id)
        return {
            "id": user_id,
            "username": username,
            "display_name": display_name or username,
        }
    finally:
        conn.close()


def login_user(username: str, password: str) -> dict:
    """用户登录

    Args:
        username: 用户名
        password: 明文密码

    Returns:
        含用户信息和 token 的字典

    Raises:
        ValueError: 用户名或密码错误
    """
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT id, username, password_hash, display_name FROM users WHERE username=?",
            (username,),
        ).fetchone()
        if not row:
            raise ValueError("用户名或密码错误")

        user = dict(row)
        if not verify_password(password, user["password_hash"]):
            raise ValueError("用户名或密码错误")

        # 更新最后登录时间
        conn.execute(
            "UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?",
            (user["id"],),
        )
        conn.commit()

        token = create_token(user["id"])
        logger.info("用户登录成功: username=%s", username)
        return {
            "token": token,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "display_name": user["display_name"],
            },
        }
    finally:
        conn.close()


def get_user_by_id(user_id: str) -> dict | None:
    """根据 ID 查询用户信息"""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT id, username, display_name, avatar_url, created_at FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_token(token: str) -> dict | None:
    """根据 JWT 令牌获取用户信息"""
    try:
        payload = verify_token(token)
        return get_user_by_id(payload["sub"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError) as e:
        logger.warning("Token 验证失败: %s", e)
        return None
