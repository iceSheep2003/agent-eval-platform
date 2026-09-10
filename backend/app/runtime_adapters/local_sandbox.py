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
from typing import Any, AsyncIterator, Callable, Mapping

from ..contracts.execution import EntrypointReport
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


class _InvokeFailure(Exception):
    """被测代码失败。带**已产生的增量**——流到一半挂了，前面的字不能丢。"""

    def __init__(self, message: str, produced: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.produced = produced

    def to_result(self, started: float) -> InvokeResult:
        return InvokeResult(
            output=self.produced or None,
            error=self.message,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


async def _iterate(
    generator: AsyncIterator[Any], timeout_seconds: float
) -> AsyncIterator[str]:
    """带超时的异步生成器遍历。

    超时按**整体**算：`asyncio.timeout` 覆盖整个循环，而不是每段重置——
    否则一个持续吐字的 Agent 可以无限拖住一次调用。
    """
    produced: list[str] = []
    try:
        async with asyncio.timeout(timeout_seconds):
            async for piece in generator:
                text = _as_text(piece)
                if text:
                    produced.append(text)
                    yield text
    except asyncio.TimeoutError as exc:
        raise _InvokeFailure(f"执行超时（{timeout_seconds}s）", "".join(produced)) from exc
    except Exception as exc:  # noqa: BLE001 - 被测代码的异常要如实记录，不能吞
        logger.warning("被测函数流式执行时抛出异常: %r", exc)
        raise _InvokeFailure(
            f"{type(exc).__name__}: {exc}", "".join(produced)
        ) from exc


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    import json

    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _target_of(payload: Mapping[str, Any]) -> Callable[..., Any]:
    entrypoint = payload.get("__entrypoint__")
    if not entrypoint:
        raise EntrypointError("payload 缺少 __entrypoint__")
    return _resolve(str(entrypoint))


def _arguments_for(
    target: Callable[..., Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    """**只传公开输入**：payload 由 execution 构造，不含 expected_output。

    按签名过滤：对话调用会带上 `messages`，而多数被测函数只接受 `input`，
    全量透传会直接 TypeError。带 **kwargs 的函数仍然拿到全部键。
    """
    arguments = _public_arguments(target, payload)
    # 能力资产按需注入：被测函数没声明 `capabilities` 形参就不传，
    # 否则现有 Agent 的签名会被这个新参数打破。
    capabilities = payload.get("__capabilities__")
    if capabilities and "capabilities" in inspect.signature(target).parameters:
        arguments["capabilities"] = capabilities
    # 资源密钥同理：Agent 没声明 `secrets` 形参就不传，不会打破现有签名。
    secrets = payload.get("__secrets__")
    if secrets and "secrets" in inspect.signature(target).parameters:
        arguments["secrets"] = secrets
    return arguments


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
        target = _target_of(payload)
        arguments = _arguments_for(target, payload)
        started = time.perf_counter()

        # 异步生成器 entrypoint：非流式调用也要能用——把增量拼成完整输出。
        if inspect.isasyncgenfunction(target):
            try:
                chunks = [
                    piece
                    async for piece in _iterate(
                        target(**arguments), ctx.timeout_seconds
                    )
                ]
            except _InvokeFailure as failure:
                return failure.to_result(started)
            return InvokeResult(
                output="".join(chunks),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

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

    async def invoke_stream(
        self, handle: RuntimeHandle, payload: Mapping[str, Any], ctx: InvocationContext
    ) -> AsyncIterator[str]:
        """有增量就逐段吐，没有就整段吐一次。

        真正的增量只在 entrypoint 是**异步生成器**时存在；普通函数（含协程）
        拿不到中间态，退化成一段。
        """
        target = _target_of(payload)
        arguments = _arguments_for(target, payload)
        if inspect.isasyncgenfunction(target):
            async for piece in _iterate(target(**arguments), ctx.timeout_seconds):
                yield piece
            return
        result = await self.invoke(handle, payload, ctx)
        if result.error is not None:
            raise EntrypointError(result.error)
        yield _as_text(result.output)

    def probe(self, entrypoint: str) -> EntrypointReport:
        """import 进来 inspect 签名——**验收 Agent 是否符合开发规范**要用真实能力，
        不能靠 spec 里的声明。任何异常都收进 `error`，不抛。
        """
        try:
            target = _resolve(entrypoint)
        except Exception as exc:  # noqa: BLE001 - 探测失败要如实报告，不抛
            return EntrypointReport(
                entrypoint=entrypoint,
                importable=False,
                error=f"{type(exc).__name__}: {exc}",
            )

        try:
            parameters = inspect.signature(target).parameters
        except (TypeError, ValueError):
            return EntrypointReport(entrypoint=entrypoint, importable=True)

        return EntrypointReport(
            entrypoint=entrypoint,
            importable=True,
            accepts_input="input" in parameters,
            accepts_messages="messages" in parameters,
            accepts_secrets="secrets" in parameters,
            accepts_memory="memory" in parameters,
            accepts_kwargs=any(
                item.kind is inspect.Parameter.VAR_KEYWORD
                for item in parameters.values()
            ),
            is_async_generator=inspect.isasyncgenfunction(target),
            is_async=inspect.iscoroutinefunction(target),
        )

    async def teardown(self, handle: RuntimeHandle) -> None:
        return None
