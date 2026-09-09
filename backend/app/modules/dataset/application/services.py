"""dataset 用例：创建数据集、导入预检、样本复核、版本固化、导出。

导入 → 草稿版本 → 复核 → 固化。**固化后的版本不可变**（需求说明 §9.3）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ....contracts.dataset import DatasetVersionRef
from ....contracts.common import (
    DatasetOrigin,
    DatasetPurpose,
    EvaluationStage,
    Id,
    ItemValidation,
    JsonValue,
    TaskProtocol,
    TaskShape,
)
from ....contracts.errors import DomainError, Errors, NotFound
from ....persistence import UnitOfWork
from ....persistence.database import Database
from ....shared.clock import Clock
from ....shared.ids import new_id
from ..domain.importing import PreflightResult, preflight, sanitized_raw
from ..domain.models import (
    Dataset,
    DatasetItem,
    DatasetSource,
    DatasetVersion,
    ImportSession,
)
from ..infrastructure.file_parser import parse_file
from ..infrastructure.repositories import (
    DatasetItemRepository,
    DatasetRepository,
    DatasetVersionRepository,
    ImportSessionRepository,
)

#: purpose → 默认适用阶段（可在创建时覆盖，见 docs/backend-dataset.md §2）
DEFAULT_STAGES: Mapping[DatasetPurpose, tuple[EvaluationStage, ...]] = {
    DatasetPurpose.CAPABILITY: (EvaluationStage.DEVELOPMENT,),
    DatasetPurpose.REGRESSION: (EvaluationStage.REGRESSION, EvaluationStage.RELEASE),
    DatasetPurpose.GATE: (EvaluationStage.RELEASE,),
    DatasetPurpose.MONITORING: (EvaluationStage.PRODUCTION,),
}


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    session: ImportSession
    version: DatasetVersion


class DatasetService:
    def __init__(self, database: Database, clock: Clock) -> None:
        self._db = database
        self._clock = clock

    # -- 数据集 --------------------------------------------------------------

    async def create_dataset(
        self,
        *,
        workspace_id: Id,
        owner_id: Id,
        name: str,
        description: str = "",
        origin: DatasetOrigin = DatasetOrigin.MANUAL,
        purpose: DatasetPurpose = DatasetPurpose.CAPABILITY,
        task_shape: TaskShape = TaskShape.SINGLE_TURN,
        stages: Sequence[EvaluationStage] | None = None,
        protocol: TaskProtocol = TaskProtocol.QA,
        source: Mapping[str, Any] | None = None,
    ) -> Dataset:
        resolved_stages = tuple(stages) if stages else DEFAULT_STAGES[purpose]
        if not resolved_stages:
            raise DomainError(Errors.VALIDATION_FAILED, "stages 不能为空")

        async with UnitOfWork(self._db) as uow:
            repo = DatasetRepository(uow.session)
            existing = await repo.find_by_name(workspace_id, name)
            if existing is not None:
                return existing
            dataset = Dataset(
                id=new_id("dataset"),
                workspace_id=workspace_id,
                name=name,
                description=description,
                owner_id=owner_id,
                origin=origin,
                purpose=purpose,
                task_shape=task_shape,
                stages=resolved_stages,
                protocol=protocol,
                source=DatasetSource.from_dict(source),
                created_at=self._clock.now(),
            )
            repo.add(dataset)
            await uow.commit()
        return dataset

    async def list_datasets(self, workspace_id: Id) -> Sequence[Dataset]:
        async with UnitOfWork(self._db) as uow:
            return list(await DatasetRepository(uow.session).list_for_workspace(workspace_id))

    async def get_dataset(self, dataset_id: Id, workspace_id: Id) -> Dataset:
        async with UnitOfWork(self._db) as uow:
            dataset = await DatasetRepository(uow.session).get(dataset_id, workspace_id)
        if dataset is None:
            raise NotFound("数据集", dataset_id)
        return dataset

    async def list_versions(self, dataset_id: Id, workspace_id: Id) -> Sequence[DatasetVersion]:
        await self.get_dataset(dataset_id, workspace_id)
        async with UnitOfWork(self._db) as uow:
            return list(await DatasetVersionRepository(uow.session).list_for_dataset(dataset_id))

    # -- 导入 ----------------------------------------------------------------

    async def import_file(
        self,
        *,
        dataset_id: Id,
        workspace_id: Id,
        actor_id: Id,
        filename: str,
        content: bytes,
        version_label: str | None = None,
    ) -> ImportOutcome:
        """解析 → 预检 → 落草稿版本。固化由 `finalize_version` 负责。"""
        dataset = await self.get_dataset(dataset_id, workspace_id)
        records = parse_file(filename, content)
        report: PreflightResult = preflight(records, protocol=dataset.protocol)

        now = self._clock.now()
        session = ImportSession(
            id=new_id("import_session"),
            dataset_id=dataset_id,
            workspace_id=workspace_id,
            filename=filename,
            status="validated",
            total_rows=report.total_rows,
            valid_rows=report.valid_rows,
            duplicate_rows=report.duplicate_rows,
            invalid_rows=report.invalid_rows,
            issues=report.issues[:500],  # 报告保留前 500 条，避免响应过大
            created_by=actor_id,
            created_at=now,
        )

        async with UnitOfWork(self._db) as uow:
            versions = DatasetVersionRepository(uow.session)
            existing = await versions.count_for_dataset(dataset_id)
            version = DatasetVersion(
                id=new_id("dataset_version"),
                dataset_id=dataset_id,
                workspace_id=workspace_id,
                version_label=version_label or _next_label(existing),
                lifecycle="draft",
                item_count=len(report.items),
                content_digest="",
                created_by=actor_id,
                created_at=now,
            )
            versions.add(version)
            await uow.session.flush()

            items = DatasetItemRepository(uow.session)
            for parsed in report.items:
                items.add(
                    DatasetItem(
                        id=new_id("sample"),
                        dataset_version_id=version.id,
                        workspace_id=workspace_id,
                        tenant_id=None,
                        index=parsed.index,
                        raw=sanitized_raw(parsed.raw),
                        task=parsed.task,
                        private=parsed.private,
                        validation=ItemValidation.VALID,
                        content_digest=parsed.digest,
                        created_at=now,
                    )
                )
            ImportSessionRepository(uow.session).add(session)
            await uow.commit()

        return ImportOutcome(session=session, version=version)

    async def list_imports(self, dataset_id: Id, workspace_id: Id) -> Sequence[ImportSession]:
        await self.get_dataset(dataset_id, workspace_id)
        async with UnitOfWork(self._db) as uow:
            return list(
                await ImportSessionRepository(uow.session).list_for_dataset(dataset_id)
            )

    # -- 样本与固化 -----------------------------------------------------------

    async def list_items(
        self, version_id: Id, workspace_id: Id, *, limit: int = 50, offset: int = 0
    ) -> tuple[Sequence[DatasetItem], int]:
        async with UnitOfWork(self._db) as uow:
            if await DatasetVersionRepository(uow.session).get(version_id, workspace_id) is None:
                raise NotFound("数据集版本", version_id)
            return await DatasetItemRepository(uow.session).list_page(
                version_id, limit=limit, offset=offset
            )

    async def review_item(
        self, item_id: Id, workspace_id: Id, validation: ItemValidation
    ) -> DatasetItem:
        async with UnitOfWork(self._db) as uow:
            items = DatasetItemRepository(uow.session)
            item = await items.get(item_id, workspace_id)
            if item is None:
                raise NotFound("样本", item_id)
            version = await DatasetVersionRepository(uow.session).get(
                item.dataset_version_id, workspace_id
            )
            if version is None:
                raise NotFound("数据集版本", item.dataset_version_id)
            if version.lifecycle != "draft":
                raise DomainError(
                    Errors.DATASET_VERSION_IMMUTABLE,
                    f"版本 {version.version_label} 已固化，样本不可修改",
                )
            await items.set_validation(item_id, validation)
            await uow.commit()
        return await self._reload_item(item_id, workspace_id)

    async def finalize_version(
        self, version_id: Id, workspace_id: Id
    ) -> DatasetVersion:
        """固化：要求没有待复核样本，否则拒绝——避免半成品被当成正式基线。"""
        async with UnitOfWork(self._db) as uow:
            versions = DatasetVersionRepository(uow.session)
            version = await versions.get(version_id, workspace_id)
            if version is None:
                raise NotFound("数据集版本", version_id)
            if version.lifecycle == "finalized":
                return version
            if version.lifecycle != "draft":
                raise DomainError(
                    Errors.RUN_STATE_CONFLICT, f"版本状态 {version.lifecycle} 不允许固化"
                )

            items = DatasetItemRepository(uow.session)
            counts = await items.count_by_validation(version_id)
            pending = counts.get(ItemValidation.NEEDS_REVIEW.value, 0)
            if pending:
                raise DomainError(
                    Errors.IMPORT_VALIDATION_FAILED,
                    f"还有 {pending} 条样本待复核，先处理完再固化",
                    pending=pending,
                )
            digests = sorted(await items.digests(version_id))
            from ....shared.canonical_json import digest as _digest

            await versions.finalize(
                version_id, self._clock.now(), len(digests), _digest(digests)
            )
            await uow.commit()
        return await self.get_version(version_id, workspace_id)

    async def get_version_ref(
        self, version_id: Id, workspace_id: Id
    ) -> DatasetVersionRef | None:
        """实现 `contracts.dataset.DatasetQueryPort`：投影 + 所属数据集的用途/阶段。"""
        async with UnitOfWork(self._db) as uow:
            version = await DatasetVersionRepository(uow.session).get(version_id, workspace_id)
            if version is None:
                return None
            dataset = await DatasetRepository(uow.session).get(version.dataset_id, workspace_id)
        if dataset is None:
            return None
        return DatasetVersionRef(
            id=version.id,
            dataset_id=dataset.id,
            workspace_id=version.workspace_id,
            version_label=version.version_label,
            purpose=dataset.purpose,
            task_shape=dataset.task_shape,
            stages=dataset.stages,
            item_count=version.item_count,
            finalized=version.lifecycle == "finalized",
        )

    async def get_version(self, version_id: Id, workspace_id: Id) -> DatasetVersion:
        async with UnitOfWork(self._db) as uow:
            version = await DatasetVersionRepository(uow.session).get(version_id, workspace_id)
        if version is None:
            raise NotFound("数据集版本", version_id)
        return version

    async def export_version(
        self, version_id: Id, workspace_id: Id
    ) -> Sequence[Mapping[str, JsonValue]]:
        """按版本导出（不是「当前数据集」）——历史结果才能复现。"""
        await self.get_version(version_id, workspace_id)
        async with UnitOfWork(self._db) as uow:
            items, _ = await DatasetItemRepository(uow.session).list_page(
                version_id, limit=100_000, offset=0
            )
        return [
            {
                "index": item.index,
                "task": item.task.as_dict(),
                "private": item.private.as_dict() if item.private else None,
                "validation": item.validation.value,
            }
            for item in items
        ]

    async def _reload_item(self, item_id: Id, workspace_id: Id) -> DatasetItem:
        async with UnitOfWork(self._db) as uow:
            item = await DatasetItemRepository(uow.session).get(item_id, workspace_id)
        if item is None:
            raise NotFound("样本", item_id)
        return item


def _next_label(existing: int) -> str:
    return "1.0.0" if existing == 0 else f"1.0.{existing}"
