"""知识库版本 spec 的校验与摘要。

知识库常是**租户级**资产（`tenant_scope=tenant_bound`）：每个租户的政策文档不同，不能跨租户检索。
`index_name` 与 `sources[].id` 是归因锚点——检索 span 靠它们匹配回具体版本。
"""

from __future__ import annotations

from typing import Any, Mapping

from .....contracts.common import AssetKind, ValidationIssue, ValidationResult
from .....shared.canonical_json import digest as _digest

MIN_TOP_K = 1


def validate(spec: Mapping[str, Any]) -> ValidationResult:
    issues: list[ValidationIssue] = []

    kind = spec.get("kind")
    if kind != AssetKind.KNOWLEDGE_BASE.value:
        issues.append(
            ValidationIssue("kind", "invalid_kind", f"应为 knowledge_base，收到 {kind!r}")
        )

    for field in ("embedding_model", "index_name"):
        value = spec.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(ValidationIssue(field, "missing", "不能为空"))

    chunk = spec.get("chunk_strategy")
    if chunk is None:
        issues.append(ValidationIssue("chunk_strategy", "missing", "必须声明分块策略"))
    elif not isinstance(chunk, Mapping):
        issues.append(ValidationIssue("chunk_strategy", "invalid", "应为对象"))
    else:
        size = chunk.get("size")
        overlap = chunk.get("overlap")
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            issues.append(ValidationIssue("chunk_strategy.size", "range", "分块大小至少为 1"))
        if not isinstance(overlap, int) or isinstance(overlap, bool) or overlap < 0:
            issues.append(ValidationIssue("chunk_strategy.overlap", "range", "重叠不能为负"))
        elif isinstance(size, int) and not isinstance(size, bool) and overlap >= size:
            issues.append(
                ValidationIssue("chunk_strategy.overlap", "range", "重叠必须小于分块大小")
            )

    retrieval = spec.get("retrieval")
    if retrieval is None:
        issues.append(ValidationIssue("retrieval", "missing", "必须声明检索配置"))
    elif not isinstance(retrieval, Mapping):
        issues.append(ValidationIssue("retrieval", "invalid", "应为对象"))
    else:
        top_k = retrieval.get("top_k")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < MIN_TOP_K:
            issues.append(ValidationIssue("retrieval.top_k", "range", f"至少 {MIN_TOP_K}"))

    sources = spec.get("sources")
    if not isinstance(sources, (list, tuple)) or not sources:
        issues.append(ValidationIssue("sources", "missing", "至少提供一个知识来源"))
    else:
        seen: set[str] = set()
        enabled_count = 0
        for index, source in enumerate(sources):
            field = f"sources[{index}]"
            if not isinstance(source, Mapping):
                issues.append(ValidationIssue(field, "invalid", "应为对象"))
                continue
            source_id = source.get("id")
            if not isinstance(source_id, str) or not source_id.strip():
                issues.append(ValidationIssue(f"{field}.id", "missing", "来源必须有稳定 id"))
            elif source_id in seen:
                issues.append(ValidationIssue(f"{field}.id", "duplicate", f"来源 id {source_id} 重复"))
            else:
                seen.add(source_id)
            uri = source.get("uri")
            if not isinstance(uri, str) or not uri.strip():
                issues.append(ValidationIssue(f"{field}.uri", "missing", "来源必须有 uri"))
            if source.get("enabled") is True:
                enabled_count += 1
        if sources and enabled_count == 0:
            issues.append(ValidationIssue("sources", "all_disabled", "至少启用一个知识来源"))

    return ValidationResult.success() if not issues else ValidationResult.failure(*issues)


def digest(spec: Mapping[str, Any]) -> str:
    return _digest(dict(spec))
