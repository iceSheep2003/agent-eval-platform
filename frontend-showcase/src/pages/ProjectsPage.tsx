import { FolderOpenOutlined } from '@ant-design/icons';
import { Card, Empty, Space, Tag, Typography } from 'antd';
import { Link } from 'react-router-dom';
import { useSession } from '../session';

const ROLE_LABEL: Record<string, string> = {
  owner: '负责人',
  member: '成员',
};

export default function ProjectsPage() {
  const { session } = useSession();
  const projects = session?.projects ?? [];

  return (
    <div className="page">
      <Typography.Title level={4}>我的项目</Typography.Title>
      <Typography.Paragraph type="secondary">
        只显示你是成员的项目——别人负责的项目在这里看不到。
      </Typography.Paragraph>
      {projects.length === 0 ? (
        <Empty description="你还没有被加入任何项目，请联系平台运营者" />
      ) : (
        <div className="card-grid">
          {projects.map((project) => (
            <Link key={project.id} to={`/projects/${project.id}`}>
              <Card hoverable className="project-card">
                <Card.Meta
                  avatar={<FolderOpenOutlined style={{ fontSize: 22, color: '#4f7cff' }} />}
                  title={
                    <Space size={8}>
                      {project.name}
                      {project.my_role && (
                        <Tag color={project.my_role === 'owner' ? 'blue' : 'default'}>
                          {ROLE_LABEL[project.my_role] ?? project.my_role}
                        </Tag>
                      )}
                    </Space>
                  }
                  description={project.description || project.slug}
                />
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
