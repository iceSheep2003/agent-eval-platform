from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.agents import router as agents_router
from backend.app.api.auth import router as auth_router
from backend.app.api.catalog import router as catalog_router
from backend.app.api.context import router as context_router
from backend.app.api.gateway import router as gateway_router
from backend.app.api.operations import router as operations_router
from backend.app.api.runs import router as runs_router
from backend.app.api.telemetry import router as telemetry_router
from backend.app.application.services import ConflictError, NotFoundError
from backend.app.container import Container
from backend.app.core.config import Settings


def create_app(settings: Settings | None = None, *, start_worker: bool = True) -> FastAPI:
    resolved = settings or Settings.from_env()
    container = Container.build(resolved)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if start_worker:
            container.worker.start()
        yield
        container.worker.stop()

    app = FastAPI(title="Eval Loom Control Plane", version="0.2.0", lifespan=lifespan)
    app.state.container = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:4173", "http://localhost:4173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth_router)
    app.include_router(agents_router)
    app.include_router(runs_router)
    app.include_router(catalog_router)
    app.include_router(context_router)
    app.include_router(operations_router)
    app.include_router(gateway_router)
    app.include_router(telemetry_router)

    @app.get("/api/health")
    def health():
        return {"ok": True, "service": "eval-loom-control-plane", "runtime": container.runtime.name}

    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, exc: NotFoundError):
        return JSONResponse({"error": str(exc)}, status_code=404)

    @app.exception_handler(ConflictError)
    async def conflict(_: Request, exc: ConflictError):
        return JSONResponse({"error": str(exc)}, status_code=409)

    frontend_dist = Path(os.getenv("EVAL_LOOM_FRONTEND_DIST", "frontend/dist"))
    if frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


# Uvicorn import target. A master key is intentionally mandatory.
app = create_app()
