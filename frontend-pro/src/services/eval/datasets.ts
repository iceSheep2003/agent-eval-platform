/** 数据集。 */

import { call, withWorkspace } from './http';

export type EvalDataset = {
  id: string;
  name: string;
  kind: string;
  version: string;
  item_count: number;
  description: string;
  status: string;
};

export const getDatasets = (workspaceId: string) =>
  call<{ items: EvalDataset[] }>('/api/datasets', withWorkspace(workspaceId));
