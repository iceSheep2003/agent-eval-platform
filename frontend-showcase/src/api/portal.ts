import { http, requestList } from './client';

/** 后端 `Channel` 枚举的线值。注意影子通道是 `liversh`，不是 `liveshadow`。 */
export type ChannelValue = 'test' | 'liversh' | 'live';

export interface PortalUser {
  id: string;
  username: string;
  display_name: string;
  email: string | null;
  status?: string;
}

export interface PortalProject {
  id: string;
  slug: string;
  name: string;
  description: string;
  my_role?: string | null;
}

export interface PortalChannel {
  channel: ChannelValue;
  label: string;
  /** 影子通道的提示语；其它通道为 null。 */
  notice: string | null;
  bound: boolean;
  version_id: string | null;
  version_label: string | null;
}

export interface PortalAgent {
  id: string;
  asset_id: string;
  name: string;
  display_name: string;
  description: string;
  lifecycle: string;
  channels: PortalChannel[];
}

export interface PortalSession {
  user: PortalUser;
  projects: PortalProject[];
}

export const portalLogin = (identifier: string, password: string) =>
  http.post<never, PortalSession>('/api/portal/auth/login', { identifier, password });

export const portalLogout = () => http.post<never, { ok: boolean }>('/api/portal/auth/logout');

export const getSession = () => http.get<never, PortalSession>('/api/portal/me');

export const getProject = (projectId: string) =>
  http.get<never, PortalProject>(`/api/portal/projects/${projectId}`);

export const listAgents = (projectId: string) =>
  requestList<PortalAgent>(`/api/portal/projects/${projectId}/agents`);

export const getAgent = (projectId: string, agentId: string) =>
  http.get<never, PortalAgent>(`/api/portal/projects/${projectId}/agents/${agentId}`);

export const chatUrl = (projectId: string, agentId: string, channel: ChannelValue) =>
  `/api/portal/projects/${projectId}/agents/${agentId}/channels/${channel}/chat`;
