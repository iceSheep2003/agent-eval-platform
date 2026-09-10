"""portal 的 HTTP DTO。字段名对齐展示平台前端的 `PortalHub` / `PortalAgent`。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PortalLoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PortalUserDTO(BaseModel):
    id: str
    username: str
    display_name: str
    email: str | None = None
    status: str = "active"


class SetPortalUserStatusRequest(BaseModel):
    """禁用/启用账号。禁用会**连带吊销该用户的全部会话**。"""

    status: Literal["active", "disabled"]


class PortalHubDTO(BaseModel):
    id: str
    slug: str
    name: str
    description: str
    my_role: str | None = None


class PortalSessionDTO(BaseModel):
    user: PortalUserDTO
    hubs: list[PortalHubDTO]


class ChannelViewDTO(BaseModel):
    channel: Literal["test", "livesh", "live"]
    label: str
    bound: bool
    version_id: str | None = None
    version_label: str | None = None


class PortalAgentDTO(BaseModel):
    id: str
    asset_id: str
    name: str
    display_name: str
    description: str
    lifecycle: str
    channels: list[ChannelViewDTO]


class PortalChatRequest(BaseModel):
    """对话请求。

    **同时兼容两种形状**：自己写的 `{message}`，以及 OpenAI 的
    `{messages:[...], stream:true}`——后者让前端可以直接用 `@ant-design/x-sdk`
    的 `OpenAIChatProvider`，不必自己写 SSE 解析。
    """

    message: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    stream: bool = False

    def resolved_message(self) -> str:
        if self.message.strip():
            return self.message
        for item in reversed(self.messages):
            if item.get("role") == "user" and item.get("content"):
                return str(item["content"])
        return ""


# -- 运营侧供给（平台账号调用） ---------------------------------------------


class CreatePortalUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=128)
    email: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=8, max_length=256)


class CreatePortalHubRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)


class AddHubMemberRequest(BaseModel):
    portal_user_id: str = Field(min_length=1, max_length=64)
    role: Literal["owner", "member"] = "member"


class AttachHubAgentRequest(BaseModel):
    asset_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=128)


class BindPortalChannelRequest(BaseModel):
    """把一把 `evl_` 部署密钥挂到某通道上。密钥本身由 asset 侧签发。"""

    deployment_credential_id: str = Field(min_length=1, max_length=64)
