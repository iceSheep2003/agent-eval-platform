"""Benchmark 适配协议与平台内置注册表。

注册表只描述平台确实能力范围内的适配状态；不安装、也不在 API
进程中执行上游 benchmark 代码。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable, Mapping, Protocol, Sequence

from ....contracts.common import JsonValue, TaskProtocol

BENCHMARK_ADAPTER_PROTOCOL_VERSION = "benchmark-adapter/v1"


class AdapterLevel(StrEnum):
    #: 静态 QA/分类/工具调用数据，可直接转换，不需要环境生命周期。
    DIRECT = "direct"
    VERIFIER = "verifier"
    INTERACTIVE = "interactive"


@dataclass(frozen=True, slots=True)
class BenchmarkManifest:
    id: str
    name: str
    benchmark_version: str
    adapter: str
    adapter_version: str
    adapter_protocol: str | None
    level: AdapterLevel
    task_protocol: TaskProtocol
    domains: tuple[str, ...]
    splits: tuple[str, ...]
    upstream_uri: str
    license: str
    description: str
    native_metric: str
    verifier: str | None
    storage_uri: str

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "id": self.id,
            "name": self.name,
            "benchmark_version": self.benchmark_version,
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "adapter_protocol": self.adapter_protocol,
            "level": self.level.value,
            "task_protocol": self.task_protocol.value,
            "domains": list(self.domains),
            "splits": list(self.splits),
            "upstream_uri": self.upstream_uri,
            "license": self.license,
            "description": self.description,
            "native_metric": self.native_metric,
            "verifier": self.verifier,
            "storage_uri": self.storage_uri,
        }


class DatasetBenchmarkAdapter(Protocol):
    """Level 1 协议：上游样本 -> 平台三段式样本。"""

    manifest: BenchmarkManifest

    def materialize(
        self, records: Iterable[Mapping[str, Any]], *, domain: str
    ) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class AdapterCompatibility:
    compatible: bool
    importable: bool
    runnable: bool
    missing_capabilities: tuple[str, ...]
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "compatible": self.compatible,
            "importable": self.importable,
            "runnable": self.runnable,
            "missing_capabilities": list(self.missing_capabilities),
            "notes": list(self.notes),
        }


class Tau2DatasetAdapter:
    """τ²/τ³ 数据集适配器。

    v1.0.0 上游已将项目更新为 τ³，但保留 ``tau2`` Python 包名。
    这里固定 tag，保证同一数据集版本可重现。
    """

    manifest = BenchmarkManifest(
        id="tau2",
        name="τ²-bench / τ³-bench",
        benchmark_version="1.0.0",
        adapter="backend.app.modules.dataset.domain.benchmarks:Tau2DatasetAdapter",
        adapter_version="1.0.0",
        adapter_protocol=BENCHMARK_ADAPTER_PROTOCOL_VERSION,
        level=AdapterLevel.INTERACTIVE,
        task_protocol=TaskProtocol.AGENTIC,
        domains=("airline", "retail", "telecom", "banking_knowledge", "mock"),
        splits=("base",),
        upstream_uri="https://github.com/sierra-research/tau2-bench/tree/v1.0.0",
        license="MIT",
        description="真实领域中的工具调用、Agent 与模拟用户交互评测。",
        native_metric="reward (DB × COMMUNICATE)",
        verifier="tau2 native evaluation criteria",
        storage_uri="benchmark-data://sources/tau2-bench/data/tau2/domains",
    )

    def materialize(
        self, records: Iterable[Mapping[str, Any]], *, domain: str
    ) -> Sequence[Mapping[str, Any]]:
        if domain not in self.manifest.domains:
            raise ValueError(f"tau2 不支持 domain={domain}")
        return tuple(self._materialize_one(record, domain=domain) for record in records)

    @staticmethod
    def _materialize_one(record: Mapping[str, Any], *, domain: str) -> Mapping[str, Any]:
        scenario = record.get("user_scenario") or {}
        instructions = scenario.get("instructions") or {}
        reason = str(instructions.get("reason_for_call") or "").strip()
        if not reason:
            raise ValueError(f"tau2 task {record.get('id', '?')} 缺少 reason_for_call")
        criteria = record.get("evaluation_criteria") or {}
        return {
            # 原样保留，便于日后用新 adapter 重新 materialize。
            "raw": dict(record),
            "task": {
                "instruction": reason,
                "protocol": TaskProtocol.AGENTIC.value,
                "context": {
                    "benchmark_task_id": str(record.get("id", "")),
                    "domain": domain,
                    "user_scenario": scenario,
                    "purpose": (record.get("description") or {}).get("purpose"),
                },
                "tools": [],
            },
            # 原生评分条件不进 Agent payload。
            "private": {
                "expected_actions": list(criteria.get("actions") or []),
                "hidden_state": {
                    "initial_state": record.get("initial_state"),
                    "evaluation_criteria": criteria,
                },
                "verifier": "tau2:evaluate_task",
            },
        }


class ManifestOnlyAdapter:
    """已纳入目录、但需要专用 verifier/环境的 benchmark。"""

    def __init__(self, manifest: BenchmarkManifest) -> None:
        self.manifest = manifest

    def materialize(
        self, records: Iterable[Mapping[str, Any]], *, domain: str
    ) -> Sequence[Mapping[str, Any]]:
        raise NotImplementedError(f"{self.manifest.id} 不是直接数据集适配")


_ADAPTERS: dict[str, DatasetBenchmarkAdapter] = {
    "mmlu": ManifestOnlyAdapter(
        BenchmarkManifest(
            id="mmlu",
            name="MMLU",
            benchmark_version="server-pinned",
            adapter="direct:csv-column-mapping",
            adapter_version="1",
            # 静态选择题只需要列映射，不应强制实现交互协议。
            adapter_protocol=None,
            level=AdapterLevel.DIRECT,
            task_protocol=TaskProtocol.QA,
            domains=("57-subjects",),
            splits=("dev", "validation", "test"),
            upstream_uri="https://github.com/hendrycks/test",
            license="MIT",
            description="57 个学科的多任务语言理解选择题基准。",
            native_metric="accuracy",
            verifier=None,
            storage_uri="benchmark-data://datasets/mmlu/all",
        )
    ),
    "tau2": Tau2DatasetAdapter(),
    "terminal-bench": ManifestOnlyAdapter(
        BenchmarkManifest(
            id="terminal-bench",
            name="Terminal-Bench",
            benchmark_version="0.1.1",
            adapter="agent_eval_benchmarks.terminal_bench:Adapter",
            adapter_version="0.1.0",
            adapter_protocol=BENCHMARK_ADAPTER_PROTOCOL_VERSION,
            level=AdapterLevel.INTERACTIVE,
            task_protocol=TaskProtocol.AGENTIC,
            domains=("terminal",),
            splits=("terminal-bench-core",),
            upstream_uri="https://github.com/laude-institute/terminal-bench",
            license="Apache-2.0",
            description="终端环境中的端到端 Agent 任务，使用容器与原生测试脚本验证。",
            native_metric="task pass rate",
            verifier="terminal-bench native tests",
            storage_uri="benchmark-data://sources/terminal-bench",
        )
    ),
    "browsergym": ManifestOnlyAdapter(
        BenchmarkManifest(
            id="browsergym",
            name="BrowserGym",
            benchmark_version="server-pinned",
            adapter="agent_eval_benchmarks.browsergym:Adapter",
            adapter_version="0.1.0",
            adapter_protocol=BENCHMARK_ADAPTER_PROTOCOL_VERSION,
            level=AdapterLevel.INTERACTIVE,
            task_protocol=TaskProtocol.AGENTIC,
            domains=("miniwob", "webarena", "webarena_verified", "visualwebarena", "assistantbench", "openapps", "timewarp"),
            splits=("benchmark-default",),
            upstream_uri="https://github.com/ServiceNow/BrowserGym",
            license="Apache-2.0",
            description="浏览器 Agent 统一环境，承载 WebArena、MiniWoB 等多个 benchmark。",
            native_metric="benchmark-native reward",
            verifier="browsergym task.validate",
            storage_uri="benchmark-data://sources/BrowserGym",
        )
    ),
    "swe-bench": ManifestOnlyAdapter(
        BenchmarkManifest(
            id="swe-bench",
            name="SWE-bench",
            benchmark_version="server-pinned",
            adapter="agent_eval_benchmarks.swe_bench:Adapter",
            adapter_version="0.1.0",
            adapter_protocol=BENCHMARK_ADAPTER_PROTOCOL_VERSION,
            level=AdapterLevel.VERIFIER,
            task_protocol=TaskProtocol.AGENTIC,
            domains=("verified", "lite", "full"),
            splits=("test", "dev"),
            upstream_uri="https://github.com/SWE-bench/SWE-bench",
            license="MIT",
            description="真实 GitHub issue 驱动的仓库级软件修复评测。",
            native_metric="resolved rate",
            verifier="swebench.harness",
            storage_uri="benchmark-data://datasets/swe-bench",
        )
    ),
}


def list_benchmark_adapters() -> tuple[DatasetBenchmarkAdapter, ...]:
    return tuple(_ADAPTERS.values())


def get_benchmark_adapter(benchmark_id: str) -> DatasetBenchmarkAdapter | None:
    return _ADAPTERS.get(benchmark_id)


def compatibility_for(adapter: DatasetBenchmarkAdapter) -> AdapterCompatibility:
    manifest = adapter.manifest
    protocol_ok = manifest.level is AdapterLevel.DIRECT or (
        manifest.adapter_protocol == BENCHMARK_ADAPTER_PROTOCOL_VERSION
    )
    missing: list[str] = []
    notes: list[str] = []
    # 当前只有 tau2 的 Level-1 materializer；目录中其他项不充数。
    importable = protocol_ok and manifest.id == "tau2"
    runnable = protocol_ok and manifest.level is AdapterLevel.DIRECT and importable
    if not importable:
        missing.append("dataset_materializer")
        notes.append("服务器已存放上游快照，尚未实现平台样本转换器")
    if manifest.level is AdapterLevel.VERIFIER:
        runnable = False
        missing.append("native_verifier")
        notes.append("运行时必须使用 benchmark 原生 verifier")
    elif manifest.level is AdapterLevel.INTERACTIVE:
        runnable = False
        missing.append("interactive_benchmark_harness")
        notes.append("运行时需要 benchmark 环境生命周期与原生 verifier")
    if not protocol_ok:
        missing.append(BENCHMARK_ADAPTER_PROTOCOL_VERSION)
    return AdapterCompatibility(
        compatible=protocol_ok,
        importable=importable,
        runnable=runnable,
        missing_capabilities=tuple(missing),
        notes=tuple(notes),
    )


def tau2_tasks_url(domain: str) -> str:
    adapter = _ADAPTERS["tau2"]
    if domain not in adapter.manifest.domains:
        raise ValueError(f"tau2 不支持 domain={domain}")
    return (
        "https://raw.githubusercontent.com/sierra-research/tau2-bench/"
        f"v{adapter.manifest.benchmark_version}/data/tau2/domains/{domain}/tasks.json"
    )
