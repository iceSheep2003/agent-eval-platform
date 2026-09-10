/**
 * 组织与成员管理。
 *
 * 两层角色分开展示（对齐 Langfuse）：
 * - 组织成员：管成员、建项目；角色 owner / admin / member / viewer
 * - 项目成员：管本项目的评测资产；角色 owner / admin / evaluator / developer / viewer
 *
 * 组织里没有账号的人，先加到组织才能加进项目。
 */

import { MailOutlined, PlusOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import {
  App,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
} from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { useWorkspace } from '@/hooks/useWorkspace';
import type {
  Invitation,
  Member,
  OrgRole,
  WorkspaceRole,
} from '@/services/eval/members';
import {
  addOrgMember,
  addWorkspaceMember,
  getInvitations,
  getOrganizations,
  getOrgMembers,
  getWorkspaceMembers,
  inviteToOrganization,
  removeOrgMember,
  removeWorkspaceMember,
  revokeInvitation,
  updateOrgMemberRole,
  updateWorkspaceMemberRole,
} from '@/services/eval/members';
import PolicyPanel from './PolicyPanel';

const ORG_ROLES: OrgRole[] = ['owner', 'admin', 'member', 'viewer'];
const WORKSPACE_ROLES: WorkspaceRole[] = [
  'owner',
  'admin',
  'evaluator',
  'developer',
  'viewer',
];

const ORG_ROLE_LABEL: Record<OrgRole, string> = {
  owner: '所有者',
  admin: '管理员',
  member: '成员',
  viewer: '只读',
};

const WORKSPACE_ROLE_LABEL: Record<WorkspaceRole, string> = {
  owner: '所有者',
  admin: '管理员',
  evaluator: '评测负责人',
  developer: '开发者',
  viewer: '只读',
};

export default function MembersPage() {
  return (
    <PageContainer
      title="工作区设置"
      content="组织管成员和项目；项目成员管本项目的评测资产。两层角色职责不同。"
    >
      <Tabs
        items={[
          { key: 'members', label: '成员', children: <MembersPanel /> },
          { key: 'policy', label: '治理策略', children: <PolicyPanel /> },
        ]}
      />
    </PageContainer>
  );
}

function MembersPanel() {
  const workspace = useWorkspace();
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [organizationId, setOrganizationId] = useState<string>();
  const [orgMembers, setOrgMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [workspaceMembers, setWorkspaceMembers] = useState<Member[]>([]);
  const [adding, setAdding] = useState<'org' | 'workspace' | 'invite' | null>(
    null,
  );

  const refresh = useCallback(async () => {
    if (!workspace) return;
    setLoading(true);
    try {
      const organizations = await getOrganizations();
      const organization = organizations.items[0];
      setOrganizationId(organization?.id);
      const [org, members, invites] = await Promise.all([
        organization
          ? getOrgMembers(organization.id)
          : Promise.resolve({ items: [] }),
        getWorkspaceMembers(workspace.id),
        organization
          ? getInvitations(organization.id)
          : Promise.resolve({ items: [] }),
      ]);
      setOrgMembers(org.items);
      setWorkspaceMembers(members.items);
      setInvitations(invites.items.filter((item) => item.status === 'pending'));
    } catch {
      setOrgMembers([]);
      setWorkspaceMembers([]);
    } finally {
      setLoading(false);
    }
  }, [workspace]);

  useEffect(() => {
    void refresh();
  }, [workspace?.id]);

  const submit = async () => {
    const values = await form.validateFields();
    try {
      if (adding === 'invite' && organizationId) {
        const invitation = await inviteToOrganization(organizationId, {
          email: values.identifier,
          role: values.role,
        });
        message.success(
          invitation.status === 'accepted'
            ? '该账号已存在，已直接加入组织'
            : '邀请已发出，对方首次登录时自动加入',
        );
      } else if (adding === 'org' && organizationId) {
        await addOrgMember(organizationId, {
          identifier: values.identifier,
          role: values.role,
        });
        message.success('已加入组织');
      } else if (adding === 'workspace' && workspace) {
        await addWorkspaceMember(workspace.id, {
          identifier: values.identifier,
          role: values.role,
        });
        message.success('已加入项目');
      }
      setAdding(null);
      form.resetFields();
      await refresh();
    } catch {
      // 失败提示由 requestErrorConfig 统一弹出
    }
  };

  const memberColumns = (
    roles: string[],
    labels: Record<string, string>,
    onRoleChange: (userId: string, role: string) => Promise<void>,
    onRemove: (userId: string) => Promise<void>,
  ) => [
    {
      title: '成员',
      render: (_: unknown, item: Member) => (
        <div>
          <strong>{item.display_name}</strong>
          <div style={{ color: '#64748b', fontSize: 12 }}>
            {item.username}
            {item.email ? ` · ${item.email}` : ''}
          </div>
        </div>
      ),
    },
    {
      title: '角色',
      width: 220,
      render: (_: unknown, item: Member) => (
        <Select
          size="small"
          value={item.role}
          style={{ width: 160 }}
          options={roles.map((role) => ({
            label: labels[role] ?? role,
            value: role,
          }))}
          onChange={(role) => void onRoleChange(item.user_id, role)}
        />
      ),
    },
    {
      title: '操作',
      width: 100,
      render: (_: unknown, item: Member) => (
        <Popconfirm
          title={`移除 ${item.display_name}？`}
          description="移除后其会话会立即失效。"
          onConfirm={() => void onRemove(item.user_id)}
        >
          <Button type="link" size="small" danger>
            移除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <>
      <section style={{ marginBottom: 24 }}>
        <header
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 12,
          }}
        >
          <Space>
            <strong>组织成员</strong>
            <Tag>{orgMembers.length}</Tag>
          </Space>
          <Space>
            <Button
              size="small"
              icon={<PlusOutlined />}
              onClick={() => {
                form.resetFields();
                setAdding('org');
              }}
            >
              添加已有账号
            </Button>
            <Button
              type="primary"
              size="small"
              icon={<MailOutlined />}
              onClick={() => {
                form.resetFields();
                setAdding('invite');
              }}
            >
              按邮箱邀请
            </Button>
          </Space>
        </header>
        <Table
          size="small"
          rowKey="user_id"
          loading={loading}
          pagination={false}
          dataSource={orgMembers}
          columns={memberColumns(
            ORG_ROLES,
            ORG_ROLE_LABEL,
            async (userId, role) => {
              if (!organizationId) return;
              await updateOrgMemberRole(
                organizationId,
                userId,
                role as OrgRole,
              );
              message.success('角色已更新');
              await refresh();
            },
            async (userId) => {
              if (!organizationId) return;
              await removeOrgMember(organizationId, userId);
              message.success('已移出组织');
              await refresh();
            },
          )}
        />
      </section>

      <section style={{ marginBottom: 24 }}>
        <header style={{ marginBottom: 12 }}>
          <Space>
            <strong>待接受的邀请</strong>
            <Tag>{invitations.length}</Tag>
            <span style={{ color: '#64748b', fontSize: 12 }}>
              账号不存在时留待处理，对方首次登录自动接受
            </span>
          </Space>
        </header>
        <Table
          size="small"
          rowKey="id"
          loading={loading}
          pagination={false}
          dataSource={invitations}
          locale={{ emptyText: '没有待接受的邀请' }}
          columns={[
            { title: '邮箱', dataIndex: 'email' },
            {
              title: '角色',
              width: 120,
              render: (_, item) => ORG_ROLE_LABEL[item.role] ?? item.role,
            },
            {
              title: '过期时间',
              width: 140,
              render: (_, item) => item.expires_at.slice(0, 10),
            },
            {
              title: '操作',
              width: 100,
              render: (_, item) => (
                <Popconfirm
                  title="撤销这条邀请？"
                  onConfirm={async () => {
                    if (!organizationId) return;
                    await revokeInvitation(organizationId, item.id);
                    message.success('已撤销');
                    await refresh();
                  }}
                >
                  <Button type="link" size="small" danger>
                    撤销
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </section>

      <section>
        <header
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 12,
          }}
        >
          <Space>
            <strong>项目成员</strong>
            <Tag>{workspaceMembers.length}</Tag>
            <span style={{ color: '#64748b', fontSize: 12 }}>
              只有组织成员才能加进项目
            </span>
          </Space>
          <Button
            type="primary"
            size="small"
            icon={<PlusOutlined />}
            onClick={() => {
              form.resetFields();
              setAdding('workspace');
            }}
          >
            添加项目成员
          </Button>
        </header>
        <Table
          size="small"
          rowKey="user_id"
          loading={loading}
          pagination={false}
          dataSource={workspaceMembers}
          columns={memberColumns(
            WORKSPACE_ROLES,
            WORKSPACE_ROLE_LABEL,
            async (userId, role) => {
              if (!workspace) return;
              await updateWorkspaceMemberRole(
                workspace.id,
                userId,
                role as WorkspaceRole,
              );
              message.success('角色已更新，该成员需重新登录');
              await refresh();
            },
            async (userId) => {
              if (!workspace) return;
              await removeWorkspaceMember(workspace.id, userId);
              message.success('已移出项目');
              await refresh();
            },
          )}
        />
      </section>

      <Modal
        open={adding !== null}
        title={
          adding === 'invite'
            ? '按邮箱邀请加入组织'
            : adding === 'org'
              ? '添加已有账号'
              : '添加项目成员'
        }
        okText="添加"
        cancelText="取消"
        onCancel={() => setAdding(null)}
        onOk={() => void submit()}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item
            label={adding === 'invite' ? '邮箱' : '账号'}
            name="identifier"
            rules={[{ required: true, message: '请输入用户名或邮箱' }]}
            extra={
              adding === 'invite'
                ? '账号不存在也没关系，会留成待接受的邀请。'
                : '账号需已存在。组织成员才能加进项目。'
            }
          >
            <Input
              placeholder={
                adding === 'invite' ? 'name@company.com' : '用户名或邮箱'
              }
            />
          </Form.Item>
          <Form.Item
            label="角色"
            name="role"
            initialValue={adding === 'org' ? 'member' : 'viewer'}
          >
            <Select
              options={(adding === 'org' ? ORG_ROLES : WORKSPACE_ROLES).map(
                (role) => ({
                  label:
                    adding === 'org'
                      ? ORG_ROLE_LABEL[role as OrgRole]
                      : WORKSPACE_ROLE_LABEL[role as WorkspaceRole],
                  value: role,
                }),
              )}
            />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
