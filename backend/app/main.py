"""FastAPI 应用装配。

一份代码、四个入口：本文件只负责**装配**，进程入口在 `backend/runtime/`。
路由前缀约定：`/api/*` 是兼容面（前端与示例脚本已在用），`/api/v1/*` 是同一批路由的别名，
`/v1/*` 是机器面（Gateway / Ingest）。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .api import CONSOLE_PREFIXES, MACHINE_PREFIX
from .api import errors as api_errors
from .api.agents_view import router as agents_view_router
from .api.overview import router as overview_router
from .api.regression import router as regression_router
from .container import Container
from .contracts import CONTRACT_VERSION
from .modules.asset.api.capability_router import router as capability_router
from .modules.asset.api.router import router as asset_router
from .modules.dataset.api.router import router as dataset_router
from .modules.delivery.api.router import router as delivery_router
from .modules.evaluation.api.router import router as evaluation_router
from .modules.execution.api.gateway import router as gateway_router
from .modules.execution.api.router import router as execution_router
from .modules.identity.api.router import auth_router, workspace_router
from .modules.observability.api.ingest import router as ingest_router
from .modules.observability.api.router import router as trace_router
from .modules.portal.api.router import router as portal_router
from .schemas.response import ok

#: 控制台路由表。新模块在这里登记，自动获得 `/api` 与 `/api/v1` 两个前缀。
CONSOLE_ROUTERS = (
    auth_router,
    workspace_router,
    asset_router,
    capability_router,
    dataset_router,
    evaluation_router,
    execution_router,
    trace_router,
    delivery_router,
    agents_view_router,
    overview_router,
    regression_router,
    portal_router,
)

#: 机器面路由表（SDK 上报、Gateway）。只挂 `/v1`，不走 `/api`。
MACHINE_ROUTERS = (ingest_router, gateway_router)


def create_app(container: Container | None = None) -> FastAPI:
    resolved = container or Container.build()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await resolved.startup()
        try:
            yield
        finally:
            await resolved.shutdown()

    app = FastAPI(
        title="Eval Loom",
        version=CONTRACT_VERSION,
        lifespan=lifespan,
    )
    app.state.container = resolved

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    api_errors.install(app)

    for prefix in CONSOLE_PREFIXES:
        for router in CONSOLE_ROUTERS:
            app.include_router(router, prefix=prefix)

    for router in MACHINE_ROUTERS:
        app.include_router(router, prefix=MACHINE_PREFIX)

    @app.get("/api/live", tags=["ops"])
    async def live() -> dict:
        """liveness：只证明进程活着，**不碰数据库**——DB 抖动不该导致 pod 被重启。"""
        return ok({"status": "alive"})

    @app.get("/api/health", tags=["ops"])
    @app.get("/api/v1/health", tags=["ops"], include_in_schema=False)
    async def health() -> dict:
        """readiness：能连上数据库才算就绪（`deploy/local-k8s/platform.yaml` 打的就是这个）。"""
        async with resolved.database.session() as session:
            await session.execute(text("SELECT 1"))
        return ok(
            {
                "status": "ready",
                "contract_version": CONTRACT_VERSION,
                "dialect": resolved.database.dialect,
            }
        )

    return app
