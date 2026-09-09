"""Thin command-line wrapper around the Python API."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from pathlib import Path
from typing import Any

from .evaluation import rescore


def _load_object(spec: str) -> Any:
    if ":" not in spec:
        raise ValueError("对象必须使用 module:object 格式")
    module_name, object_name = spec.split(":", 1)
    value = getattr(importlib.import_module(module_name), object_name)
    return value() if isinstance(value, type) else value


def _cmd_test(args: argparse.Namespace) -> int:
    try:
        import pytest  # type: ignore
    except ImportError:
        print("agent-eval test 需要安装 pytest：python -m pip install 'agent-eval-sdk[pytest]'", file=sys.stderr)
        return 2
    return int(pytest.main(args.paths or ["."]))


def _cmd_score(args: argparse.Namespace) -> int:
    metrics = [_load_object(spec) for spec in args.metric]
    result = asyncio.run(rescore(args.run_dir, metrics=metrics))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.summary.fail_count == 0 and result.summary.metric_error_count == 0 else 1


def _cmd_inspect(args: argparse.Namespace) -> int:
    directory = Path(args.run_dir)
    summary_path = directory / "summary.json"
    if not summary_path.exists():
        print(f"找不到 {summary_path}", file=sys.stderr)
        return 2
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    scores_path = directory / "scores.jsonl"
    if scores_path.exists():
        failures = []
        for line in scores_path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            row = json.loads(line)
            failed = [score for score in row.get("scores", []) if score.get("status") in {"fail", "error"}]
            if failed:
                failures.append({"case_id": row.get("case_id"), "scores": failed})
        if failures:
            print("\nFailures:")
            print(json.dumps(failures, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-eval", description="Agent Evaluation SDK CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    test_parser = subparsers.add_parser("test", help="通过 pytest 发现并运行评测测试")
    test_parser.add_argument("paths", nargs="*", help="测试文件或目录")
    test_parser.set_defaults(handler=_cmd_test)

    score_parser = subparsers.add_parser("score", help="对已有 JSONL Run 重评分")
    score_parser.add_argument("run_dir")
    score_parser.add_argument("--metric", action="append", required=True, help="module:MetricClass")
    score_parser.set_defaults(handler=_cmd_score)

    inspect_parser = subparsers.add_parser("inspect", help="查看本地 Run 摘要和失败评分")
    inspect_parser.add_argument("run_dir")
    inspect_parser.set_defaults(handler=_cmd_inspect)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

