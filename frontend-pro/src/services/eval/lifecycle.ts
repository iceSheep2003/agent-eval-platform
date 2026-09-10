/**
 * 资产治理策略（声明式状态机）。
 *
 * 通道（TEST / LIVESH / LIVE）是**状态**，晋级是**迁移**。每条迁移声明：
 * 要过哪些检查、需要什么权限、是否要二次确认——**都是数据**。
 *
 * 所以「进入 LIVESH 要做哪几件事」不该由前端写死，读这个接口即可。
 * 后端改了策略，界面跟着变，不用重新发版。
 */

import { call } from './http';

export type LifecycleCheckName =
  | 'promotion_gate'
  | 'shadow_route'
  | 'shadow_verification';

export type LifecycleCheck = {
  name: LifecycleCheckName;
  enabled: boolean;
  params: Record<string, unknown>;
};

export type LifecycleTransition = {
  from_channel: string;
  to_channel: string;
  permission: string;
  requires_reauth: boolean;
  checks: LifecycleCheck[];
};

export type LifecyclePolicy = {
  transitions: LifecycleTransition[];
};

export type ParamSpec = {
  key: string;
  label: string;
  type: 'number' | 'select' | 'text';
  default: unknown;
  options: string[];
  step: number | null;
  help: string | null;
};

export type CheckSchema = {
  name: LifecycleCheckName;
  label: string;
  description: string;
  params: ParamSpec[];
};

/**
 * 可用检查项与它们的参数 schema。
 *
 * **前端不写死参数**——加检查项只改后端，界面自动多出对应表单。
 */
export const getLifecycleChecks = () =>
  call<{ items: CheckSchema[] }>('/api/lifecycle-policy/checks');

export const getLifecyclePolicy = () =>
  call<LifecyclePolicy>('/api/lifecycle-policy');

/** 覆盖本工作区的策略。写坏了可以 reset 退回平台默认。 */
export const saveLifecyclePolicy = (transitions: LifecycleTransition[]) =>
  call<LifecyclePolicy>('/api/lifecycle-policy', {
    method: 'PUT',
    data: { transitions },
  });

export const resetLifecyclePolicy = () =>
  call<LifecyclePolicy>('/api/lifecycle-policy/reset', { method: 'POST' });

const CHECK_LABEL: Record<LifecycleCheckName, string> = {
  promotion_gate: '发布门禁',
  shadow_route: '影子路由已配置',
  shadow_verification: '影子验证不劣于基线',
};

/** 把检查项的参数量成一句人话，让阈值在界面上看得见。 */
export function describeCheck(check: LifecycleCheck): string {
  const label = CHECK_LABEL[check.name] ?? check.name;
  const params = check.params ?? {};
  const details: string[] = [];

  if (check.name === 'promotion_gate' && params.stage) {
    details.push(`阶段 ${params.stage}`);
  }
  if (check.name === 'shadow_verification') {
    if (params.min_samples) details.push(`样本 ≥ ${params.min_samples}`);
    if (params.window_days) details.push(`近 ${params.window_days} 天`);
    if (typeof params.success_rate_tolerance === 'number') {
      details.push(`成功率容差 ${(params.success_rate_tolerance as number) * 100}%`);
    }
    if (typeof params.latency_tolerance === 'number') {
      details.push(`P95 容差 ${(params.latency_tolerance as number) * 100}%`);
    }
  }
  return details.length ? `${label}（${details.join('，')}）` : label;
}

/** 目标通道对应的迁移。`null` 表示这个方向没有声明过（例如 TEST 是起点）。 */
export function transitionTo(
  policy: LifecyclePolicy | undefined,
  toChannel: string,
): LifecycleTransition | undefined {
  return policy?.transitions.find((item) => item.to_channel === toChannel);
}
