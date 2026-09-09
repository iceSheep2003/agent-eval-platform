"""dataset 的 HTTP 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile

from ....api.deps import Actor, assert_permission, get_container
from ....container import Container
from ....contracts.common import ItemValidation
from ....contracts.errors import DomainError, Errors
from ....contracts.identity import Permission
from ....schemas.response import list_response, ok
from ..application.services import DatasetService, ImportOutcome
from ..domain.models import Dataset, DatasetItem, DatasetVersion, ImportSession
from .schemas import (
    CreateDatasetRequest,
    DatasetDTO,
    DatasetItemDTO,
    DatasetVersionDTO,
    ImportSessionDTO,
    ReviewItemRequest,
)

router = APIRouter(tags=["dataset"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


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
