"""dataset 的 HTTP 路由。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, UploadFile

from ....api.deps import Actor, assert_permission, get_container
from ....container import Container
from ....contracts.common import ItemValidation
from ....contracts.common import DatasetOrigin, DatasetPurpose, TaskShape
from ....contracts.errors import DomainError, Errors
from ....contracts.identity import Permission
from ....schemas.response import list_response, ok
from ..application.services import DatasetService, ImportOutcome
from ..domain.models import Dataset, DatasetItem, DatasetVersion, ImportSession
from ..domain.benchmarks import (
    compatibility_for,
    get_benchmark_adapter,
    list_benchmark_adapters,
    tau2_tasks_url,
)
from .schemas import (
    CreateDatasetRequest,
    DatasetDTO,
    DatasetItemDTO,
    DatasetVersionDTO,
    ImportSessionDTO,
    PullBenchmarkRequest,
    ReviewItemRequest,
)

router = APIRouter(tags=["dataset"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_BENCHMARK_BYTES = 50 * 1024 * 1024


def _load_json(path: Path) -> list[dict[str, Any]]:
    """只从配置的 benchmark 数据根目录读，API 请求不直连公网。"""
    with path.open("rb") as source:
        content = source.read(MAX_BENCHMARK_BYTES + 1)
    if len(content) > MAX_BENCHMARK_BYTES:
        raise DomainError(Errors.IMPORT_VALIDATION_FAILED, "benchmark 数据超过 50 MiB")
    decoded = json.loads(content)
    if not isinstance(decoded, list) or not all(isinstance(item, dict) for item in decoded):
        raise DomainError(Errors.IMPORT_VALIDATION_FAILED, "benchmark 上游数据不是对象数组")
    return decoded


def get_dataset_service(container: Annotated[Container, Depends(get_container)]) -> DatasetService:
    return container.datasets


def _dataset_dto(dataset: Dataset, version: DatasetVersion | None) -> DatasetDTO:
    return DatasetDTO(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        owner=dataset.owner_id,
        kind=dataset.origin.value,
        origin=dataset.origin.value,
        purpose=dataset.purpose.value,
        task_shape=dataset.task_shape.value,
        stages=[stage.value for stage in dataset.stages],
        protocol=dataset.protocol.value,
        source=dataset.source.as_dict() if dataset.source else None,
        version=version.version_label if version else None,
        item_count=version.item_count if version else 0,
        status=version.lifecycle if version else "draft",
    )


def _version_dto(version: DatasetVersion, current_id: str | None) -> DatasetVersionDTO:
    return DatasetVersionDTO(
        id=version.id,
        version=version.version_label,
        lifecycle=version.lifecycle,
        item_count=version.item_count,
        content_digest=version.content_digest,
        is_current=version.id == current_id,
        created_at=version.created_at,
        finalized_at=version.finalized_at,
    )


def _session_dto(session: ImportSession, version: DatasetVersion | None) -> ImportSessionDTO:
    return ImportSessionDTO(
        id=session.id,
        filename=session.filename,
        status=session.status,
        total_rows=session.total_rows,
        valid_rows=session.valid_rows,
        duplicate_rows=session.duplicate_rows,
        invalid_rows=session.invalid_rows,
        issues=[
            {"row": issue.row, "code": issue.code, "message": issue.message}
            for issue in session.issues
        ],
        version_id=version.id if version else None,
        created_at=session.created_at,
    )


def _item_dto(item: DatasetItem) -> DatasetItemDTO:
    return DatasetItemDTO(
        id=item.id,
        index=item.index,
        validation=item.validation.value,
        tenant_id=item.tenant_id,
        task=dict(item.task.as_dict()),
        private=item.private.as_dict() if item.private else None,
        raw=dict(item.raw),
    )


def _benchmark_dto(adapter: Any, root: Path | None) -> dict[str, Any]:
    item = adapter.manifest.as_dict()
    relative = str(adapter.manifest.storage_uri).removeprefix("benchmark-data://")
    available = bool(root and (root / relative).exists())
    compatible = compatibility_for(adapter).as_dict()
    compatible["importable"] = bool(compatible["importable"] and available)
    compatible["runnable"] = bool(compatible["runnable"] and available)
    if not available:
        compatible["missing_capabilities"] = [
            *compatible["missing_capabilities"],
            "server_dataset_snapshot",
        ]
    item["compatibility"] = compatible
    item["storage"] = {"uri": adapter.manifest.storage_uri, "available": available}
    return item


@router.get("/benchmarks")
async def list_benchmarks(
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """列出已注册 benchmark 及当前平台的真实适配状态。"""
    assert_permission(container, actor, Permission.DATASET_READ)
    items = [
        _benchmark_dto(adapter, container.settings.benchmark_data_root)
        for adapter in list_benchmark_adapters()
    ]
    return list_response(items, total=len(items))


@router.get("/benchmarks/{benchmark_id}")
async def get_benchmark(
    benchmark_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    assert_permission(container, actor, Permission.DATASET_READ)
    adapter = get_benchmark_adapter(benchmark_id)
    if adapter is None:
        raise DomainError(Errors.NOT_FOUND, f"benchmark {benchmark_id} 未注册")
    return ok(_benchmark_dto(adapter, container.settings.benchmark_data_root))


@router.post("/benchmarks/{benchmark_id}/pull")
async def pull_benchmark(
    benchmark_id: str,
    payload: PullBenchmarkRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> dict:
    """从固定版本的上游拉取任务，经 adapter 转换后落为平台草稿版本。

    拉取不会执行上游代码；原始记录保留在 ``item.raw``，原生评分
    条件只保存在 ``item.private``。
    """
    assert_permission(container, actor, Permission.DATASET_IMPORT)
    adapter = get_benchmark_adapter(benchmark_id)
    if adapter is None:
        raise DomainError(Errors.NOT_FOUND, f"benchmark {benchmark_id} 未注册")
    manifest = adapter.manifest
    if payload.domain not in manifest.domains:
        raise DomainError(
            Errors.VALIDATION_FAILED,
            f"{benchmark_id} 不支持 domain={payload.domain}",
        )
    if payload.split not in manifest.splits:
        raise DomainError(
            Errors.VALIDATION_FAILED,
            f"{benchmark_id} 不支持 split={payload.split}",
        )
    if benchmark_id != "tau2":
        raise DomainError(Errors.VALIDATION_FAILED, f"{benchmark_id} 尚未实现拉取器")

    url = tau2_tasks_url(payload.domain)
    root = container.settings.benchmark_data_root
    if root is None:
        raise DomainError(Errors.IMPORT_VALIDATION_FAILED, "未配置 benchmark 数据目录")
    source_file = root / "sources" / "tau2-bench" / "data" / "tau2" / "domains" / payload.domain / "tasks.json"
    try:
        upstream = await asyncio.to_thread(_load_json, source_file)
        selected = upstream[: payload.limit] if payload.limit else upstream
        records = adapter.materialize(selected, domain=payload.domain)
    except DomainError:
        raise
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise DomainError(
            Errors.IMPORT_VALIDATION_FAILED,
            f"读取 benchmark 失败（{source_file}）: {exc}",
        ) from exc

    source = {
        "benchmark_id": manifest.id,
        "benchmark_version": manifest.benchmark_version,
        "adapter": manifest.adapter,
        "adapter_version": manifest.adapter_version,
        "split": payload.split,
        "upstream_uri": url,
        "license": manifest.license,
    }
    dataset = await service.create_dataset(
        workspace_id=actor.workspace_id,
        owner_id=actor.user_id,
        name=payload.name or f"{manifest.name} / {payload.domain} / {payload.split}",
        description=payload.description or manifest.description,
        origin=DatasetOrigin.BENCHMARK,
        purpose=DatasetPurpose.CAPABILITY,
        task_shape=TaskShape.AGENTIC,
        protocol=manifest.task_protocol,
        source=source,
    )
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in records).encode()
    outcome = await service.import_file(
        dataset_id=dataset.id,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        filename=f"{benchmark_id}-{payload.domain}-{payload.split}.jsonl",
        content=content,
        version_label=payload.version_label or manifest.benchmark_version,
    )
    result = _dataset_dto(dataset, outcome.version).model_dump()
    result["import"] = _session_dto(outcome.session, outcome.version).model_dump()
    result["compatibility"] = compatibility_for(adapter).as_dict()
    return ok(result)


@router.post("/datasets")
async def create_dataset(
    payload: CreateDatasetRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> dict:
    assert_permission(container, actor, Permission.DATASET_CREATE)
    dataset = await service.create_dataset(
        workspace_id=actor.workspace_id,
        owner_id=actor.user_id,
        name=payload.name,
        description=payload.description,
        origin=payload.origin,
        purpose=payload.purpose,
        task_shape=payload.task_shape,
        stages=payload.stages,
        protocol=payload.protocol,
        source=payload.source,
    )
    versions = await service.list_versions(dataset.id, actor.workspace_id)
    return ok(_dataset_dto(dataset, versions[0] if versions else None).model_dump())


@router.get("/datasets")
async def list_datasets(
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> dict:
    assert_permission(container, actor, Permission.DATASET_READ)
    items = []
    for dataset in await service.list_datasets(actor.workspace_id):
        versions = await service.list_versions(dataset.id, actor.workspace_id)
        items.append(_dataset_dto(dataset, versions[0] if versions else None).model_dump())
    return list_response(items)


@router.get("/datasets/{dataset_id}")
async def get_dataset(
    dataset_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> dict:
    assert_permission(container, actor, Permission.DATASET_READ)
    dataset = await service.get_dataset(dataset_id, actor.workspace_id)
    versions = await service.list_versions(dataset_id, actor.workspace_id)
    return ok(_dataset_dto(dataset, versions[0] if versions else None).model_dump())


@router.get("/datasets/{dataset_id}/versions")
async def list_versions(
    dataset_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> dict:
    assert_permission(container, actor, Permission.DATASET_READ)
    versions = await service.list_versions(dataset_id, actor.workspace_id)
    current = versions[0].id if versions else None
    return list_response([_version_dto(item, current).model_dump() for item in versions])


@router.post("/datasets/{dataset_id}/imports")
async def import_file(
    dataset_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
    file: Annotated[UploadFile, File()],
    version_label: str | None = None,
) -> dict:
    """上传 → 预检 → 落草稿版本。返回预检报告（预计样本数 / 重复项数 / 无效项数）。"""
    assert_permission(container, actor, Permission.DATASET_IMPORT)
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise DomainError(Errors.IMPORT_VALIDATION_FAILED, "文件超过 20 MiB")
    outcome: ImportOutcome = await service.import_file(
        dataset_id=dataset_id,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        filename=file.filename or "upload",
        content=content,
        version_label=version_label,
    )
    return ok(_session_dto(outcome.session, outcome.version).model_dump())


@router.get("/datasets/{dataset_id}/imports")
async def list_imports(
    dataset_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> dict:
    assert_permission(container, actor, Permission.DATASET_READ)
    sessions = await service.list_imports(dataset_id, actor.workspace_id)
    return list_response([_session_dto(item, None).model_dump() for item in sessions])


@router.get("/datasets/{dataset_id}/versions/{version_id}/items")
async def list_items(
    dataset_id: str,
    version_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    assert_permission(container, actor, Permission.DATASET_READ)
    items, total = await service.list_items(
        version_id, actor.workspace_id, limit=limit, offset=offset
    )
    return list_response([_item_dto(item).model_dump() for item in items], total=total)


@router.patch("/dataset-items/{item_id}")
async def review_item(
    item_id: str,
    payload: ReviewItemRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> dict:
    assert_permission(container, actor, Permission.DATASET_IMPORT)
    item = await service.review_item(
        item_id, actor.workspace_id, ItemValidation(payload.validation)
    )
    return ok(_item_dto(item).model_dump())


@router.post("/datasets/{dataset_id}/versions/{version_id}/finalize")
async def finalize_version(
    dataset_id: str,
    version_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> dict:
    assert_permission(container, actor, Permission.DATASET_VERSION_FINALIZE)
    version = await service.finalize_version(version_id, actor.workspace_id)
    return ok(_version_dto(version, version.id).model_dump())


@router.get("/datasets/{dataset_id}/versions/{version_id}/export")
async def export_version(
    dataset_id: str,
    version_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> dict:
    assert_permission(container, actor, Permission.DATASET_EXPORT)
    return ok({"items": list(await service.export_version(version_id, actor.workspace_id))})
