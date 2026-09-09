/** 认证：登录 / 登出 / 会话。 */

import { request } from '@umijs/max';
import type { SessionPayload } from './types';

export const getSession = () =>
  request<SessionPayload>('/api/auth/me', { withCredentials: true });

export const login = (identifier: string, password: string) =>
  request<SessionPayload>('/api/auth/login', {
    method: 'POST',
    data: { identifier, password },
    withCredentials: true,
  });

export const logout = () =>
  request<{ ok: boolean }>('/api/auth/logout', { method: 'POST', withCredentials: true });
