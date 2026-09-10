/** 跨域共享的会话类型。业务实体类型放在各自的域文件里。 */

export type EvalUser = {
  id: string;
  username: string;
  email: string;
  display_name: string;
  role: string;
};

export type Workspace = {
  id: string;
  name: string;
  description: string;
  role: string;
  member_count?: number;
};

export type SessionPayload = { user: EvalUser; workspaces: Workspace[] };
