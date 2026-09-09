"""控制台 API 进程入口。

    uvicorn backend.runtime.api_console:app --host 127.0.0.1 --port 8787 --reload

M0–M1 阶段 ingest 与 console 合并在此进程；Trace 写入量大时再拆
（`runtime/ingest.py` 与它共享同一份代码与数据库）。
"""

from __future__ import annotations

from backend.app.main import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.runtime.api_console:app", host="127.0.0.1", port=8787, reload=True)
