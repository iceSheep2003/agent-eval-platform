"""失败 Trial → 回归样本。

这个用例天然跨模块（读 execution 的 Trial，写 dataset 的样本），所以放在**组合层的 HTTP 面**：
只做「取 Trial → 交给 dataset 用例」的编排，业务规则仍在 dataset 的领域里。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..container import Container
from ..contracts.errors import DomainError, Errors, NotFound
from ..contracts.identity import Permission
from ..schemas.response import ok
from .deps import Actor, assert_permission, get_container

router = APIRouter(tags=["improvement"])


class RegressionSampleRequest(BaseModel):
    dataset_id: str
    trial_id: str
    reason: str | None = Field(default=None, max_length=512)


@router.post("/regression-samples")
async def create_regression_sample(
    payload: RegressionSampleRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """把一次失败 Trial 沉淀成数据集草稿样本。

    样本以 `needs_review` 落库——期望结果要人工补，复核通过前不会进入固化版本。
    """
    assert_permission(container, actor, Permission.DATASET_IMPORT)
    trial = await container.runs.get_trial_ref(payload.trial_id, actor.workspace_id)
    if trial is None:
        raise NotFound("Trial", payload.trial_id)
    if trial.verdict is not None and trial.verdict.value == "pass":
        raise DomainError(
            Errors.VALIDATION_FAILED,
            "这条 Trial 是通过的，不需要沉淀为回归样本",
            verdict=trial.verdict.value,
        )

    item = await container.datasets.append_regression_sample(
        dataset_id=payload.dataset_id,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        trial=trial,
        reason=payload.reason,
    )
    return ok(
        {
            "item_id": item.id,
            "dataset_version_id": item.dataset_version_id,
            "validation": item.validation.value,
            "tenant_id": item.tenant_id,
            "instruction": item.task.instruction,
        }
    )
