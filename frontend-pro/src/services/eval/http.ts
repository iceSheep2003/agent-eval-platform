/**
 * 请求公共选项。
 *
 * 后端统一返回 `{success, data, errorCode, errorMessage, showType}`，
 * `config/config.ts` 里的 `request.dataField = 'data'` 已经解包，
 * 所以各域函数直接 `request<T>(path)` 拿到的就是 `data`。
 */

export const workspaceHeaders = (workspaceId: string) => ({
  'x-workspace-id': workspaceId,
});

/** 带工作区上下文的请求选项。所有业务接口都必须带，否则后端无法判断租户边界。 */
export const withWorkspace = (workspaceId: string) => ({
  headers: workspaceHeaders(workspaceId),
  withCredentials: true,
});
