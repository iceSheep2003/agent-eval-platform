import { LogoutOutlined, RobotOutlined } from '@ant-design/icons';
import { Avatar, Button, Dropdown, Layout, Space, Typography } from 'antd';
import type { ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useSession } from '../session';

const { Header, Content } = Layout;

export default function AppShell({ children }: { children: ReactNode }) {
  const { session, logout } = useSession();
  const navigate = useNavigate();

  return (
    <Layout className="app-layout">
      <Header className="app-header">
        <Link to="/" className="brand">
          <RobotOutlined />
          <span>Eval Loom 展示平台</span>
        </Link>
        <Space size={12}>
          <Typography.Text type="secondary">
            {session?.projects.length ?? 0} 个项目
          </Typography.Text>
          <Dropdown
            menu={{
              items: [
                {
                  key: 'logout',
                  icon: <LogoutOutlined />,
                  label: '退出登录',
                  onClick: async () => {
                    await logout();
                    navigate('/login');
                  },
                },
              ],
            }}
          >
            <Button type="text">
              <Space size={8}>
                <Avatar size="small" style={{ background: '#4f7cff' }}>
                  {session?.user.display_name?.slice(0, 1) ?? '?'}
                </Avatar>
                {session?.user.display_name}
              </Space>
            </Button>
          </Dropdown>
        </Space>
      </Header>
      <Content className="app-content">{children}</Content>
    </Layout>
  );
}
