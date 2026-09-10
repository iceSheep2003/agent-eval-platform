from __future__ import annotations

from backend.app.modules.dataset.domain.benchmarks import (
    AdapterLevel,
    Tau2DatasetAdapter,
    compatibility_for,
    list_benchmark_adapters,
)


def test_catalog_distinguishes_adapter_levels_and_readiness() -> None:
    catalog = {adapter.manifest.id: adapter for adapter in list_benchmark_adapters()}
    assert set(catalog) == {"mmlu", "tau2", "terminal-bench", "browsergym", "swe-bench"}
    assert catalog["mmlu"].manifest.level is AdapterLevel.DIRECT
    assert catalog["mmlu"].manifest.adapter_protocol is None
    assert catalog["swe-bench"].manifest.level is AdapterLevel.VERIFIER
    assert catalog["terminal-bench"].manifest.level is AdapterLevel.INTERACTIVE
    assert compatibility_for(catalog["tau2"]).importable is True
    assert compatibility_for(catalog["tau2"]).runnable is False
    assert compatibility_for(catalog["swe-bench"]).importable is False


def test_tau2_materializer_keeps_native_record_and_hides_verifier() -> None:
    source = {
        "id": "case-1",
        "description": {"purpose": "check refund policy"},
        "user_scenario": {
            "instructions": {
                "domain": "airline",
                "reason_for_call": "Cancel reservation ABC123",
                "known_info": "user id is u-1",
            }
        },
        "initial_state": {"reservation": "active"},
        "evaluation_criteria": {
            "actions": [{"name": "cancel_reservation", "arguments": {"id": "ABC123"}}],
            "reward_basis": ["DB", "COMMUNICATE"],
        },
    }
    row = Tau2DatasetAdapter().materialize([source], domain="airline")[0]
    assert row["raw"] == source
    assert row["task"]["instruction"] == "Cancel reservation ABC123"
    assert "evaluation_criteria" not in row["task"]
    assert row["private"]["verifier"] == "tau2:evaluate_task"
    assert row["private"]["hidden_state"]["evaluation_criteria"]["reward_basis"] == [
        "DB",
        "COMMUNICATE",
    ]
