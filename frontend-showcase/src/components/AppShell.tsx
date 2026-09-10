import { BookOutlined, LogoutOutlined, RobotOutlined } from '@ant-design/icons';
import { Avatar, Button, Dropdown, Layout, Space } from 'antd';
import type { ReactNode } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useSession } from '../session';
import Sidebar from './Sidebar';

const { Header, Content } = Layout;

export default function AppShell({ children }: { children: ReactNode }) {
  const { session, logout } = useSession();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const inDocs = pathname.startsWith('/docs');

  return (
    <Layout className="app-layout">
      <Header className="app-header">
        <Link to="/" className="brand">
          <RobotOutlined />
          <span>Eval Loom 展示平台</span>
        </Link>
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
      </Header>
      <Layout className="app-body">
        <Sidebar />
        <Layout className="app-main">
          <Content className="app-content">{children}</Content>
          <footer className="app-footer">
            <span className="footer-copy">Eval Loom 展示平台</span>
            <nav className="footer-links">
              <Link
                to="/docs"
                className={inDocs ? 'footer-link footer-link-active' : 'footer-link'}
              >
                <BookOutlined /> 使用文档
              </Link>
            </nav>
          </footer>
        </Layout>
      </Layout>
    </Layout>
  );
}
