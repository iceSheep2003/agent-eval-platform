/**
 * 评测平台的接口层，**按业务域拆分**：
 *
 * ```text
 * auth.ts        登录 / 会话
 * agents.ts      Agent 资产、版本、通道、晋级回退、Trace
 * credentials.ts 接入凭证
 * runs.ts        评测运行
 * datasets.ts    数据集
 * evaluation.ts  能力 / 维度 / 策略
 * http.ts        请求公共选项
 * types.ts       跨域共享类型
 * ```
 *
 * 这个 `index.ts` 只是**兼容用的 barrel**——旧代码继续 `from '@/services/eval'` 不会坏。
 * 新代码请直接引用具体域（`from '@/services/eval/agents'`），
 * 否则页面之间会因为共用同一个入口而隐式耦合。
 */

export * from './types';
export * from './auth';
export * from './runs';
export * from './agents';
export * from './credentials';
export * from './datasets';
export * from './evaluation';
