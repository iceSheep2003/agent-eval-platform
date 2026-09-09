import axios, { type AxiosInstance } from 'axios';

/**
 * 后端统一响应封装是 `{success, data, errorCode, errorMessage}`。
 *
 * **必须在拦截器里解包**——控制台 `frontend-pro` 漏了这一步（`dataField: 'data'`
 * 没配），导致所有列表页静默回退到 demo 数据。这里显式取 `res.data.data`，
 * 业务代码直接拿到真实对象。
 */
export interface Envelope<T> {
  success: boolean;
  data: T;
  errorCode: string | null;
  errorMessage: string | null;
  showType?: number;
}

export interface ListPayload<T> {
  items: T[];
  total?: number;
}

export class BizError extends Error {
  code: string | null;
  status: number | null;

  constructor(message: string, code: string | null, status: number | null) {
    super(message);
    this.name = 'BizError';
    this.code = code;
    this.status = status;
  }
}

export const http: AxiosInstance = axios.create({
  // 走 Vite 代理，同源；cookie 与 SSE 都不用处理 CORS
  baseURL: '',
  withCredentials: true,
  timeout: 120_000,
});

http.interceptors.response.use(
  (response) => {
    const body = response.data as Envelope<unknown>;
    if (body && typeof body === 'object' && 'success' in body) {
      if (!body.success) {
        throw new BizError(
          body.errorMessage ?? '请求失败',
          body.errorCode,
          response.status,
        );
      }
      return body.data as never;
    }
    return response.data as never;
  },
  (error) => {
    const status = error?.response?.status ?? null;
    const body = error?.response?.data as Envelope<unknown> | undefined;
    if (body && typeof body === 'object' && body.errorMessage) {
      throw new BizError(body.errorMessage, body.errorCode ?? null, status);
    }
    if (status === 401) {
      throw new BizError('登录已过期，请重新登录', 'unauthenticated', 401);
    }
    throw new BizError(error?.message ?? '网络错误', null, status);
  },
);

/** 列表接口统一是 `{items: [...]}`，这里剥一层。 */
export async function requestList<T>(url: string): Promise<T[]> {
  const payload = await http.get<never, ListPayload<T>>(url);
  return payload?.items ?? [];
}
