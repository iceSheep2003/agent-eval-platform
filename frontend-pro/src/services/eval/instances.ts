/**
 * 运行实例：把某个版本的 Agent 真正跑起来。
 *
 * **和发布通道是两条独立的生命周期**：
 *   发布通道 test/liversh/live 改的是「用哪个版本」
 *   运行实例 stopped/running/… 改的是「跑没跑起来」
 *
 * 所以冻结版本不启动、晋级也不启动（LIVE 除外，发布即生效）。
 */

import { request } from '@umijs/max';

export type InstanceStatus =
  | 'stopped'
  | 'starting'
  | 'running'
  | 'stopping'
  | 'failed';

export type AgentInstance = {
  id: string;
  asset_id: string;
  asset_version_id: string;
  channel: 'test' | 'liversh' | 'live';
  status: InstanceStatus;
  runtime_type: string;
  endpoint?: string | null;
  error?: string | null;
  started_at?: string | null;
  stopped_at?: string | null;
};

export type InstanceAction = { instance: AgentInstance; message: string };

const headers = (workspaceId: string) => ({ 'x-workspace-id': workspaceId });

export const getInstances = (workspaceId: string, agentId: string) =>
  request<{ items: AgentInstance[] }>(`/api/agents/${agentId}/instances`, {
    headers: headers(workspaceId),
    withCredentials: true,
  });

export const startInstance = (workspaceId: string, agentId: string, channel: 'liversh' | 'live') =>
  request<InstanceAction>(`/api/agents/${agentId}/instances`, {
    method: 'POST',
    data: { channel },
    headers: headers(workspaceId),
    withCredentials: true,
  });

export const stopInstance = (workspaceId: string, agentId: string, instanceId: string) =>
  request<InstanceAction>(`/api/agents/${agentId}/instances/${instanceId}/stop`, {
    method: 'POST',
    headers: headers(workspaceId),
    withCredentials: true,
  });

export const restartInstance = (workspaceId: string, agentId: string, instanceId: string) =>
  request<InstanceAction>(`/api/agents/${agentId}/instances/${instanceId}/restart`, {
    method: 'POST',
    headers: headers(workspaceId),
    withCredentials: true,
  });

/** 实例状态的中文与配色。`null` = 该通道还没启动过。 */
export const INSTANCE_META: Record<string, { label: string; color: string }> = {
  stopped: { label: '已停止', color: 'default' },
  starting: { label: '启动中', color: 'processing' },
  running: { label: '运行中', color: 'success' },
  stopping: { label: '停止中', color: 'warning' },
  failed: { label: '启动失败', color: 'error' },
};

export const instanceMeta = (status?: string | null) =>
  INSTANCE_META[status ?? ''] ?? { label: '未启动', color: 'default' };
