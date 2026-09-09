import { FolderOpenOutlined } from '@ant-design/icons';
import { Card, Empty, Space, Tag, Typography } from 'antd';
import { Link } from 'react-router-dom';
import { useSession } from '../session';

const ROLE_LABEL: Record<string, string> = {
  owner: '负责人',
  member: '成员',
};

export default function HubsPage() {
  const { session } = useSession();
  const hubs = session?.hubs ?? [];

  return (
    <div className="page">
      <Typography.Title level={4}>我的门户</Typography.Title>
      <Typography.Paragraph type="secondary">
        只显示你是成员的门户——别人负责的门户在这里看不到。
      </Typography.Paragraph>
      {hubs.length === 0 ? (
        <Empty description="你还没有被加入任何门户，请联系平台运营者" />
      ) : (
        <div className="card-grid">
          {hubs.map((hub) => (
            <Link key={hub.id} to={`/hubs/${hub.id}`}>
              <Card hoverable className="hub-card">
                <Card.Meta
                  avatar={<FolderOpenOutlined style={{ fontSize: 22, color: '#4f7cff' }} />}
                  title={
                    <Space size={8}>
                      {hub.name}
                      {hub.my_role && (
                        <Tag color={hub.my_role === 'owner' ? 'blue' : 'default'}>
                          {ROLE_LABEL[hub.my_role] ?? hub.my_role}
                        </Tag>
                      )}
                    </Space>
                  }
                  description={hub.description || hub.slug}
                />
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
