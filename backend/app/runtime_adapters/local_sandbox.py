"""本地确定性 Runtime：在进程内按 entrypoint 调用被测函数。

**只用于开发与测试**——它不提供任何隔离（无容器、无网络限制、无资源限额）。
生产用 `RUNTIME_BACKEND=kubernetes` 换成真正的沙箱。这样 `RuntimePort` 的消费者
（execution）完全不用改。
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import time
from typing import Any, Callable, Mapping

from ..modules.execution.application.ports import (
    InvocationContext,
    InvokeResult,
    RuntimeHandle,
    RuntimeSpec,
)

logger = logging.getLogger(__name__)


class EntrypointError(RuntimeError):
    """entrypoint 无法解析或调用失败。"""


def _public_arguments(
    target: Callable[..., Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    """只保留被测函数真正接受的参数（`__` 开头的内部键一律丢弃）。"""
    public = {key: value for key, value in payload.items() if not key.startswith("__")}
    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError):  # 内建/无法内省的 callable：原样透传
        return public
    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return public
    return {key: value for key, value in public.items() if key in signature.parameters}


def _resolve(entrypoint: str) -> Callable[..., Any]:
    if ":" not in entrypoint:
        raise EntrypointError(f"entrypoint 必须是 'module.path:callable'，收到 {entrypoint!r}")
    module_path, _, attribute = entrypoint.partition(":")
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise EntrypointError(f"无法导入 {module_path}：{exc}") from exc
    target = getattr(module, attribute, None)
    if target is None or not callable(target):
        raise EntrypointError(f"{module_path} 里没有可调用的 {attribute}")
    return target


class LocalSandboxRuntime:
    """满足 `execution.application.ports.RuntimePort`。"""

    async def provision(self, spec: RuntimeSpec, ctx: InvocationContext) -> RuntimeHandle:
        if not spec.entrypoint:
            raise EntrypointError(
                f"版本 {spec.asset_version_id} 没有 entrypoint，本地沙箱无法启动"
            )
        return RuntimeHandle(
            id=f"local:{spec.asset_version_id}",
            asset_version_id=spec.asset_version_id,
            ephemeral=True,
        )

    async def invoke(
        self, handle: RuntimeHandle, payload: Mapping[str, Any], ctx: InvocationContext
    ) -> InvokeResult:
        entrypoint = payload.get("__entrypoint__")
        if not entrypoint:
            raise EntrypointError("payload 缺少 __entrypoint__")
        target = _resolve(str(entrypoint))

        # **只传公开输入**：payload 由 execution 构造，不含 expected_output。
        # 按签名过滤：对话调用会带上 `messages`，而多数被测函数只接受 `input`，
        # 全量透传会直接 TypeError。带 **kwargs 的函数仍然拿到全部键。
        arguments = _public_arguments(target, payload)
        started = time.perf_counter()
        try:
            if inspect.iscoroutinefunction(target):
                output = await asyncio.wait_for(
                    target(**arguments), timeout=ctx.timeout_seconds
                )
            else:
                output = await asyncio.wait_for(
                    asyncio.to_thread(target, **arguments), timeout=ctx.timeout_seconds
                )
        except asyncio.TimeoutError:
            return InvokeResult(
                output=None,
                error=f"执行超时（{ctx.timeout_seconds}s）",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001 - 被测代码的异常要如实记录，不能吞
            logger.warning("被测函数抛出异常: %r", exc)
            return InvokeResult(
                output=None,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        return InvokeResult(
            output=output,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    async def teardown(self, handle: RuntimeHandle) -> None:
        return None
