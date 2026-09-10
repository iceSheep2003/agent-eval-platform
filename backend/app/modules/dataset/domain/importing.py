"""导入预检（纯函数，无 IO）。

预检必须在**落库之前**完成：结构错误、重复项、缺字段在这里拦下来，
避免脏样本进入数据集版本。用户看到的「预计样本数 / 重复项数」就是这里的输出。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from ....contracts.common import JsonValue, TaskProtocol
from ....shared.redaction import redact
from .models import (
    ImportIssue,
    PrivateTaskContext,
    TaskSpec,
    ToolSpec,
    item_digest,
)

#: 支持的输入形状（按优先级匹配）。
#: 1) 三段式：{"task": {...}, "private": {...}, "raw": {...}}
#: 2) 扁平式：{"input": ..., "expected_output": ...}
#: 3) 指令式：{"instruction": ..., "expected_output": ...}
_SIMPLE_KEYS = ("input", "question", "query")
_EXPECTED_KEYS = ("expected_output", "expected", "answer", "label")


@dataclass(frozen=True, slots=True)
class ParsedItem:
    index: int
    raw: Mapping[str, Any]
    task: TaskSpec
    private: PrivateTaskContext | None
    digest: str


@dataclass(frozen=True, slots=True)
class PreflightResult:
    items: tuple[ParsedItem, ...]
    total_rows: int
    duplicate_rows: int
    invalid_rows: int
    issues: tuple[ImportIssue, ...]

    @property
    def valid_rows(self) -> int:
        return len(self.items)

    def summary(self) -> dict[str, JsonValue]:
        return {
            "total_rows": self.total_rows,
            "valid_rows": self.valid_rows,
            "duplicate_rows": self.duplicate_rows,
            "invalid_rows": self.invalid_rows,
        }


def preflight(
    records: Iterable[Mapping[str, Any]],
    *,
    protocol: TaskProtocol = TaskProtocol.QA,
) -> PreflightResult:
    """把原始记录转成样本，并报告重复与无效。

    重复判定用 `task + private` 的摘要，而不是整行——同一道题换了无关元数据
    不该被当成新样本。
    """
    items: list[ParsedItem] = []
    issues: list[ImportIssue] = []
    seen: dict[str, int] = {}
    duplicates = 0
    invalid = 0
    total = 0

    for index, record in enumerate(records):
        total += 1
        raw = dict(record)
        try:
            task, private = _to_task_and_private(raw, protocol)
        except ValueError as exc:
            invalid += 1
            issues.append(ImportIssue(row=index, code="invalid_row", message=str(exc)))
            continue

        digest = item_digest(task, private)
        if digest in seen:
            duplicates += 1
            issues.append(
                ImportIssue(
                    row=index,
                    code="duplicate",
                    message=f"与第 {seen[digest]} 行内容重复",
                )
            )
            continue

        seen[digest] = index
        items.append(
            ParsedItem(
                index=len(items),
                raw=raw,
                task=task,
                private=private,
                digest=digest,
            )
        )

    return PreflightResult(
        items=tuple(items),
        total_rows=total,
        duplicate_rows=duplicates,
        invalid_rows=invalid,
        issues=tuple(issues),
    )


def _to_task_and_private(
    raw: Mapping[str, Any], protocol: TaskProtocol
) -> tuple[TaskSpec, PrivateTaskContext | None]:
    if "task" in raw and isinstance(raw["task"], Mapping):
        return _from_structured(raw, protocol)

    instruction = _first_present(raw, _SIMPLE_KEYS)
    if instruction is None:
        raise ValueError(
            f"缺少输入字段：需要 {'/'.join(_SIMPLE_KEYS)} 之一，或使用 task/private 结构"
        )
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("输入必须是非空字符串")

    expected = _first_present(raw, _EXPECTED_KEYS)
    private = PrivateTaskContext(expected_output=expected) if expected is not None else None
    context = raw.get("context")
    return (
        TaskSpec(
            instruction=instruction,
            protocol=protocol,
            context=dict(context) if isinstance(context, Mapping) else {},
        ),
        private,
    )


def _from_structured(
    raw: Mapping[str, Any], protocol: TaskProtocol
) -> tuple[TaskSpec, PrivateTaskContext | None]:
    task_raw = raw["task"]
    instruction = task_raw.get("instruction") or task_raw.get("input")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("task.instruction 必须是非空字符串")

    tools: list[ToolSpec] = []
    for tool in task_raw.get("tools") or ():
        if not isinstance(tool, Mapping) or not tool.get("name"):
            raise ValueError("task.tools 每项必须包含 name")
        tools.append(
            ToolSpec(
                name=str(tool["name"]),
                description=str(tool.get("description") or ""),
                parameters=dict(tool.get("parameters") or {}),
            )
        )

    task = TaskSpec(
        instruction=instruction,
        protocol=TaskProtocol(task_raw.get("protocol") or protocol),
        context=dict(task_raw.get("context") or {}),
        tools=tuple(tools),
    )

    private_raw = raw.get("private")
    private: PrivateTaskContext | None = None
    if isinstance(private_raw, Mapping):
        private = PrivateTaskContext(
            expected_output=private_raw.get("expected_output"),
            expected_actions=tuple(
                dict(item) for item in (private_raw.get("expected_actions") or ())
            ),
            hidden_state=dict(private_raw.get("hidden_state") or {}),
            verifier=private_raw.get("verifier"),
        )
    return task, private


def _first_present(raw: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in raw:
            return raw[key]
    return None


def sanitized_raw(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    """保真存储前先脱敏——原始样本里可能混着 token / cookie。"""
    # adapter 输出用 {raw, task, private} 包装。数据库的 raw 应保留
    # benchmark 原始样本，而不是再包一层平台投影。
    source = raw.get("raw") if isinstance(raw.get("raw"), Mapping) else raw
    return dict(redact(source))
