/** 评测运行：列表、详情、运行控制。 */

import { call, withWorkspace } from './http';

export type EvalRun = {
  id: string;
  name: string;
  agent_name: string;
  agent_version: string;
  dataset_name: string;
  status: 'queued' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled';
  phase: string;
  progress: number;
  passed: number;
  total: number;
  score: number;
  cost: number;
  duration_seconds: number;
  updated_at: string;
};

export type TraceEvent = {
  id: string;
  event_type: string;
  actor: string;
  name: string;
  input?: string;
  output?: string;
  status: string;
  started_at: string;
  ended_at?: string;
};

export type EvalRunDetail = EvalRun & {
  trials: Array<{ id: string; status: string; score: number; duration_ms: number }>;
  traces: TraceEvent[];
  scores: Array<{ id: string; dimension_id: string; value: number }>;
};

export const getRuns = (workspaceId: string) =>
  call<{ items: EvalRun[] }>('/api/runs', withWorkspace(workspaceId));

export const getRun = (workspaceId: string, runId: string) =>
  call<EvalRunDetail>(`/api/runs/${runId}`, withWorkspace(workspaceId));

export const runAction = (
  workspaceId: string,
  runId: string,
  action: 'pause' | 'resume' | 'stop',
) =>
  call<EvalRunDetail>(`/api/runs/${runId}/${action}`, {
    method: 'POST',
    ...withWorkspace(workspaceId),
  });
