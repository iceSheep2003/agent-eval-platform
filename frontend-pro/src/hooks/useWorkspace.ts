import { useModel } from '@umijs/max';
import type { Workspace } from '@/services/eval';

export function useWorkspace() {
  const { initialState } = useModel('@@initialState');
  return (initialState as typeof initialState & { currentWorkspace?: Workspace })?.currentWorkspace;
}
