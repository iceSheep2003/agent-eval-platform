"""asset 模块的 ORM 表。表名统一 `asset_` 前缀（表所有权约定）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ....persistence.base import Base, TimestampMixin


class AssetRow(Base, TimestampMixin):
    __tablename__ = "asset_asset"
    __table_args__ = (
        UniqueConstraint("workspace_id", "kind", "name", name="uq_asset_name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    lifecycle: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    connect_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tenant_scope: Mapped[str] = mapped_column(String(24), nullable=False, default="workspace_shared")
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: **软删除**。归档的 Agent 不再出现在列表里，但历史 Run / Trace / 评分全部保留——
    #: 评测平台的价值一半在「当时为什么这么判」，硬删等于把证据也删了。
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AssetVersionRow(Base, TimestampMixin):
    __tablename__ = "asset_version"
    __table_args__ = (
        UniqueConstraint("asset_id", "version_label", name="uq_version_label"),
        UniqueConstraint("asset_id", "spec_digest", name="uq_version_digest"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("asset_asset.id"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version_label: Mapped[str] = mapped_column(String(32), nullable=False)
    spec: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    spec_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)

    asset: Mapped["AssetRow"] = relationship()


class ChannelBindingRow(Base, TimestampMixin):
    __tablename__ = "asset_channel_binding"
    __table_args__ = (UniqueConstraint("asset_id", "channel", name="uq_channel"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("asset_asset.id"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bound_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    asset: Mapped["AssetRow"] = relationship()


class AssetBindingRow(Base, TimestampMixin):
    """消费方（Agent）→ 能力资产（Skill / MCP / 知识库）的引用。

    **不复制资源内容**，只存指针；`resolve_mode` 决定指针怎么解析成具体版本。
    """

    __tablename__ = "asset_binding"
    __table_args__ = (
        UniqueConstraint(
            "consumer_asset_id",
            "provider_asset_id",
            "consumer_version_id",
            name="uq_binding_consumer_provider_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    consumer_asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: NULL = 该 Agent 的**所有**版本共用这条绑定。
    consumer_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider_asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: 冗余判别列：按类型反查「谁在用 MCP」时不用回表。
    provider_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    #: channel | pinned
    resolve_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="channel")
    provider_channel: Mapped[str | None] = mapped_column(String(16), nullable=True)
    provider_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: workspace_shared | tenant_id
    tenant_scope: Mapped[str] = mapped_column(String(64), nullable=False, default="workspace_shared")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)


class CredentialRow(Base, TimestampMixin):
    __tablename__ = "asset_credential"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    asset_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    #: 部署凭证限定的通道；SDK 上报密钥为 NULL。
    channel: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    #: sha256；明文只在创建响应里出现一次
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    last_four: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ArtifactRow(Base, TimestampMixin):
    __tablename__ = "asset_artifact"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    version_label: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    build_status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")


class ResourceSecretRow(Base, TimestampMixin):
    """资源密钥的**密文**。明文只在写入那一刻存在于内存里。

    与 `asset_credential` 的分工：
    - `asset_credential` 是**平台发给外部的凭证**（`evk_`/`evl_`），只存哈希、不可还原；
    - 本表是**Agent 运行时要用的密钥**（LLM Key、MCP Token），必须可还原，故加密。
    """

    __tablename__ = "asset_resource_secret"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: Agent 版本 spec 里 `secrets[].name` 引用的名字，如 `llm_api_key`。
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    #: Fernet 密文。主密钥不进数据库，泄露库也解不开。
    ciphertext: Mapped[str] = mapped_column(String(1024), nullable=False)
    #: 短指纹，用于日志与展示「用的是哪一把」，不可反推明文。
    fingerprint: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)


class SecretBindingRow(Base, TimestampMixin):
    """Agent 版本 × 通道 → 用哪把密钥。

    **指针**：值（`asset_resource_secret`）可变、可轮换，指针可回滚。
    与 `asset_binding`（能力资产引用）是同一个形状——都是「不可变版本里的引用，
    在调用时解析成当前值」。
    """

    __tablename__ = "asset_secret_binding"
    __table_args__ = (
        UniqueConstraint(
            "asset_version_id", "channel", "secret_name", name="uq_secret_binding"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    asset_version_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: test | liversh | live
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    secret_name: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_secret_id: Mapped[str] = mapped_column(String(64), nullable=False)
    bound_by: Mapped[str] = mapped_column(String(64), nullable=False)
