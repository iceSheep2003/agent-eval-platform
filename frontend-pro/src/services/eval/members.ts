/**
 * 组织与成员。
 *
 * 三层对齐 Langfuse：**组织 Organization → 项目 Workspace → 成员 Membership**。
 * 两套角色职责不同，不要混用：
 * - 组织角色 `OrgRole`：owner / admin / member / viewer —— 管成员、建项目
 * - 项目角色 `WorkspaceRole`：owner / admin / evaluator / developer / viewer —— 管评测资产
 */

import { call, withWorkspace } from './http';

export type OrgRole = 'owner' | 'admin' | 'member' | 'viewer';

export type WorkspaceRole =
  | 'owner'
  | 'admin'
  | 'evaluator'
  | 'developer'
  | 'viewer';

export type Organization = {
  id: string;
  slug: string;
  name: string;
  role: OrgRole | null;
};

export type Member = {
  user_id: string;
  username: string;
  display_name: string;
  email: string | null;
  role: string;
};

export const getOrganizations = () =>
  call<{ items: Organization[] }>('/api/organizations');

export const getOrgMembers = (organizationId: string) =>
  call<{ items: Member[] }>(`/api/organizations/${organizationId}/members`);

export const addOrgMember = (
  organizationId: string,
  payload: { identifier: string; role: OrgRole },
) =>
  call<{ user_id: string; role: string }>(
    `/api/organizations/${organizationId}/members`,
    { method: 'POST', data: payload },
  );

export const updateOrgMemberRole = (
  organizationId: string,
  userId: string,
  role: OrgRole,
) =>
  call<{ user_id: string; role: string }>(
    `/api/organizations/${organizationId}/members/${userId}`,
    { method: 'PATCH', data: { role } },
  );

export const removeOrgMember = (organizationId: string, userId: string) =>
  call<{ user_id: string }>(`/api/organizations/${organizationId}/members/${userId}`, {
    method: 'DELETE',
  });

export const getWorkspaceMembers = (workspaceId: string) =>
  call<{ items: Member[] }>(`/api/workspaces/${workspaceId}/members`, {
    headers: { 'x-workspace-id': workspaceId },
    withCredentials: true,
  });

export const addWorkspaceMember = (
  workspaceId: string,
  payload: { identifier: string; role: WorkspaceRole },
) =>
  call<Member>(`/api/workspaces/${workspaceId}/members`, {
    method: 'POST',
    data: payload,
    ...withWorkspace(workspaceId),
  });

export const updateWorkspaceMemberRole = (
  workspaceId: string,
  userId: string,
  role: WorkspaceRole,
) =>
  call<{ user_id: string; role: string }>(
    `/api/workspaces/${workspaceId}/members/${userId}`,
    { method: 'PATCH', data: { role }, ...withWorkspace(workspaceId) },
  );

export const removeWorkspaceMember = (workspaceId: string, userId: string) =>
  call<{ user_id: string }>(`/api/workspaces/${workspaceId}/members/${userId}`, {
    method: 'DELETE',
    ...withWorkspace(workspaceId),
  });

export type Invitation = {
  id: string;
  organization_id: string;
  email: string;
  role: OrgRole;
  status: 'pending' | 'accepted' | 'revoked';
  invited_by: string;
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
};

export const getInvitations = (organizationId: string) =>
  call<{ items: Invitation[] }>(`/api/organizations/${organizationId}/invitations`);

/** 按邮箱邀请。账号已存在立即加入；否则等对方首次登录时自动接受。 */
export const inviteToOrganization = (
  organizationId: string,
  payload: { email: string; role: OrgRole },
) =>
  call<Invitation>(`/api/organizations/${organizationId}/invitations`, {
    method: 'POST',
    data: payload,
  });

export const revokeInvitation = (organizationId: string, invitationId: string) =>
  call<{ invitation_id: string }>(
    `/api/organizations/${organizationId}/invitations/${invitationId}`,
    { method: 'DELETE' },
  );

export const createWorkspace = (payload: { slug: string; name: string }) =>
  call<{ id: string; name: string }>('/api/workspaces', {
    method: 'POST',
    data: payload,
  });
