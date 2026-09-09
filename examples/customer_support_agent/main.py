"""CLI entrypoint: run the customer-support agent and flush traces to a sink.

Platform upload (SDK 接入) — also pulls knowledge/skills/MCP via ``evk_`` key:
    EVAL_LOOM_BASE_URL=http://127.0.0.1:8787 \
    EVAL_LOOM_SDK_KEY=evk_... \
    python -m examples.customer_support_agent

Local offline (no backend needed):
    python -m examples.customer_support_agent --local
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from ._obs import JsonlSink, PlatformSink, configure
from .agent import configure_agent, support_agent
from .memory import Memory
from .platform import PlatformContext, fetch_platform_context

SAMPLE_QUERIES = (
    "请判断订单 A001 是否可以退款",
    "订单 A002 可以退款吗",
    "订单 A999 能退款吗",
    "退款政策是什么？几天内可以申请？",
)

DEFAULT_MEMORY = ".agent-eval/memory/customer-support.json"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the customer-support agent and flush traces")
    parser.add_argument("--local", action="store_true", help="write events to a local JSONL instead of the platform")
    parser.add_argument("--output-dir", default=None, help="JSONL output directory when --local")
    parser.add_argument("--memory", default=None, help="memory file path (default: transient; set to persist)")
    parser.add_argument("queries", nargs="*", help="queries to run (defaults to sample queries)")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> None:
    base = os.getenv("EVAL_LOOM_BASE_URL")
    key = os.getenv("EVAL_LOOM_SDK_KEY")
    if not args.local and base and key:
        sinks = [PlatformSink(base, key)]
        context = fetch_platform_context(base, key)
        where = f"platform {base}"
    else:
        out = Path(args.output_dir or ".agent-eval/runs/customer-support") / "events.jsonl"
        sinks = [JsonlSink(out)]
        context = PlatformContext()
        where = f"local {out}"
    configure(sinks=sinks)

    memory = Memory(args.memory) if args.memory else Memory()
    configure_agent(memory=memory, context=context)

    queries = list(args.queries) or list(SAMPLE_QUERIES)
    for query in queries:
        answer = await support_agent(query)
        print(f"Q: {query}\nA: {answer}\n")

    memory.save()
    print(
        f"Flushed {len(queries)} traces to {where}; "
        f"context: {len(context.knowledge)} KB / {len(context.skills)} skills / "
        f"{len(context.mcp_servers)} MCP servers"
    )


def main(argv: list[str] | None = None) -> None:
    asyncio.run(_run(_parse_args(argv)))


if __name__ == "__main__":
    main()