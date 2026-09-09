import { CheckOutlined, DownOutlined } from '@ant-design/icons';
import { useModel } from '@umijs/max';
import { Avatar, Button, Dropdown, Space, Typography } from 'antd';
import type { Workspace } from '@/services/eval';

export default function WorkspaceSwitcher() {
  const { initialState, setInitialState } = useModel('@@initialState');
  const state = initialState as typeof initialState & {
    workspaces?: Workspace[];
    currentWorkspace?: Workspace;
  };
  const workspace = state?.currentWorkspace;
  const workspaces = state?.workspaces ?? [];

  return (
    <Dropdown
      trigger={['click']}
      menu={{
        selectedKeys: workspace ? [workspace.id] : [],
        items: workspaces.map((item) => ({
          key: item.id,
          icon: <Avatar size={24}>{item.name.slice(0, 1)}</Avatar>,
          label: (
            <Space vertical size={0} style={{ minWidth: 160 }}>
              <Typography.Text strong>{item.name}</Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {item.role} · {item.description}
              </Typography.Text>
            </Space>
          ),
          extra: item.id === workspace?.id ? <CheckOutlined /> : undefined,
          onClick: () => {
            localStorage.setItem('eval-workspace-id', item.id);
            setInitialState((previous) => ({ ...previous, currentWorkspace: item }));
          },
        })),
      }}
    >
      <Button type="text" className="workspace-switcher">
        <Avatar size={28}>{workspace?.name.slice(0, 1) ?? 'W'}</Avatar>
        <span className="workspace-switcher__copy">
          <strong>{workspace?.name ?? '选择工作区'}</strong>
          <small>{workspace?.role ?? 'No workspace'}</small>
        </span>
        <DownOutlined />
      </Button>
    </Dropdown>
  );
}
