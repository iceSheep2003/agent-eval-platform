/**
 * 资源密钥：Agent 运行时要用的凭证（模型 Key、MCP Token）。
 *
 * 与 `credentials.ts` 的分工：
 * - `credentials` 是**平台发给外部的凭证**（`evk_`/`evl_`），只存哈希、不可还原；
 * - 本模块是**Agent 运行时要注入的密钥**，必须可还原，所以加密存储。
 *
 * 明文只在创建时进请求体，**任何响应都不返回明文**——只给指纹。
 */

import { call, withWorkspace } from './http';

/** 平台内置的模型配置键。Agent 不必声明，平台自动注入；声明同名即可覆盖。 */
export const MODEL_KEYS = ['model_base_url', 'model_auth_token', 'model_name'] as const;
export type ModelKey = (typeof MODEL_KEYS)[number];

/** 工作区默认绑定的保留版本 id——对该工作区所有 Agent 生效。 */
export const WORKSPACE_DEFAULT = '*';

export type ResourceSecret = {
  id: string;
  name: string;
  fingerprint: string;
  description: string;
  created_at: string;
};

export type SecretBinding = {
  id: string;
  asset_version_id: string;
  channel: string;
  secret_name: string;
  resource_secret_id: string;
  fingerprint: string | null;
  bound_at: string;
};

export const listSecrets = (workspaceId: string) =>
  call<{ items: ResourceSecret[] }>('/api/secrets', withWorkspace(workspaceId));

export const putSecret = (
  workspaceId: string,
  payload: { name: string; value: string; description?: string },
) =>
  call<ResourceSecret>('/api/secrets', {
    method: 'POST',
    data: payload,
    ...withWorkspace(workspaceId),
  });

/** 工作区默认绑定——对所有 Agent 生效的那一层。 */
export const listSecretBindings = (workspaceId: string) =>
  call<{ items: SecretBinding[] }>('/api/secret-bindings', withWorkspace(workspaceId));

/**
 * 设置工作区默认模型配置。
 *
 * 传 `null` 的项不动；传空串的项会被忽略。测试与生产通道分别绑定——
 * 这是「同一个 Agent 在不同通道用不同模型」的落点。
 */
export const setModelConfig = (
  workspaceId: string,
  payload: { base_url?: string | null; auth_token?: string | null; model_name?: string | null },
) =>
  call<{ bound: string[] }>('/api/model-config', {
    method: 'POST',
    data: payload,
    ...withWorkspace(workspaceId),
  });

/** 解绑工作区默认的某个密钥。 */
export const unbindSecret = (
  workspaceId: string,
  channel: string,
  secretName: string,
) =>
  call<{ unbound: boolean }>(
    `/api/secret-bindings/${channel}/${encodeURIComponent(secretName)}`,
    { method: 'DELETE', ...withWorkspace(workspaceId) },
  );

/** 取某 Agent 的版本列表——绑定密钥要知道绑到哪个版本。 */
export const listAgentVersions = (workspaceId: string, assetId: string) =>
  call<{ items: Array<{ id: string; version: string }> }>(
    `/api/agents/${assetId}/versions`,
    withWorkspace(workspaceId),
  );

/** 把某把密钥绑到「Agent 版本 × 通道」。 */
export const bindSecret = (
  workspaceId: string,
  assetId: string,
  versionId: string,
  channel: string,
  payload: { resource_secret_id: string; secret_name: string; workspace_default?: boolean },
) =>
  call<SecretBinding>(
    `/api/agents/${assetId}/versions/${versionId}/secrets/${channel}/bind`,
    { method: 'POST', data: payload, ...withWorkspace(workspaceId) },
  );
