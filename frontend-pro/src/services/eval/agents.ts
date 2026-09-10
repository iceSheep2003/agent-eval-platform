/**
 * Agent 资产：接入、版本、通道、晋级回退、Trace。
 *
 * 三通道版本用「label 给人看、id 给接口用」两套字段：
 * `test_version` 是显示值，`test_version_id` 才是晋级/回退的入参。
 */

import { call, withWorkspace } from './http';

export type AgentSourceKind = 'package' | 'github' | 'sdk';

export type EvalAgent = {
  id: string;
  name: string;
  description: string;
  owner: string;
  owner_id?: string;
  connect_type: string;
  status: string;
  environment: string;
  lifecycle?: 'test' | 'livesh' | 'live';
  version?: string;
  test_version?: string | null;
  livesh_version?: string | null;
  live_version?: string | null;
  test_version_id?: string | null;
  livesh_version_id?: string | null;
  live_version_id?: string | null;
  credential_state?: 'ready' | 'missing' | 'expiring';
  source_ref?: string;
  created_at?: string;
  updated_at?: string;
  instance_count: number;
  binding_count?: number;
  success_rate?: number;
  latency_ms?: number;
  run_count?: number;
  quality_score?: number;
  average_cost?: number;
  average_llm_calls?: number;
  average_tool_calls?: number;
};

export type AgentArtifact = {
  id: string;
  agent_id: string;
  source_kind: AgentSourceKind;
  version: string;
  source_ref: string;
  commit_sha?: string;
  checksum_sha256?: string;
  build_status: 'queued' | 'building' | 'ready' | 'failed';
  created_at: string;
};

export type AgentTraceSpan = {
  id: string;
  name: string;
  type: 'agent' | 'llm' | 'tool' | 'retriever';
  status: string;
  depth: number;
  duration: number;
  model?: string;
  tokens?: number;
  cost?: number;
  input: string;
  output: string;
  attributes: Record<string, string | number>;
};

export type AgentTrace = {
  id: string;
  name: string;
  status: string;
  environment: string;
  startedAt: string;
  duration: number;
  tokens: number;
  cost: number;
  input: string;
  output: string;
  tenant_id?: string | null;
  spans: AgentTraceSpan[];
};

export type AgentTraceSummary = Omit<AgentTrace, 'spans'> & { span_count: number };

export type EvalAgentDetail = EvalAgent & {
  versions: Array<{
    id: string;
    version: string;
    status: string;
    source_type: string;
    source_uri: string;
    created_at: string;
  }>;
  instances: Array<{
    id: string;
    status: string;
    runtime_type: string;
    endpoint?: string;
    created_at: string;
  }>;
  bindings: Array<{
    id: string;
    policy_name: string;
    dataset_name: string;
    schedule: string;
    failure_threshold: number;
    enabled: number;
  }>;
  releases: Array<{
    id: string;
    version: string;
    from_version?: string;
    channel: string;
    status: string;
    created_at: string;
  }>;
  health_checks: Array<{
    id: string;
    status: string;
    latency_ms: number;
    completed_at?: string;
    created_at: string;
  }>;
  credentials: Array<{
    id: string;
    name: string;
    kind: string;
    last_four: string;
    updated_at: string;
  }>;
  sdk_trace_count: number;
  invocations: Array<{
    id: string;
    instance_id: string;
    caller_type: string;
    input: string;
    output?: string;
    status: string;
    latency_ms: number;
    error?: string;
    created_at: string;
  }>;
};

export const getAgents = (workspaceId: string) =>
  call<{ items: EvalAgent[] }>('/api/agents', withWorkspace(workspaceId));

export const getAgent = (workspaceId: string, agentId: string) =>
  call<EvalAgentDetail>(`/api/agents/${agentId}`, withWorkspace(workspaceId));

/**
 * 接入 Agent。三种方式走同一个接口，用 `connect_type` + `source` 区分，
 * 各自必填字段由后端 `modules/asset/domain/spec/agent.py` 校验。
 */
export const registerAgent = (
  workspaceId: string,
  payload: {
    name: string;
    description?: string;
    /** 负责人：工作区成员 ID。留空则后端默认当前登录用户。 */
    owner_id?: string;
    connect_type: AgentSourceKind;
    source?: Record<string, unknown>;
  },
) =>
  call<EvalAgentDetail>('/api/agents', {
    method: 'POST',
    data: payload,
    ...withWorkspace(workspaceId),
  });

export const getAgentArtifacts = (workspaceId: string, agentId: string) =>
  call<{ items: AgentArtifact[] }>(
    `/api/agents/${agentId}/artifacts`,
    withWorkspace(workspaceId),
  );

export const getAgentTraces = (workspaceId: string, agentId: string, limit = 50) =>
  call<{ items: AgentTraceSummary[] }>(
    `/api/agents/${agentId}/traces?limit=${limit}`,
    withWorkspace(workspaceId),
  );

export const getTrace = (workspaceId: string, traceId: string) =>
  call<AgentTrace>(`/api/traces/${traceId}`, withWorkspace(workspaceId));

/** 晋级。目标通道决定所需权限；门禁未通过返回 409 `gate_blocked`。 */
export const promoteAgentVersion = (
  workspaceId: string,
  payload: {
    asset_id: string;
    version_id: string;
    to_channel: 'livesh' | 'live';
    run_id?: string;
    confirm?: boolean;
  },
) =>
  call<{
    id: string;
    version_id: string;
    from_channel: string;
    to_channel: string;
    run_id: string;
    gate_passed: boolean;
  }>('/api/promotions', {
    method: 'POST',
    data: payload,
    ...withWorkspace(workspaceId),
  });

/** 回退：只改通道指针，问题版本与证据保留。 */
export const rollbackAgentVersion = (
  workspaceId: string,
  agentId: string,
  payload: {
    channel: 'test' | 'livesh' | 'live';
    to_version_id: string;
    reason: string;
    confirm?: boolean;
  },
) =>
  call<{ id: string; channel: string; to_version_id: string }>(
    `/api/agents/${agentId}/rollback`,
    { method: 'POST', data: payload, ...withWorkspace(workspaceId) },
  );

export const getAgentPromotions = (workspaceId: string, agentId: string) =>
  call<{ items: Array<Record<string, unknown>> }>(
    `/api/agents/${agentId}/promotions`,
    withWorkspace(workspaceId),
  );
