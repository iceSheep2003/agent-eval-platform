"""领域错误 → HTTP 响应。

业务代码只抛 `DomainError`，**不抛 HTTPException**——否则错误码会散落在路由里，
前端拿不到稳定的 `errorCode`。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..contracts.errors import DomainError, Errors
from ..schemas.response import fail

logger = logging.getLogger(__name__)


def _render(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(status_code=status, content=fail(code, message, http_status=status))


async def domain_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    if exc.http_status >= 500:
        logger.exception("领域错误 %s", exc.code)
    return _render(exc.code, str(exc), exc.http_status)


async def validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    message = first.get("msg", "参数校验失败")
    detail = f"{location}: {message}" if location else message
    return _render(Errors.VALIDATION_FAILED.code, detail, Errors.VALIDATION_FAILED.http_status)


async def http_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = "http_error"
    if exc.status_code == 404:
        code = Errors.NOT_FOUND.code
    elif exc.status_code == 401:
        code = Errors.UNAUTHENTICATED.code
    elif exc.status_code == 403:
        code = Errors.PERMISSION_DENIED.code
    return _render(code, str(exc.detail), exc.status_code)


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常")
    return _render(
        "internal_error", "服务内部错误", Errors.CONTRACT_VERSION_MISMATCH.http_status
    )


def install(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
