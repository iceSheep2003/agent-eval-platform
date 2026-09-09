from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    package_dir: Path
    master_key: str
    runtime_backend: str = "local"
    kubernetes_namespace: str = "eval-loom"
    worker_poll_seconds: float = 0.1

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("EVAL_LOOM_DATA_DIR", ".data/eval-loom")).resolve()
        master_key = os.getenv("EVAL_LOOM_MASTER_KEY", "")
        if not master_key:
            if os.getenv("EVAL_LOOM_ENV", "development") == "production":
                raise RuntimeError("EVAL_LOOM_MASTER_KEY is required in production")
            data_dir.mkdir(parents=True, exist_ok=True)
            key_path = data_dir / ".master-key"
            if key_path.exists():
                master_key = key_path.read_text(encoding="ascii").strip()
            else:
                master_key = Fernet.generate_key().decode("ascii")
                key_path.write_text(master_key, encoding="ascii")
                key_path.chmod(0o600)
        return cls(
            data_dir=data_dir,
            database_path=data_dir / "platform.db",
            package_dir=data_dir / "packages",
            master_key=master_key,
            runtime_backend=os.getenv("RUNTIME_BACKEND", "local"),
            kubernetes_namespace=os.getenv("KUBERNETES_NAMESPACE", "eval-loom"),
        )
