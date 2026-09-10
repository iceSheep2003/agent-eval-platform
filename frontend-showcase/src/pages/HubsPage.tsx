import { FolderFilled, TeamOutlined } from '@ant-design/icons';
import { Empty, Tag, Typography } from 'antd';
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
      <Typography.Title level={4} style={{ marginBottom: 4 }}>
        我的门户
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        只显示你是成员的门户——别人负责的门户在这里看不到。点进去，或直接从左边的目录树选 Agent。
      </Typography.Paragraph>

      {hubs.length === 0 ? (
        <Empty description="你还没有被加入任何门户，请联系平台运营者" />
      ) : (
        <div className="folder-grid">
          {hubs.map((hub) => (
            <Link key={hub.id} to={`/hubs/${hub.id}`} className="folder-link">
              <FolderFilled className="folder-icon" />
              <div className="folder-body">
                <div className="folder-name">{hub.name}</div>
                <div className="folder-desc">{hub.description || hub.slug}</div>
              </div>
              {hub.my_role && (
                <Tag
                  className="folder-role"
                  color={hub.my_role === 'owner' ? 'blue' : 'default'}
                  icon={hub.my_role === 'owner' ? <TeamOutlined /> : undefined}
                >
                  {ROLE_LABEL[hub.my_role] ?? hub.my_role}
                </Tag>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
