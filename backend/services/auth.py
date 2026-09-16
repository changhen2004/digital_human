# services/auth.py
# 登录注册服务 - 用户账号与登录会话（SQLite，仅用标准库）

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config

SESSION_COOKIE = "dh_session"
SESSION_MAX_AGE = 30 * 24 * 3600   # 登录状态保留30天
PBKDF2_ROUNDS = 120_000
USERNAME_PATTERN = re.compile(r"[\w-]{2,32}")


class AuthError(Exception):
    pass


class AuthValidationError(AuthError):
    pass


class AuthConflictError(AuthError):
    pass


class AuthUnauthorizedError(AuthError):
    pass


class AuthService:
    """用户账号与登录会话管理，所有用户共用一份 users.db。"""

    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else Path(config.DATA_DIR) / "users.db"
        self.lock = threading.Lock()
        self._init_database()

    def register(self, username, password):
        username, password = self._validate(username, password)
        salt = secrets.token_hex(16)
        user = {
            "id": secrets.token_hex(16),
            "username": username,
            "createdAt": self._now(),
        }
        with self.lock:
            connection = sqlite3.connect(self.db_path)
            try:
                connection.execute(
                    "INSERT INTO users (id, username, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user["id"], username, self._hash(password, salt), salt, user["createdAt"]),
                )
                connection.commit()
            except sqlite3.IntegrityError as error:
                raise AuthConflictError("用户名已存在") from error
            finally:
                connection.close()
        return user

    def login(self, username, password):
        username, password = self._validate(username, password)
        connection = sqlite3.connect(self.db_path)
        try:
            row = connection.execute(
                "SELECT id, username, password_hash, salt, created_at FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        finally:
            connection.close()
        if row is None or not hmac.compare_digest(self._hash(password, row[3]), row[2]):
            raise AuthUnauthorizedError("用户名或密码错误")
        return {"id": row[0], "username": row[1], "createdAt": row[4]}

    def create_session(self, user_id):
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        with self.lock:
            connection = sqlite3.connect(self.db_path)
            try:
                connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now.isoformat(),))
                connection.execute(
                    "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                    (token, user_id, (now + timedelta(seconds=SESSION_MAX_AGE)).isoformat()),
                )
                connection.commit()
            finally:
                connection.close()
        return token

    def user_for_token(self, token):
        if not isinstance(token, str) or not token:
            return None
        connection = sqlite3.connect(self.db_path)
        try:
            row = connection.execute(
                """
                SELECT users.id, users.username, users.created_at FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token = ? AND sessions.expires_at > ?
                """,
                (token, datetime.now(timezone.utc).isoformat()),
            ).fetchone()
        finally:
            connection.close()
        return {"id": row[0], "username": row[1], "createdAt": row[2]} if row else None

    def logout(self, token):
        with self.lock:
            connection = sqlite3.connect(self.db_path)
            try:
                connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
                connection.commit()
            finally:
                connection.close()

    def count_users(self):
        connection = sqlite3.connect(self.db_path)
        try:
            return connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        finally:
            connection.close()

    def _validate(self, username, password):
        if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username.strip()):
            raise AuthValidationError("用户名需为2到32位中文、字母、数字、下划线或短横线")
        if not isinstance(password, str) or not 6 <= len(password) <= 128:
            raise AuthValidationError("密码长度需为6到128位")
        return username.strip(), password

    def _hash(self, password, salt):
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS).hex()

    def _init_database(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            """)
            connection.commit()
        finally:
            connection.close()

    def _now(self):
        return datetime.now(timezone.utc).isoformat()
