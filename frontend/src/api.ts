export async function api<T>(path: string, init: RequestInit = {}, workspaceId = 'eval-dev'): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: 'include',
    headers: { 'x-workspace-id': workspaceId, ...(init.body instanceof FormData ? {} : { 'content-type': 'application/json' }), ...init.headers },
  })
  const payload = response.status === 204 ? undefined : await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload?.error || payload?.detail || `API ${response.status}`)
  return payload as T
}

export type ApiAgent = {
  id: string; name: string; description: string; owner: string; connect_type: string
  status: 'active' | 'paused' | 'disabled'; environment: string
  version_id?: string; version?: string; source_uri?: string; instance_count: number
  binding_count?: number; success_rate?: number; latency_ms?: number; run_count?: number
}

export type ApiAgentVersion = { id: string; version: string; source_type: string; source_uri?: string; source_digest: string; image_ref?: string; status: string; created_at: string }
export type ApiAgentInstance = { id: string; agent_version_id: string; desired_status: string; status: string; runtime_backend: string; runtime_ref?: string; endpoint?: string; error?: string; created_at: string }
export type ApiAgentBinding = { id: string; agent_version_id: string; policy_id: string; policy_name: string; lifecycle: string; trigger_type: string; dataset_name: string; dataset_version: string; schedule: string; failure_threshold: number; enabled: number; created_at: string }
export type ApiAgentRelease = { id: string; agent_version_id: string; from_version_id?: string; operation: 'release' | 'rollback'; channel: string; status: string; changelog: string; version: string; from_version?: string; created_at: string }
export type ApiHealthCheck = { id: string; status: string; latency_ms?: number; checks: string; error?: string; created_at: string; completed_at?: string }
export type ApiConfigChange = { id: string; endpoint: string; environment: string; owner: string; status: string; created_at: string; validated_at?: string }
export type ApiCredential = { id: string; agent_id?: string; agent_ids: string[]; agents: Array<{ id: string; name: string }>; provider: string; name: string; last_four: string; created_at: string; updated_at: string }
export type ApiDeploymentToken = { id: string; agent_id: string; name: string; last_four: string; revoked_at?: string; created_at: string; token?: string; invoke_url?: string }
export type ApiSdkKey = { id: string; agent_id: string; name: string; last_four: string; revoked_at?: string; created_at: string; key?: string; ingest_url?: string }
export type ApiInvocation = { id: string; agent_id: string; instance_id: string; caller_type: string; input: string; output?: string; status: string; latency_ms: number; error?: string; created_at: string }
export type ApiAgentDetail = ApiAgent & {
  versions: ApiAgentVersion[]
  instances: ApiAgentInstance[]
  bindings: ApiAgentBinding[]
  releases: ApiAgentRelease[]
  health_checks: ApiHealthCheck[]
  config_changes: ApiConfigChange[]
  credentials: ApiCredential[]
  access_tokens: ApiDeploymentToken[]
  sdk_keys: ApiSdkKey[]
  sdk_trace_count: number
  invocations: ApiInvocation[]
}

export type ApiRun = {
  id: string; name: string; agent_name: string; agent_version: string; dataset_name: string
  status: 'queued' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled'
  phase: 'queued' | 'provisioning' | 'executing' | 'scoring' | 'completed' | 'failed'
  progress: number; passed: number; total: number; score: number; cost: number
  duration_seconds: number; updated_at: string
}

export type ApiTemplate = { id: string; name: string; dataset_id: string }

export type ApiDataset = {
  id: string; name: string; kind: 'agentic' | 'single-turn' | 'badcase' | 'trace'; version: string
  item_count: number; description: string; status: string; protocol: string; evaluation: string
}

export type ApiPolicy = {
  id: string; name: string; lifecycle: string; dataset_id: string; template_id: string; dataset_name: string; dataset_version: string
  evaluators: string[]; trigger_type: string; gates: Record<string, unknown>; enabled: boolean; binding_count: number
}

export type ApiCapability = {
  id: string; name: string; description: string; enabled: number
  dimensions: Array<{ id: string; name: string; scorer_type: string; weight: number; threshold: number; deterministic: boolean; score: number }>
}
