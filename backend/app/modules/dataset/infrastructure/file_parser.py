"""导入文件解析：JSON / JSONL / CSV → 记录列表。

只做「格式 → 记录」的转换，**不做业务校验**——校验是 `domain/importing.preflight` 的事。
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Mapping, Sequence

from ....contracts.errors import DomainError, Errors

JSON_SUFFIXES = (".json",)
JSONL_SUFFIXES = (".jsonl", ".ndjson")
CSV_SUFFIXES = (".csv",)
MAX_ROWS = 100_000


def parse_file(filename: str, content: bytes) -> Sequence[Mapping[str, Any]]:
    lowered = filename.lower()
    if lowered.endswith(JSONL_SUFFIXES):
        return _parse_jsonl(content)
    if lowered.endswith(JSON_SUFFIXES):
        return _parse_json(content)
    if lowered.endswith(CSV_SUFFIXES):
        return _parse_csv(content)
    raise DomainError(
        Errors.IMPORT_VALIDATION_FAILED,
        f"不支持的文件类型：{filename}；支持 {JSON_SUFFIXES + JSONL_SUFFIXES + CSV_SUFFIXES}",
    )


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DomainError(Errors.IMPORT_VALIDATION_FAILED, "文件编码无法识别（试过 utf-8 / gb18030）")


def _ensure_records(rows: Any, source: str) -> list[Mapping[str, Any]]:
    if not isinstance(rows, list):
        raise DomainError(Errors.IMPORT_VALIDATION_FAILED, f"{source} 顶层必须是数组")
    if len(rows) > MAX_ROWS:
        raise DomainError(
            Errors.IMPORT_VALIDATION_FAILED, f"样本数 {len(rows)} 超过上限 {MAX_ROWS}"
        )
    records: list[Mapping[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise DomainError(Errors.IMPORT_VALIDATION_FAILED, f"{source} 每行必须是对象")
        records.append(dict(row))
    return records


def _parse_jsonl(content: bytes) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = []
    for number, line in enumerate(_decode(content).splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DomainError(
                Errors.IMPORT_VALIDATION_FAILED, f"第 {number} 行不是合法 JSON：{exc.msg}"
            ) from exc
        if not isinstance(parsed, Mapping):
            raise DomainError(Errors.IMPORT_VALIDATION_FAILED, f"第 {number} 行不是对象")
        records.append(dict(parsed))
    if len(records) > MAX_ROWS:
        raise DomainError(
            Errors.IMPORT_VALIDATION_FAILED, f"样本数 {len(records)} 超过上限 {MAX_ROWS}"
        )
    return records


def _parse_json(content: bytes) -> list[Mapping[str, Any]]:
    try:
        parsed = json.loads(_decode(content))
    except json.JSONDecodeError as exc:
        raise DomainError(Errors.IMPORT_VALIDATION_FAILED, f"不是合法 JSON：{exc.msg}") from exc
    # 允许 {"items": [...]} 或 {"cases": [...]} 包裹
    if isinstance(parsed, Mapping):
        for key in ("items", "cases", "samples", "data"):
            if isinstance(parsed.get(key), list):
                parsed = parsed[key]
                break
    return _ensure_records(parsed, "JSON")


def _parse_csv(content: bytes) -> list[Mapping[str, Any]]:
    reader = csv.DictReader(io.StringIO(_decode(content)))
    if not reader.fieldnames:
        raise DomainError(Errors.IMPORT_VALIDATION_FAILED, "CSV 缺少表头")
    records = [dict(row) for row in reader]
    if len(records) > MAX_ROWS:
        raise DomainError(
            Errors.IMPORT_VALIDATION_FAILED, f"样本数 {len(records)} 超过上限 {MAX_ROWS}"
        )
    return records
