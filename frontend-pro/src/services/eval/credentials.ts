/** 接入凭证：签发、轮换、吊销。明文 `secret` 只在创建/轮换响应里出现一次。 */

import { request } from '@umijs/max';
import { withWorkspace } from './http';

export type AgentCredential = {
  id: string;
  name: string;
  prefix: string;
  kind: string;
  last_four: string;
  scopes: string[];
  environment: string | null;
  channel: string | null;
  agent_ids: string[];
  status: 'active' | 'expiring' | 'revoked';
  last_used_at?: string;
  expires_at?: string;
  created_at: string;
};

export const getAgentCredentials = (workspaceId: string) =>
  request<{ items: AgentCredential[] }>('/api/agent-credentials', withWorkspace(workspaceId));

export const createAgentCredential = (
  workspaceId: string,
  payload: {
    name: string;
    kind?: 'evk' | 'evl' | 'evs';
    agent_id?: string;
    channel?: 'test' | 'livesh' | 'live';
    scopes?: string[];
    expires_at?: string;
  },
) =>
  request<AgentCredential & { secret: string }>('/api/agent-credentials', {
    method: 'POST',
    data: payload,
    ...withWorkspace(workspaceId),
  });

export const rotateAgentCredential = (workspaceId: string, credentialId: string) =>
  request<AgentCredential & { secret: string }>(
    `/api/agent-credentials/${credentialId}/rotate`,
    { method: 'POST', ...withWorkspace(workspaceId) },
  );

export const revokeAgentCredential = (workspaceId: string, credentialId: string) =>
  request<AgentCredential>(`/api/agent-credentials/${credentialId}/revoke`, {
    method: 'POST',
    ...withWorkspace(workspaceId),
  });
