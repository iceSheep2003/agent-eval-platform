"""DeepEval smoke test for the SDK-instrumented customer-support agent.

Run with:

    python -m pip install -e '.[deepeval]'
    deepeval test run examples/test_customer_support_agent.py
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("deepeval", reason="install the [deepeval] extra to run this smoke test")

from deepeval import assert_test
from deepeval.dataset import Golden
from deepeval.metrics import TaskCompletionMetric

from examples.customer_support_agent import support_agent


def test_refund_answer() -> None:
    golden = Golden(
        input="请判断订单 A001 是否可以退款",
        expected_output="订单 A001 可以退款，金额为 ¥249.00。已为您提交退款申请。",
    )
    asyncio.run(support_agent(golden.input))
    assert_test(golden=golden, metrics=[TaskCompletionMetric(threshold=0.5)])