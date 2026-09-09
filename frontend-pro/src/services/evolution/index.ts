import { request } from '@umijs/max';

export type EvolutionAssetKind = 'skill' | 'mcp' | 'knowledge';
export type EvolutionLifecycle = 'test' | 'livesh' | 'live';
export type EvolutionActorType = 'agent' | 'human' | 'monitor';

export type EvolutionEvidence = {
  id: string;
  name: string;
  value: number;
  threshold: number;
  unit: 'score' | 'percent' | 'ms';
  passed: boolean;
};

export type EvolutionVersion = {
  id: string;
  version: string;
  lifecycle: EvolutionLifecycle;
  status: 'draft' | 'evaluating' | 'ready' | 'active' | 'blocked' | 'retired';
  change_summary: string;
  source: EvolutionActorType;
  author: string;
  created_at: string;
  traffic_percent: number;
  evidence: EvolutionEvidence[];
};

export type EvolutionAsset = {
  id: string;
  kind: EvolutionAssetKind;
  name: string;
  description: string;
  owner: string;
  used_by_agents: number;
  updated_at: string;
  channels: Record<EvolutionLifecycle, EvolutionVersion | null>;
};

export type EvolutionProposal = {
  id: string;
  asset_id: string;
  asset_name: string;
  asset_kind: EvolutionAssetKind;
  source: EvolutionActorType;
  title: string;
  reason: string;
  evidence_trace_ids: string[];
  proposed_version: string;
  risk: 'low' | 'medium' | 'high';
  status: 'pending' | 'accepted' | 'rejected';
  created_at: string;
};

export type EvolutionOverview = {
  assets: EvolutionAsset[];
  proposals: EvolutionProposal[];
};

export type SkillVersionSpec = {
  kind: 'skill';
  instructions: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  allowed_tools: string[];
  max_steps: number;
  timeout_ms: number;
};

export type McpVersionSpec = {
  kind: 'mcp';
  endpoint: string;
  transport: 'stdio' | 'sse' | 'streamable-http';
  authentication: { type: string; secret_ref?: string };
  tools: Array<{ name: string; description: string; input_schema: Record<string, unknown> }>;
};

export type KnowledgeVersionSpec = {
  kind: 'knowledge';
  embedding_model: string;
  index_name: string;
  chunk_strategy: { mode: string; size: number; overlap: number };
  retrieval: { mode: string; top_k: number; reranker?: string };
  sources: Array<{ id: string; name: string; connector: string; uri: string; enabled: boolean }>;
};

export type EvolutionVersionSpec = SkillVersionSpec | McpVersionSpec | KnowledgeVersionSpec;

const workspaceHeaders = (workspaceId: string) => ({ 'x-workspace-id': workspaceId });

export const getEvolutionOverview = (workspaceId: string) =>
  request<EvolutionOverview>('/api/evolution/overview', {
    headers: workspaceHeaders(workspaceId),
    withCredentials: true,
  });

export const getEvolutionAsset = (workspaceId: string, assetId: string) =>
  request<EvolutionAsset>(`/api/evolution/assets/${assetId}`, {
    headers: workspaceHeaders(workspaceId),
    withCredentials: true,
  });

export const getEvolutionVersionSpec = (
  workspaceId: string,
  assetId: string,
  versionId: string,
) =>
  request<EvolutionVersionSpec>(
    `/api/evolution/assets/${assetId}/versions/${versionId}/spec`,
    {
      headers: workspaceHeaders(workspaceId),
      withCredentials: true,
    },
  );

export const updateEvolutionVersionSpec = (
  workspaceId: string,
  assetId: string,
  versionId: string,
  payload: EvolutionVersionSpec,
) =>
  request<EvolutionVersionSpec>(
    `/api/evolution/assets/${assetId}/versions/${versionId}/spec`,
    {
      method: 'PUT',
      data: payload,
      headers: workspaceHeaders(workspaceId),
      withCredentials: true,
    },
  );

export const createEvolutionAsset = (
  workspaceId: string,
  payload: Pick<EvolutionAsset, 'kind' | 'name' | 'description' | 'owner'>,
) =>
  request<EvolutionAsset>('/api/evolution/assets', {
    method: 'POST',
    data: payload,
    headers: workspaceHeaders(workspaceId),
    withCredentials: true,
  });

export const createEvolutionVersion = (
  workspaceId: string,
  assetId: string,
  payload: Pick<EvolutionVersion, 'version' | 'change_summary' | 'source'> & { proposal_id?: string },
) =>
  request<EvolutionVersion>(`/api/evolution/assets/${assetId}/versions`, {
    method: 'POST',
    data: payload,
    headers: workspaceHeaders(workspaceId),
    withCredentials: true,
  });

export const runEvolutionEvaluation = (
  workspaceId: string,
  assetId: string,
  versionId: string,
  payload: { policy_ids: string[]; dataset_version_ids: string[] },
) =>
  request<EvolutionVersion>(`/api/evolution/assets/${assetId}/versions/${versionId}/evaluations`, {
    method: 'POST',
    data: payload,
    headers: workspaceHeaders(workspaceId),
    withCredentials: true,
  });

export const promoteEvolutionVersion = (
  workspaceId: string,
  assetId: string,
  versionId: string,
  payload: { target: EvolutionLifecycle; evidence_ids: string[]; traffic_percent?: number },
) =>
  request<EvolutionAsset>(`/api/evolution/assets/${assetId}/versions/${versionId}/promote`, {
    method: 'POST',
    data: payload,
    headers: workspaceHeaders(workspaceId),
    withCredentials: true,
  });

export const rollbackEvolutionChannel = (
  workspaceId: string,
  assetId: string,
  payload: { channel: EvolutionLifecycle; target_version_id: string; reason: string },
) =>
  request<EvolutionAsset>(`/api/evolution/assets/${assetId}/rollback`, {
    method: 'POST',
    data: payload,
    headers: workspaceHeaders(workspaceId),
    withCredentials: true,
  });

export const checkMcpConnection = (
  workspaceId: string,
  assetId: string,
  versionId: string,
) =>
  request<{ healthy: boolean; latency_ms: number; checked_at: string }>(
    `/api/evolution/assets/${assetId}/versions/${versionId}/mcp-health-checks`,
    {
      method: 'POST',
      headers: workspaceHeaders(workspaceId),
      withCredentials: true,
    },
  );

export const rebuildKnowledgeIndex = (
  workspaceId: string,
  assetId: string,
  versionId: string,
) =>
  request<{ run_id: string; status: 'queued' | 'running' }>(
    `/api/evolution/assets/${assetId}/versions/${versionId}/index-runs`,
    {
      method: 'POST',
      headers: workspaceHeaders(workspaceId),
      withCredentials: true,
    },
  );

export const reviewEvolutionProposal = (
  workspaceId: string,
  proposalId: string,
  payload: { decision: 'accept' | 'reject'; comment?: string },
) =>
  request<EvolutionProposal>(`/api/evolution/proposals/${proposalId}/review`, {
    method: 'POST',
    data: payload,
    headers: workspaceHeaders(workspaceId),
    withCredentials: true,
  });
