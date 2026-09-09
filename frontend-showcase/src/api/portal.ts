import { http, requestList } from './client';

/** 后端 `Channel` 枚举的线值。注意影子通道是 `livesh`，不是 `liveshadow`。 */
export type ChannelValue = 'test' | 'livesh' | 'live';

export interface PortalUser {
  id: string;
  username: string;
  display_name: string;
  email: string | null;
  status?: string;
}

export interface PortalHub {
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
  hubs: PortalHub[];
}

export const portalLogin = (identifier: string, password: string) =>
  http.post<never, PortalSession>('/api/portal/auth/login', { identifier, password });

export const portalLogout = () => http.post<never, { ok: boolean }>('/api/portal/auth/logout');

export const getSession = () => http.get<never, PortalSession>('/api/portal/me');

export const getHub = (hubId: string) =>
  http.get<never, PortalHub>(`/api/portal/hubs/${hubId}`);

export const listAgents = (hubId: string) =>
  requestList<PortalAgent>(`/api/portal/hubs/${hubId}/agents`);

export const getAgent = (hubId: string, agentId: string) =>
  http.get<never, PortalAgent>(`/api/portal/hubs/${hubId}/agents/${agentId}`);

export const chatUrl = (hubId: string, agentId: string, channel: ChannelValue) =>
  `/api/portal/hubs/${hubId}/agents/${agentId}/channels/${channel}/chat`;
