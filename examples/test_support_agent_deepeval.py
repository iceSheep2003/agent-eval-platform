"""DeepEval smoke test for the instrumented example Agent.

Run with:

    python -m pip install -e '.[deepeval]'
    deepeval test run examples/test_support_agent_deepeval.py

The test is intentionally kept separate from ``tests/test_sdk.py`` because it
uses DeepEval's own trace lifecycle and metric runner.
"""

from __future__ import annotations

import pytest

pytest.importorskip("deepeval", reason="install the optional [deepeval] extra to run this smoke test")

from deepeval import assert_test
from deepeval.dataset import Golden
from deepeval.metrics import TaskCompletionMetric

from examples.support_agent_deepeval import customer_support_agent


def test_refund_answer() -> None:
    golden = Golden(
        input="请判断订单 A001 是否可以退款",
        expected_output="订单 A001 可以退款，金额为 ¥249.00。",
    )
    customer_support_agent(golden.input)
    assert_test(golden=golden, metrics=[TaskCompletionMetric(threshold=0.5)])
