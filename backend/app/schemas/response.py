"""统一响应封装。

前端 `frontend-pro/src/requestErrorConfig.ts` 的 `errorThrower` 要求 `success` 为真，
否则整页回退到演示数据。所以**所有** `/api/*` 响应都必须经过这里。

前端需要在 request 配置里加 `dataField: 'data'`，页面才能继续写 `result.items`。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..contracts.common import Page

#: 与前端 ErrorShowType 对齐：0 静默 / 1 警告 / 2 错误提示 / 3 通知 / 9 跳登录
SHOW_SILENT = 0
SHOW_WARN = 1
SHOW_ERROR = 2
SHOW_NOTIFICATION = 3
SHOW_REDIRECT = 9

SHOW_TYPE_BY_STATUS: Mapping[int, int] = {
    400: SHOW_ERROR,
    401: SHOW_REDIRECT,
    403: SHOW_ERROR,
    404: SHOW_WARN,
    409: SHOW_ERROR,
    413: SHOW_ERROR,
    422: SHOW_ERROR,
    429: SHOW_WARN,
    500: SHOW_NOTIFICATION,
}


def ok(data: Any = None) -> dict[str, Any]:
    """成功响应。`data` 会被前端 `dataField: 'data'` 解包。"""
    return {
        "success": True,
        "data": data,
        "errorCode": None,
        "errorMessage": None,
        "showType": SHOW_SILENT,
    }


def fail(code: str, message: str, *, http_status: int = 400) -> dict[str, Any]:
    return {
        "success": False,
        "data": None,
        "errorCode": code,
        "errorMessage": message,
        "showType": SHOW_TYPE_BY_STATUS.get(http_status, SHOW_ERROR),
    }


def list_response(
    items: Sequence[Any],
    *,
    next_cursor: str | None = None,
    total: int | None = None,
) -> dict[str, Any]:
    """列表统一形状 `{items: [...]}`。

    前端所有列表页都读 `result.items`；写成裸数组会导致整页回退 mock。
    """
    return ok({"items": list(items), "next_cursor": next_cursor, "total": total})


def page_response(page: Page[Any]) -> dict[str, Any]:
    return list_response(page.items, next_cursor=page.next_cursor, total=page.total)


__all__ = [
    "SHOW_ERROR",
    "SHOW_NOTIFICATION",
    "SHOW_REDIRECT",
    "SHOW_SILENT",
    "SHOW_WARN",
    "fail",
    "list_response",
    "ok",
    "page_response",
]
