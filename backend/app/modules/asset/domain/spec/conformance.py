"""Agent 开发规范：**能不能被平台托管**，而不只是「能不能跑起来」。

`agent.py` 校验的是 spec 自身的自洽性（必填字段、端口范围）。这里校验的是
**Agent 与平台的契约**——平台要按通道调用它、注入密钥、注入记忆、做流式，
Agent 必须按约定暴露入口。

分两段：
- `check_spec(...)`：纯静态，冻结版本前就能跑；
- `check_entrypoint(...)`：需要真的 import 进来看签名，由调用方注入探针。

**为什么要有这个**：没有它，每个 Agent 都会长出自己的调用协议，平台只能
靠适配层一个个绕（`customer_support_agent` 的 `platform_entry` 就是被迫绕的）。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .....contracts.common import ValidationIssue, ValidationResult
from .....contracts.execution import EntrypointReport

#: 平台注入的形参名。Agent 想接就必须叫这些名字——改名等于换协议。
REQUIRED_PARAMS = ("input",)
OPTIONAL_PARAMS = ("messages", "secrets", "memory", "capabilities")

#: 这些 key 一旦出现在 spec 里，说明有人把明文密钥写进了不可变版本。
_PLAINTEXT_KEYS = ("password", "token", "api_key", "apikey", "secret", "access_key")

#: memory 的作用域声明。`stateless` 是显式的，不是「忘了写」。
MEMORY_SCOPES = ("thread", "tenant", "agent_version", "stateless")


def check_spec(spec: Mapping[str, Any]) -> ValidationResult:
    """静态检查：冻结版本前就能做的那些。"""
    issues: list[ValidationIssue] = []
    connect_type = spec.get("connect_type")

    # 1. 密钥必须是引用，不能是明文
    for path, key, _ in _walk(spec):
        if key.lower() in _PLAINTEXT_KEYS and not _looks_like_ref(path):
            issues.append(
                ValidationIssue(
                    path,
                    "plaintext_secret",
                    "版本不可变，密钥必须写 secret_ref；明文一旦冻结就再也换不掉",
                )
            )

    # 2. 用了密钥就必须声明成 secret_ref
    for index, item in enumerate(_as_list(spec.get("secrets"))):
        if not isinstance(item, Mapping):
            issues.append(ValidationIssue(f"secrets[{index}]", "invalid", "应为对象"))
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            issues.append(
                ValidationIssue(f"secrets[{index}].name", "missing", "密钥必须有名字")
            )
        elif _looks_like_ref(str(name)):
            # 用户把「引用语法」写进了 name——他把 name 当成了值。
            issues.append(
                ValidationIssue(
                    f"secrets[{index}].name",
                    "not_a_name",
                    f"这里应写密钥的**名字**（如 llm_api_key），不是引用 {name!r}",
                )
            )

    # 3. memory 必须显式声明作用域
    #
    # **只对平台托管的 Agent 要求**：`sdk` 接入的 Agent 自己跑、自己管记忆，
    # 平台只收它的 Trace，替它规定记忆作用域是多余的门槛。
    memory = spec.get("memory")
    if connect_type == "sdk":
        return ValidationResult.success() if not issues else ValidationResult.failure(*issues)
    if memory is None:
        issues.append(
            ValidationIssue(
                "memory",
                "missing",
                '必须声明记忆作用域：{"scope": "thread" | "tenant" | "agent_version" | "stateless"}',
            )
        )
    elif not isinstance(memory, Mapping):
        issues.append(ValidationIssue("memory", "invalid", "应为对象"))
    elif memory.get("scope") not in MEMORY_SCOPES:
        issues.append(
            ValidationIssue(
                "memory.scope",
                "invalid",
                f"应为 {MEMORY_SCOPES} 之一，收到 {memory.get('scope')!r}",
            )
        )

    # 4. 能力必须走引用，不能内联
    for field in ("skills", "mcp_servers", "knowledge_bases"):
        if field in spec and spec[field] is not None and not isinstance(spec[field], list):
            issues.append(ValidationIssue(field, "invalid", "应为列表（元素是资产引用）"))

    return ValidationResult.success() if not issues else ValidationResult.failure(*issues)


def check_entrypoint(
    report: EntrypointReport,
    *,
    connect_type: str | None = None,
    require_streaming: bool = False,
) -> ValidationResult:
    """运行时检查：Agent 的入口是否符合平台调用协议。

    `connect_type="sdk"` 的版本没有 entrypoint（走 SDK 上报），跳过。
    """
    if connect_type == "sdk":
        return ValidationResult.success()

    issues: list[ValidationIssue] = []

    if not report.importable:
        issues.append(
            ValidationIssue(
                "entrypoint",
                "unimportable",
                f"无法加载 entrypoint：{report.error or '未知原因'}",
            )
        )
        return ValidationResult.failure(*issues)

    if not report.accepts_input:
        issues.append(
            ValidationIssue(
                "entrypoint.input",
                "missing_param",
                "入口必须接受 `input`——平台按这个形参传公开输入",
            )
        )

    if not report.accepts_messages and not report.accepts_kwargs:
        issues.append(
            ValidationIssue(
                "entrypoint.messages",
                "missing_param",
                "入口必须接受 `messages`（多轮上下文）或 **kwargs；"
                "否则展示平台的对话与评测的多轮样本都喂不进去",
            )
        )

    if require_streaming and not report.supports_streaming:
        issues.append(
            ValidationIssue(
                "entrypoint.stream",
                "not_async_generator",
                "绑到 LIVE 的版本必须是异步生成器，否则对话拿不到逐字输出",
            )
        )

    return ValidationResult.success() if not issues else ValidationResult.failure(*issues)


def _walk(node: Any, path: str = "") -> Sequence[tuple[str, str, Any]]:
    """遍历 spec 里所有 `(路径, key, value)`，用于按 key 名找明文密钥。"""
    found: list[tuple[str, str, Any]] = []
    if isinstance(node, Mapping):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            found.append((here, str(key), value))
            found.extend(_walk(value, here))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_walk(value, f"{path}[{index}]"))
    return found


def _looks_like_ref(path: str) -> bool:
    """这个位置是不是「引用」而非「值」。

    只认字段名以 `_ref` 结尾的形式（`secret_ref` / `token_ref`），
    避免把 `api_key: "sk-xxx"` 误判成合法引用。
    """
    leaf = path.rsplit(".", 1)[-1].split("[", 1)[0]
    return leaf.endswith("_ref")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]
