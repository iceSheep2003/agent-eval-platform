/** 认证：登录 / 登出 / 会话。 */

import { call } from './http';
import type { SessionPayload } from './types';

export const getSession = () =>
  call<SessionPayload>('/api/auth/me', { withCredentials: true });

export const login = (identifier: string, password: string) =>
  call<SessionPayload>('/api/auth/login', {
    method: 'POST',
    data: { identifier, password },
    withCredentials: true,
  });

export const logout = () =>
  call<{ ok: boolean }>('/api/auth/logout', { method: 'POST', withCredentials: true });
