"""展示平台领域实体。

**这是另一个产品的数据模型**，与平台 `identity` 的账号体系无关：
平台账号是内部运营者，portal 账号是外部使用者。两者唯一的接触面是
`PortalAgentChannel.deployment_credential_id`——它指向 asset 的一把 `evl_` 密钥，
用来按通道调用已发布版本。

项目归属工作区（因为它展示的 Agent 属于某个工作区），但**成员是 portal 用户**。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ....contracts.common import Channel, Id

#: 项目角色。`owner` 管成员与挂载，`member` 只能看和对话。
#: 两者当前的**权限点集合相同**（展示平台只读+对话），差别在结构上先留好。
ProjectRole = Literal["owner", "member"]

PortalUserStatus = Literal["active", "disabled"]
ProjectStatus = Literal["active", "archived"]


#: 连续失败多少次后锁定账号，以及锁多久。
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


@dataclass(frozen=True, slots=True)
class PortalUser:
    """展示平台账号。明文密码不落库，只存 argon2id 哈希。"""

    id: Id
    username: str
    email: str | None
    display_name: str
    password_hash: str
    status: PortalUserStatus
    created_at: datetime
    #: 连续失败次数与锁定截止时间——抵挡密码暴力破解。
    failed_attempts: int = 0
    locked_until: datetime | None = None

    def is_locked(self, now: datetime) -> bool:
        return self.locked_until is not None and now < self.locked_until


@dataclass(frozen=True, slots=True)
class PortalSession:
    """登录会话。库里只存 token 的 sha256。"""

    id: Id
    portal_user_id: Id
    token_hash: str
    expires_at: datetime
    last_seen_at: datetime
    created_at: datetime

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


@dataclass(frozen=True, slots=True)
class PortalProject:
    id: Id
    workspace_id: Id
    slug: str
    name: str
    description: str
    status: ProjectStatus
    created_by: Id
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ProjectMember:
    id: Id
    project_id: Id
    portal_user_id: Id
    role: ProjectRole
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ProjectAgent:
    """项目里挂的一个 Agent。`asset_id` 指向平台的资产，**不复制它的内容**。"""

    id: Id
    project_id: Id
    asset_id: Id
    display_name: str
    sort_order: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PortalAgentChannel:
    """项目 Agent 的某个通道用哪把部署密钥。

    只存**凭证引用**，不存密钥明文——撤销凭证即对话失效，与平台侧一致。
    """

    id: Id
    project_agent_id: Id
    channel: Channel
    deployment_credential_id: Id | None
    created_at: datetime
