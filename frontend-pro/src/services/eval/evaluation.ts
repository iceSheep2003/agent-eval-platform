/** 评测配置：能力、维度、策略。 */

import { call, withWorkspace } from './http';

export type EvalCapability = {
  id: string;
  name: string;
  description: string;
  enabled: number;
  dimensions: Array<{
    id: string;
    name: string;
    score: number;
    threshold: number;
    weight: number;
  }>;
};

export type EvalPolicy = {
  id: string;
  name: string;
  lifecycle: string;
  dataset_name: string;
  dataset_version: string;
  evaluators: string[];
  trigger_type: string;
  gates: Record<string, number>;
  enabled: boolean;
  binding_count: number;
};

export const getCapabilities = (workspaceId: string) =>
  call<{ items: EvalCapability[] }>('/api/capabilities', withWorkspace(workspaceId));

export const getPolicies = (workspaceId: string) =>
  call<{ items: EvalPolicy[] }>('/api/policies', withWorkspace(workspaceId));
