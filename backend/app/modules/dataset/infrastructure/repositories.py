"""dataset 仓储。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....contracts.common import (
    DatasetOrigin,
    DatasetPurpose,
    EvaluationStage,
    ItemValidation,
    TaskProtocol,
    TaskShape,
)
from ....shared.clock import ensure_aware
from ..domain.models import (
    Dataset,
    DatasetItem,
    DatasetSource,
    DatasetVersion,
    ImportIssue,
    ImportSession,
    PrivateTaskContext,
    TaskLimits,
    TaskSpec,
    ToolSpec,
)
from .tables import DatasetItemRow, DatasetRow, DatasetVersionRow, ImportSessionRow


def _dataset(row: DatasetRow) -> Dataset:
    return Dataset(
        id=row.id,
        workspace_id=row.workspace_id,
        name=row.name,
        description=row.description,
        owner_id=row.owner_id,
        origin=DatasetOrigin(row.origin),
        purpose=DatasetPurpose(row.purpose),
        task_shape=TaskShape(row.task_shape),
        stages=tuple(EvaluationStage(item) for item in (row.stages or [])),
        protocol=TaskProtocol(row.protocol),
        source=DatasetSource.from_dict(row.source),
        created_at=ensure_aware(row.created_at),
    )


def _version(row: DatasetVersionRow) -> DatasetVersion:
    return DatasetVersion(
        id=row.id,
        dataset_id=row.dataset_id,
        workspace_id=row.workspace_id,
        version_label=row.version_label,
        lifecycle=row.lifecycle,  # type: ignore[arg-type]
        item_count=row.item_count,
        content_digest=row.content_digest,
        created_by=row.created_by,
        created_at=ensure_aware(row.created_at),
        finalized_at=ensure_aware(row.finalized_at) if row.finalized_at else None,
    )


def _task_from_dict(raw: Mapping[str, Any]) -> TaskSpec:
    limits_raw = raw.get("limits")
    limits = (
        TaskLimits(
            max_steps=limits_raw.get("max_steps"),
            timeout_seconds=limits_raw.get("timeout_seconds"),
            max_cost_usd=limits_raw.get("max_cost_usd"),
        )
        if isinstance(limits_raw, Mapping)
        else None
    )
    return TaskSpec(
        instruction=str(raw.get("instruction") or ""),
        protocol=TaskProtocol(raw.get("protocol") or TaskProtocol.QA),
        context=dict(raw.get("context") or {}),
        tools=tuple(
            ToolSpec(
                name=str(tool.get("name")),
                description=str(tool.get("description") or ""),
                parameters=dict(tool.get("parameters") or {}),
            )
            for tool in (raw.get("tools") or ())
        ),
        limits=limits,
    )


def _private_from_dict(raw: Mapping[str, Any] | None) -> PrivateTaskContext | None:
    if not raw:
        return None
    return PrivateTaskContext(
        expected_output=raw.get("expected_output"),
        expected_actions=tuple(dict(item) for item in (raw.get("expected_actions") or ())),
        hidden_state=dict(raw.get("hidden_state") or {}),
        verifier=raw.get("verifier"),
    )


def _item(row: DatasetItemRow) -> DatasetItem:
    return DatasetItem(
        id=row.id,
        dataset_version_id=row.dataset_version_id,
        workspace_id=row.workspace_id,
        tenant_id=row.tenant_id,
        index=row.index,
        raw=dict(row.raw or {}),
        task=_task_from_dict(row.task or {}),
        private=_private_from_dict(row.private),
        validation=ItemValidation(row.validation),
        content_digest=row.content_digest,
        created_at=ensure_aware(row.created_at),
    )


def _session(row: ImportSessionRow) -> ImportSession:
    return ImportSession(
        id=row.id,
        dataset_id=row.dataset_id,
        workspace_id=row.workspace_id,
        filename=row.filename,
        status=row.status,  # type: ignore[arg-type]
        total_rows=row.total_rows,
        valid_rows=row.valid_rows,
        duplicate_rows=row.duplicate_rows,
        invalid_rows=row.invalid_rows,
        issues=tuple(
            ImportIssue(row=item.get("row", 0), code=item.get("code", ""), message=item.get("message", ""))
            for item in (row.issues or [])
        ),
        created_by=row.created_by,
        created_at=ensure_aware(row.created_at),
        applied_version_id=row.applied_version_id,
    )


class DatasetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, dataset_id: str, workspace_id: str) -> Dataset | None:
        stmt = select(DatasetRow).where(
            DatasetRow.id == dataset_id, DatasetRow.workspace_id == workspace_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _dataset(row) if row else None

    async def find_by_name(self, workspace_id: str, name: str) -> Dataset | None:
        stmt = select(DatasetRow).where(
            DatasetRow.workspace_id == workspace_id, DatasetRow.name == name
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _dataset(row) if row else None

    async def list_for_workspace(self, workspace_id: str) -> Sequence[Dataset]:
        stmt = (
            select(DatasetRow)
            .where(DatasetRow.workspace_id == workspace_id)
            .order_by(DatasetRow.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_dataset(row) for row in rows]

    def add(self, dataset: Dataset) -> None:
        self._session.add(
            DatasetRow(
                id=dataset.id,
                workspace_id=dataset.workspace_id,
                name=dataset.name,
                description=dataset.description,
                owner_id=dataset.owner_id,
                origin=dataset.origin.value,
                purpose=dataset.purpose.value,
                task_shape=dataset.task_shape.value,
                stages=[stage.value for stage in dataset.stages],
                protocol=dataset.protocol.value,
                source=dataset.source.as_dict() if dataset.source else None,
            )
        )


class DatasetVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, version_id: str, workspace_id: str) -> DatasetVersion | None:
        stmt = select(DatasetVersionRow).where(
            DatasetVersionRow.id == version_id, DatasetVersionRow.workspace_id == workspace_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _version(row) if row else None

    async def list_for_dataset(self, dataset_id: str) -> Sequence[DatasetVersion]:
        stmt = (
            select(DatasetVersionRow)
            .where(DatasetVersionRow.dataset_id == dataset_id)
            .order_by(DatasetVersionRow.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_version(row) for row in rows]

    async def find_draft(self, dataset_id: str) -> DatasetVersion | None:
        stmt = (
            select(DatasetVersionRow)
            .where(
                DatasetVersionRow.dataset_id == dataset_id,
                DatasetVersionRow.lifecycle == "draft",
            )
            .order_by(DatasetVersionRow.created_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _version(row) if row else None

    async def count_for_dataset(self, dataset_id: str) -> int:
        stmt = select(func.count()).select_from(DatasetVersionRow).where(
            DatasetVersionRow.dataset_id == dataset_id
        )
        return int((await self._session.execute(stmt)).scalar_one())

    def add(self, version: DatasetVersion) -> None:
        self._session.add(
            DatasetVersionRow(
                id=version.id,
                dataset_id=version.dataset_id,
                workspace_id=version.workspace_id,
                version_label=version.version_label,
                lifecycle=version.lifecycle,
                item_count=version.item_count,
                content_digest=version.content_digest,
                created_by=version.created_by,
            )
        )

    async def finalize(self, version_id: str, now: datetime, item_count: int, digest: str) -> None:
        await self._session.execute(
            update(DatasetVersionRow)
            .where(DatasetVersionRow.id == version_id)
            .values(
                lifecycle="finalized",
                finalized_at=now,
                item_count=item_count,
                content_digest=digest,
            )
        )


class DatasetItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, item_id: str, workspace_id: str) -> DatasetItem | None:
        stmt = select(DatasetItemRow).where(
            DatasetItemRow.id == item_id, DatasetItemRow.workspace_id == workspace_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _item(row) if row else None

    async def get_by_id(self, item_id: str) -> DatasetItem | None:
        """按 ID 取样本，不校验工作区——调用方（execution）已在自己的上下文里。"""
        row = await self._session.get(DatasetItemRow, item_id)
        return _item(row) if row else None

    async def list_page(
        self, version_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[Sequence[DatasetItem], int]:
        stmt = (
            select(DatasetItemRow)
            .where(DatasetItemRow.dataset_version_id == version_id)
            .order_by(DatasetItemRow.index)
            .limit(limit)
            .offset(offset)
        )
        count_stmt = select(func.count()).select_from(DatasetItemRow).where(
            DatasetItemRow.dataset_version_id == version_id
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        total = int((await self._session.execute(count_stmt)).scalar_one())
        return [_item(row) for row in rows], total

    async def find_by_digest(self, version_id: str, content_digest: str) -> DatasetItem | None:
        stmt = select(DatasetItemRow).where(
            DatasetItemRow.dataset_version_id == version_id,
            DatasetItemRow.content_digest == content_digest,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _item(row) if row else None

    async def count_by_validation(self, version_id: str) -> Mapping[str, int]:
        stmt = (
            select(DatasetItemRow.validation, func.count())
            .where(DatasetItemRow.dataset_version_id == version_id)
            .group_by(DatasetItemRow.validation)
        )
        rows = (await self._session.execute(stmt)).all()
        return {str(status): int(count) for status, count in rows}

    def add(self, item: DatasetItem) -> None:
        self._session.add(
            DatasetItemRow(
                id=item.id,
                dataset_version_id=item.dataset_version_id,
                workspace_id=item.workspace_id,
                tenant_id=item.tenant_id,
                index=item.index,
                raw=dict(item.raw),
                task=item.task.as_dict(),
                private=item.private.as_dict() if item.private else None,
                validation=item.validation.value,
                content_digest=item.content_digest,
            )
        )

    async def set_validation(self, item_id: str, validation: ItemValidation) -> None:
        await self._session.execute(
            update(DatasetItemRow)
            .where(DatasetItemRow.id == item_id)
            .values(validation=validation.value)
        )

    async def digests(self, version_id: str) -> Sequence[str]:
        stmt = select(DatasetItemRow.content_digest).where(
            DatasetItemRow.dataset_version_id == version_id
        )
        return list((await self._session.execute(stmt)).scalars().all())


class ImportSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, session_id: str, workspace_id: str) -> ImportSession | None:
        stmt = select(ImportSessionRow).where(
            ImportSessionRow.id == session_id, ImportSessionRow.workspace_id == workspace_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _session(row) if row else None

    async def list_for_dataset(self, dataset_id: str) -> Sequence[ImportSession]:
        stmt = (
            select(ImportSessionRow)
            .where(ImportSessionRow.dataset_id == dataset_id)
            .order_by(ImportSessionRow.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_session(row) for row in rows]

    def add(self, record: ImportSession) -> None:
        self._session.add(
            ImportSessionRow(
                id=record.id,
                dataset_id=record.dataset_id,
                workspace_id=record.workspace_id,
                filename=record.filename,
                status=record.status,
                total_rows=record.total_rows,
                valid_rows=record.valid_rows,
                duplicate_rows=record.duplicate_rows,
                invalid_rows=record.invalid_rows,
                issues=[
                    {"row": issue.row, "code": issue.code, "message": issue.message}
                    for issue in record.issues
                ],
                created_by=record.created_by,
            )
        )

    async def mark_applied(self, session_id: str, version_id: str) -> None:
        await self._session.execute(
            update(ImportSessionRow)
            .where(ImportSessionRow.id == session_id)
            .values(status="applied", applied_version_id=version_id)
        )
