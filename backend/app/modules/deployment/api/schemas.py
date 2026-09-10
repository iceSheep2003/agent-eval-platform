"""deployment 的 HTTP DTO。字段名对齐前端 `EvalAgentDetail.instances[]`。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..domain.models import Instance


class StartInstanceRequest(BaseModel):
    channel: Literal["liversh", "live"]
    #: 生产发布的高风险动作要二次确认（占位实现，见架构文档 §5.1.5）
    confirm: bool = False


class InstanceDTO(BaseModel):
    id: str
    asset_id: str
    asset_version_id: str
    channel: str
    status: str
    runtime_type: str
    endpoint: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    stopped_at: datetime | None = None


class InstanceActionDTO(BaseModel):
    instance: InstanceDTO
    message: str


def instance_dto(instance: Instance) -> InstanceDTO:
    return InstanceDTO(
        id=instance.id,
        asset_id=instance.asset_id,
        asset_version_id=instance.asset_version_id,
        channel=instance.channel.value,
        status=instance.state.value,
        runtime_type=instance.runtime_type,
        endpoint=instance.endpoint,
        error=instance.error,
        started_at=instance.started_at,
        stopped_at=instance.stopped_at,
    )


def action_dto(instance: Instance, message: str) -> dict[str, Any]:
    return InstanceActionDTO(instance=instance_dto(instance), message=message).model_dump()
