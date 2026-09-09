from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from agent_eval import (
    AnswerContains,
    EvaluationCase,
    MemorySink,
    PlatformSink,
    Score,
    TaskCompletion,
    evaluate,
    observe,
    rescore,
    span,
)


class SdkTests(unittest.IsolatedAsyncioTestCase):
    async def test_platform_sink_uses_agent_sdk_key(self) -> None:
        sink = PlatformSink("http://127.0.0.1:8787/", "evk_example")
        self.assertEqual(sink.url, "http://127.0.0.1:8787/v1/traces")
        self.assertEqual(sink.headers["Authorization"], "Bearer evk_example")
        with self.assertRaises(ValueError):
            PlatformSink("http://127.0.0.1:8787", "not-an-sdk-key")

    async def test_nested_sync_observe_and_rescore(self) -> None:
        @observe(kind="tool", name="lookup_order")
        def lookup(order_id: str) -> dict[str, str]:
            return {"order_id": order_id, "status": "refundable"}

        @observe(kind="agent", name="support_agent")
        def agent(question: str) -> str:
            result = lookup("A001")
            return "该订单可以退款。" if result["status"] == "refundable" else "不能退款。"

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "run"
            result = await evaluate(
                agent=agent,
                cases=[EvaluationCase(id="refund-001", input="能退款吗？")],
                metrics=[AnswerContains("可以退款"), TaskCompletion()],
                output_dir=output_dir,
            )
            self.assertEqual(result.summary.pass_rate, 1.0)
            self.assertEqual(result.summary.agent_success_count, 1)
            self.assertTrue((output_dir / "events.jsonl").exists())
            self.assertGreater(len(result.case_results[0].scores[0].evidence), 0)

            rescored = await rescore(output_dir, metrics=[AnswerContains("可以退款")])
            self.assertEqual(rescored.summary.pass_count, 1)

    async def test_async_context_isolated_for_concurrent_cases(self) -> None:
        @observe(kind="tool", name="echo")
        async def echo(value: str) -> str:
            await asyncio.sleep(0.005)
            return value

        @observe(kind="agent", name="echo_agent")
        async def agent(value: str) -> str:
            return await echo(value)

        result = await evaluate(
            agent=agent,
            cases=[EvaluationCase(id=f"case-{i}", input=f"value-{i}") for i in range(6)],
            metrics=[TaskCompletion()],
            concurrency=3,
        )
        self.assertEqual(result.summary.case_count, 6)
        self.assertEqual({item.output for item in result.case_results}, {f"value-{i}" for i in range(6)})
        self.assertTrue(all(item.trace_id for item in result.case_results))

    async def test_agent_error_does_not_stop_other_cases(self) -> None:
        def agent(value: str) -> str:
            if value == "bad":
                raise ValueError("bad input")
            return value

        result = await evaluate(
            agent=agent,
            cases=[EvaluationCase(id="ok", input="good"), EvaluationCase(id="bad", input="bad")],
            metrics=[TaskCompletion()],
        )
        statuses = {item.case_id: item.status for item in result.case_results}
        self.assertEqual(statuses, {"ok": "success", "bad": "error"})
        self.assertEqual(result.summary.agent_error_count, 1)

    async def test_custom_metric_and_memory_sink(self) -> None:
        sink = MemorySink()

        @observe(kind="agent", name="tiny")
        async def agent(_: str) -> str:
            async with span(kind="llm", name="mock-model") as current:
                current.set_usage(input_tokens=2, output_tokens=3, total_tokens=5)
                return "ok"

        class IsOk:
            name = "is_ok"
            version = "1.0.0"
            scope = "case"

            async def score(self, target):
                return Score(self.name, self.version, target.output == "ok", "pass" if target.output == "ok" else "fail")

        result = await evaluate(
            agent=agent,
            cases=[EvaluationCase(id="one", input="x")],
            metrics=[IsOk()],
            sink=sink,
        )
        self.assertEqual(result.summary.pass_count, 1)
        self.assertTrue(any(event.event_type == "span_finished" for event in sink.events))

    async def test_tool_arguments_are_structured_and_large_values_use_artifact(self) -> None:
        @observe(kind="tool", name="lookup")
        def lookup(order_id: str) -> dict[str, str]:
            return {"order_id": order_id}

        @observe(kind="agent", name="agent")
        def agent(_: str) -> str:
            lookup("A-001")
            return "done"

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await evaluate(
                agent=agent,
                cases=[EvaluationCase(id="one", input="x")],
                metrics=[],
                output_dir=Path(temp_dir) / "run",
            )
            tool = result.case_results[0]
            self.assertEqual(tool.status, "success")
            event_lines = (Path(temp_dir) / "run" / "events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertTrue(any('"event_type":"tool_called"' in line for line in event_lines))


if __name__ == "__main__":
    unittest.main()
