/**
 * 请求公共选项。
 *
 * 后端统一返回 `{success, data, errorCode, errorMessage, showType}`，
 * `config/config.ts` 里的 `request.dataField = 'data'` 已经解包，
 * 所以各域函数直接 `request<T>(path)` 拿到的就是 `data`。
 */

import { request } from '@umijs/max';
import type { RequestOptions } from '@umijs/max';

export const workspaceHeaders = (workspaceId: string) => ({
  'x-workspace-id': workspaceId,
});

/** 带工作区上下文的请求选项。所有业务接口都必须带，否则后端无法判断租户边界。 */
export const withWorkspace = (workspaceId: string) => ({
  headers: workspaceHeaders(workspaceId),
  withCredentials: true,
});

type Envelope<T> = { success: boolean; data: T };

/**
 * 调控制台接口并解包 `data`。
 *
 * **不要依赖 `.umirc` 的 `request.dataField`**：本项目的 umi 版本只在配置 schema
 * 里声明了它，运行时并未实现（生成的 `.umi/plugin-request/request.ts` 里搜不到），
 * 配了也不生效——拿到的是整个 `{success, data, errorCode, ...}` 信封。
 * 失败时 `requestErrorConfig.ts` 的 errorThrower 已经抛错，这里只管成功分支。
 */
export const call = async <T>(path: string, options?: RequestOptions): Promise<T> => {
  const body = (await request(path, options ?? {})) as unknown as Envelope<T>;
  return body.data;
};
