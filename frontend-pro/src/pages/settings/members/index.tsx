/**
 * 组织与成员管理。
 *
 * 两层角色分开展示（对齐 Langfuse）：
 * - 组织成员：管成员、建项目；角色 owner / admin / member / viewer
 * - 项目成员：管本项目的评测资产；角色 owner / admin / evaluator / developer / viewer
 *
 * 组织里没有账号的人，先加到组织才能加进项目。
 */

import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
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
  Tag,
} from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { useWorkspace } from '@/hooks/useWorkspace';
import type { Member, OrgRole, WorkspaceRole } from '@/services/eval/members';
import {
  addOrgMember,
  addWorkspaceMember,
  getOrgMembers,
  getOrganizations,
  getWorkspaceMembers,
  removeOrgMember,
  removeWorkspaceMember,
  updateOrgMemberRole,
  updateWorkspaceMemberRole,
} from '@/services/eval/members';

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
  const workspace = useWorkspace();
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [organizationId, setOrganizationId] = useState<string>();
  const [orgMembers, setOrgMembers] = useState<Member[]>([]);
  const [workspaceMembers, setWorkspaceMembers] = useState<Member[]>([]);
  const [adding, setAdding] = useState<'org' | 'workspace' | null>(null);

  const refresh = useCallback(async () => {
    if (!workspace) return;
    setLoading(true);
    try {
      const organizations = await getOrganizations();
      const organization = organizations.items[0];
      setOrganizationId(organization?.id);
      const [org, members] = await Promise.all([
        organization ? getOrgMembers(organization.id) : Promise.resolve({ items: [] }),
        getWorkspaceMembers(workspace.id),
      ]);
      setOrgMembers(org.items);
      setWorkspaceMembers(members.items);
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
      if (adding === 'org' && organizationId) {
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
    scope: 'org' | 'workspace',
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
          options={roles.map((role) => ({ label: labels[role] ?? role, value: role }))}
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
    <PageContainer
      title="组织与成员"
      content="组织管成员和项目；项目成员管本项目的 Agent、数据集与评测资产。两层角色职责不同。"
      extra={
        <Button icon={<ReloadOutlined />} onClick={() => void refresh()}>
          刷新
        </Button>
      }
    >
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
          <Button
            type="primary"
            size="small"
            icon={<PlusOutlined />}
            onClick={() => {
              form.resetFields();
              setAdding('org');
            }}
          >
            添加组织成员
          </Button>
        </header>
        <Table
          size="small"
          rowKey="user_id"
          loading={loading}
          pagination={false}
          dataSource={orgMembers}
          columns={memberColumns(
            'org',
            ORG_ROLES,
            ORG_ROLE_LABEL,
            async (userId, role) => {
              if (!organizationId) return;
              await updateOrgMemberRole(organizationId, userId, role as OrgRole);
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
            'workspace',
            WORKSPACE_ROLES,
            WORKSPACE_ROLE_LABEL,
            async (userId, role) => {
              if (!workspace) return;
              await updateWorkspaceMemberRole(workspace.id, userId, role as WorkspaceRole);
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
        title={adding === 'org' ? '添加组织成员' : '添加项目成员'}
        okText="添加"
        cancelText="取消"
        onCancel={() => setAdding(null)}
        onOk={() => void submit()}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item
            label="账号"
            name="identifier"
            rules={[{ required: true, message: '请输入用户名或邮箱' }]}
            extra="账号需已存在。组织成员才能加进项目。"
          >
            <Input placeholder="用户名或邮箱" />
          </Form.Item>
          <Form.Item
            label="角色"
            name="role"
            initialValue={adding === 'org' ? 'member' : 'viewer'}
          >
            <Select
              options={(adding === 'org' ? ORG_ROLES : WORKSPACE_ROLES).map((role) => ({
                label:
                  adding === 'org'
                    ? ORG_ROLE_LABEL[role as OrgRole]
                    : WORKSPACE_ROLE_LABEL[role as WorkspaceRole],
                value: role,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}
