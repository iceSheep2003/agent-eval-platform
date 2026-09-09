import { ArrowLeftOutlined, MessageOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Empty, Skeleton, Space, Tag, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  getProject,
  listAgents,
  type PortalAgent,
  type PortalChannel,
  type PortalProject,
} from '../api/portal';
import { CHANNEL_COLOR } from '../theme';

function ChannelChips({ channels }: { channels: PortalChannel[] }) {
  return (
    <Space size={6} wrap>
      {channels.map((item) => (
        <Tag
          key={item.channel}
          color={item.bound ? CHANNEL_COLOR[item.channel] : undefined}
          style={item.bound ? undefined : { opacity: 0.55 }}
        >
          {item.channel.toUpperCase()} · {item.bound ? item.version_label : '未绑定'}
        </Tag>
      ))}
    </Space>
  );
}

export default function ProjectPage() {
  const { projectId = '' } = useParams();
  const [project, setProject] = useState<PortalProject | null>(null);
  const [agents, setAgents] = useState<PortalAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([getProject(projectId), listAgents(projectId)])
      .then(([nextProject, nextAgents]) => {
        if (cancelled) return;
        setProject(nextProject);
        setAgents(nextAgents);
        setError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return (
    <div className="page">
      <Link to="/" className="back-link">
        <ArrowLeftOutlined /> 返回项目列表
      </Link>
      <Typography.Title level={4} style={{ marginTop: 12 }}>
        {project?.name ?? '项目'}
      </Typography.Title>
      {project?.description && (
        <Typography.Paragraph type="secondary">{project.description}</Typography.Paragraph>
      )}
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}

      {loading ? (
        <Skeleton active />
      ) : agents.length === 0 ? (
        <Empty description="该项目下还没有 Agent" />
      ) : (
        <div className="card-grid">
          {agents.map((agent) => (
            <Card
              key={agent.id}
              className="agent-card"
              title={agent.display_name}
              extra={
                <Link to={`/projects/${projectId}/agents/${agent.id}`}>
                  <Button type="primary" size="small" icon={<MessageOutlined />}>
                    对话
                  </Button>
                </Link>
              }
            >
              <Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }}>
                {agent.description || agent.name}
              </Typography.Paragraph>
              <ChannelChips channels={agent.channels} />
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
