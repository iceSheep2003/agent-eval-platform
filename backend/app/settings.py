"""运行配置。

全部来自环境变量，**没有配置文件**——部署时注入，本地开发用默认值。
主密钥在开发态落本地文件，生产态强制外部注入（不进数据库、不进镜像）。
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

MASTER_KEY_ENV = "EVAL_LOOM_MASTER_KEY"
ENV_ENV = "EVAL_LOOM_ENV"
DATA_DIR_ENV = "EVAL_LOOM_DATA_DIR"
DATABASE_URL_ENV = "EVAL_LOOM_DATABASE_URL"
RUNTIME_BACKEND_ENV = "RUNTIME_BACKEND"

DEFAULT_DATA_DIR = Path(".data/eval-loom")
MASTER_KEY_FILENAME = ".master-key"


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


@dataclass(frozen=True, slots=True)
class Settings:
    env: str = "development"
    data_dir: Path = DEFAULT_DATA_DIR
    database_url: str = ""
    runtime_backend: str = "local"
    master_key: str = ""

    # 会话
    cookie_name: str = "eval_loom_session"
    cookie_secure: bool = False
    session_idle_hours: int = 4
    session_absolute_hours: int = 24
    csrf_enabled: bool = True

    # 展示平台（portal）：**独立账号体系**，cookie 名与平台不共用
    portal_cookie_name: str = "eval_loom_portal_session"
    portal_session_hours: int = 24

    # 认证
    require_sso: bool = False

    # 上传
    max_ingest_events: int = 1000
    max_ingest_bytes: int = 5 * 1024 * 1024

    # 队列
    command_lease_seconds: int = 60
    command_max_attempts: int = 5

    log_format: str = "console"  # console | json（k8s 日志采集用 json）

    cors_origins: tuple[str, ...] = field(
        default=(
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:4173",
            # 展示平台（frontend-showcase）的开发服务器
            "http://localhost:5174",
            "http://127.0.0.1:5174",
        )
    )

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def db_path(self) -> Path:
        """SQLite 文件路径（仅本地开发用；生产走 database_url）。"""
        return self.data_dir / "eval-loom.db"

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.getenv(ENV_ENV, "development").strip().lower()
        data_dir = Path(os.getenv(DATA_DIR_ENV) or DEFAULT_DATA_DIR)
        database_url = os.getenv(DATABASE_URL_ENV) or f"sqlite+aiosqlite:///{data_dir / 'eval-loom.db'}"
        return cls(
            env=env,
            data_dir=data_dir,
            database_url=database_url,
            runtime_backend=os.getenv(RUNTIME_BACKEND_ENV, "local").strip().lower(),
            master_key=_resolve_master_key(env, data_dir),
            cookie_secure=(env == "production"),
            session_idle_hours=_int_env("EVAL_LOOM_SESSION_IDLE_HOURS", 4),
            session_absolute_hours=_int_env("EVAL_LOOM_SESSION_ABSOLUTE_HOURS", 24),
            portal_session_hours=_int_env("EVAL_LOOM_PORTAL_SESSION_HOURS", 24),
            csrf_enabled=_bool_env("EVAL_LOOM_CSRF_ENABLED", True),
            require_sso=_bool_env("AUTH_REQUIRE_SSO", False),
            command_lease_seconds=_int_env("EVAL_LOOM_COMMAND_LEASE_SECONDS", 60),
            command_max_attempts=_int_env("EVAL_LOOM_COMMAND_MAX_ATTEMPTS", 5),
            log_format=os.getenv("EVAL_LOOM_LOG_FORMAT", "console").strip().lower(),
            cors_origins=_cors_origins(),
        )


def _cors_origins() -> tuple[str, ...]:
    raw = os.getenv("EVAL_LOOM_CORS_ORIGINS", "").strip()
    if not raw:
        return (
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:4173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
        )
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _resolve_master_key(env: str, data_dir: Path) -> str:
    """生产强制外部注入；开发态生成一次并落本地文件，重启不失效。"""
    injected = os.getenv(MASTER_KEY_ENV, "").strip()
    if injected:
        return injected
    if env == "production":
        raise RuntimeError(
            f"生产环境必须注入 {MASTER_KEY_ENV}；主密钥不落盘、不进数据库"
        )
    data_dir.mkdir(parents=True, exist_ok=True)
    key_file = data_dir / MASTER_KEY_FILENAME
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    key = secrets.token_urlsafe(48)
    key_file.write_text(key, encoding="utf-8")
    key_file.chmod(0o600)
    return key
