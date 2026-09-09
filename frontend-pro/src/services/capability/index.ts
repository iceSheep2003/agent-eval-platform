import { call, withWorkspace } from '@/services/eval/http';

/**
 * 能力资产（Skill / MCP / 知识库）管理接口。
 *
 * 与 `services/evolution` 分开：那套是概览页的只读读模型，这套是管理面。
 * **通道与版本是两个概念**——`channels` 只给指针（谁指向哪个版本），
 * 版本详情走 `versions`。后端 §6.4 专门警告过这两者不能混成一个字段。
 */

/** 后端规范值。页面上的 `knowledge` 是历史字面量，接口层会翻译。 */
export type CapabilityKind = 'skill' | 'mcp' | 'knowledge_base';
export type ChannelName = 'test' | 'livesh' | 'live';
export type VersionLifecycle =
  | 'draft'
  | 'evaluating'
  | 'ready'
  | 'blocked'
  | 'retired';

export type AssetChannel = {
  channel: ChannelName;
  version_id: string | null;
  version_label: string | null;
  bound_at: string | null;
  bound_by: string | null;
};

export type CapabilityVersion = {
  id: string;
  version_label: string;
  lifecycle: VersionLifecycle;
  spec: Record<string, unknown>;
  created_by: string;
  created_at: string;
};

export type CapabilityAsset = {
  id: string;
  kind: CapabilityKind;
  name: string;
  description: string;
  owner: string;
  lifecycle: string;
  tenant_scope: string;
  tenant_id: string | null;
  version_count: number;
  binding_count: number;
  created_at: string;
  updated_at: string | null;
  latest_version: CapabilityVersion | null;
  channels: AssetChannel[];
};

export type CapabilityBinding = {
  id: string;
  consumer_asset_id: string;
  consumer_asset_name: string | null;
  consumer_version_id: string | null;
  provider_asset_id: string;
  provider_kind: CapabilityKind;
  resolve_mode: 'channel' | 'pinned';
  provider_channel: ChannelName | null;
  provider_version_id: string | null;
  resolved_version_id: string | null;
  resolved_version_label: string | null;
  tenant_scope: string;
  created_at: string;
};

export type ResourceMetrics = {
  asset_id: string;
  version_id: string;
  window_hours: number;
  kind: CapabilityKind;
  invocations: number;
  error_count: number;
  error_rate: number;
  p95_latency_ms: number | null;
  cost_usd: number;
  /** 口径名：mcp → tool_success_rate、knowledge_base → retriever_success_rate、skill → skill_completion_rate */
  success_metric: string | null;
  success_rate: number | null;
  /** 已归因 / 本应归因。掉下去说明匹配规则失效，不是资源变差了。 */
  attribution_coverage: number | null;
};

export type CreateCapabilityPayload = {
  kind: CapabilityKind;
  name: string;
  description?: string;
  spec: Record<string, unknown>;
  tenant_id?: string | null;
};

export type CapabilityValidation = {
  valid: boolean;
  issues: Array<{ path: string; code: string; message: string }>;
};

export type McpHealthCheck = {
  healthy: boolean;
  latency_ms: number | null;
  protocol_version?: string;
  checked_at: string;
  error?: string;
};

export type McpDiscovery = {
  tools: Array<{
    name: string;
    description: string;
    input_schema: Record<string, unknown>;
  }>;
  prompts?: Array<{ name: string; description?: string }>;
  resources?: Array<{ uri: string; name: string; mime_type?: string }>;
};

export type KnowledgeIndexRun = {
  run_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  queued_at?: string;
};

export type RetrievalTestResult = {
  query: string;
  latency_ms: number;
  matches: Array<{
    id: string;
    source_id: string;
    title?: string;
    content: string;
    score: number;
    metadata?: Record<string, unknown>;
  }>;
};

export const listCapabilityAssets = (workspaceId: string, kind: CapabilityKind) =>
  call<{ items: CapabilityAsset[] }>('/api/v1/assets', {
    params: { kind },
    ...withWorkspace(workspaceId),
  });

export const getCapabilityAsset = (workspaceId: string, assetId: string) =>
  call<CapabilityAsset>(`/api/v1/assets/${assetId}`, withWorkspace(workspaceId));

export const createCapabilityAsset = (
  workspaceId: string,
  payload: CreateCapabilityPayload,
) =>
  call<CapabilityAsset>('/api/v1/assets', {
    method: 'POST',
    data: payload,
    ...withWorkspace(workspaceId),
  });

export const listCapabilityVersions = (workspaceId: string, assetId: string) =>
  call<{ items: CapabilityVersion[] }>(
    `/api/v1/assets/${assetId}/versions`,
    withWorkspace(workspaceId),
  );

export const createCapabilityVersion = (
  workspaceId: string,
  assetId: string,
  payload: { spec: Record<string, unknown>; version_label?: string },
) =>
  call<CapabilityVersion>(`/api/v1/assets/${assetId}/versions`, {
    method: 'POST',
    data: payload,
    ...withWorkspace(workspaceId),
  });

export const listProviderBindings = (workspaceId: string, assetId: string) =>
  call<{ items: CapabilityBinding[] }>(
    `/api/v1/assets/${assetId}/bindings`,
    withWorkspace(workspaceId),
  );

export const getResourceMetrics = (
  workspaceId: string,
  assetId: string,
  versionId: string,
  windowHours = 24,
) =>
  call<ResourceMetrics>(
    `/api/v1/assets/${assetId}/versions/${versionId}/metrics`,
    {
      params: { window_hours: windowHours },
      ...withWorkspace(workspaceId),
    },
  );

/** The endpoints below are the management-plane contract reserved for the backend. */
export const validateCapabilitySpec = (
  workspaceId: string,
  kind: CapabilityKind,
  spec: Record<string, unknown>,
) =>
  call<CapabilityValidation>('/api/v1/assets/validate', {
    method: 'POST',
    data: { kind, spec },
    ...withWorkspace(workspaceId),
  });

export const promoteCapabilityVersion = (
  workspaceId: string,
  assetId: string,
  versionId: string,
  payload: { channel: ChannelName; evidence_ids?: string[] },
) =>
  call<CapabilityAsset>(
    `/api/v1/assets/${assetId}/versions/${versionId}/promote`,
    { method: 'POST', data: payload, ...withWorkspace(workspaceId) },
  );

export const checkMcpConnection = (
  workspaceId: string,
  assetId: string,
  versionId: string,
) =>
  call<McpHealthCheck>(
    `/api/v1/assets/${assetId}/versions/${versionId}/mcp-health-checks`,
    { method: 'POST', ...withWorkspace(workspaceId) },
  );

export const discoverMcpCapabilities = (
  workspaceId: string,
  assetId: string,
  versionId: string,
) =>
  call<McpDiscovery>(
    `/api/v1/assets/${assetId}/versions/${versionId}/mcp-discovery`,
    { method: 'POST', ...withWorkspace(workspaceId) },
  );

export const rebuildKnowledgeIndex = (
  workspaceId: string,
  assetId: string,
  versionId: string,
) =>
  call<KnowledgeIndexRun>(
    `/api/v1/assets/${assetId}/versions/${versionId}/index-runs`,
    { method: 'POST', ...withWorkspace(workspaceId) },
  );

export const testKnowledgeRetrieval = (
  workspaceId: string,
  assetId: string,
  versionId: string,
  payload: { query: string; filters?: Record<string, unknown> },
) =>
  call<RetrievalTestResult>(
    `/api/v1/assets/${assetId}/versions/${versionId}/retrieval-tests`,
    { method: 'POST', data: payload, ...withWorkspace(workspaceId) },
  );
