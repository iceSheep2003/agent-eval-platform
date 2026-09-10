import {
  FolderOpenOutlined,
  FolderOutlined,
  MessageOutlined,
  RobotOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { Empty, Input, Skeleton, Tree, Typography } from 'antd';
import type { DataNode } from 'antd/es/tree';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { listAgents, type PortalAgent } from '../api/portal';
import { useSession } from '../session';

interface HubNode {
  hubId: string;
  hubName: string;
  agents: PortalAgent[];
  loading: boolean;
}

/** 节点 key 前缀，避免门户 ID 与 Agent ID 撞车。 */
const HUB_KEY = (id: string) => `hub:${id}`;
const AGENT_KEY = (hubId: string, agentId: string) => `agent:${hubId}:${agentId}`;

export default function Sidebar() {
  const { session } = useSession();
  const navigate = useNavigate();
  const { hubId, agentId } = useParams();
  const [nodes, setNodes] = useState<HubNode[]>([]);
  const [expanded, setExpanded] = useState<string[]>([]);
  const [keyword, setKeyword] = useState('');

  const hubs = session?.hubs ?? [];

  // 门户下的 Agent 列表懒加载一次就缓存住——树展开/折叠不该反复打接口
  useEffect(() => {
    let cancelled = false;
    setNodes(hubs.map((hub) => ({ hubId: hub.id, hubName: hub.name, agents: [], loading: true })));
    void Promise.all(
      hubs.map(async (hub) => {
        try {
          return { hubId: hub.id, agents: await listAgents(hub.id) };
        } catch {
          return { hubId: hub.id, agents: [] as PortalAgent[] };
        }
      }),
    ).then((results) => {
      if (cancelled) return;
      const byHub = new Map(results.map((item) => [item.hubId, item.agents]));
      setNodes(
        hubs.map((hub) => ({
          hubId: hub.id,
          hubName: hub.name,
          agents: byHub.get(hub.id) ?? [],
          loading: false,
        })),
      );
    });
    return () => {
      cancelled = true;
    };
  }, [hubs.map((hub) => hub.id).join(','), hubs.length]);

  // 当前路由所在的门户自动展开
  useEffect(() => {
    if (hubId) setExpanded((prev) => (prev.includes(HUB_KEY(hubId)) ? prev : [...prev, HUB_KEY(hubId)]));
  }, [hubId]);

  const treeData = useMemo<DataNode[]>(() => {
    const lowered = keyword.trim().toLowerCase();
    return nodes
      .map((node) => {
        const agents = lowered
          ? node.agents.filter((agent) =>
              `${agent.display_name} ${agent.name}`.toLowerCase().includes(lowered),
            )
          : node.agents;
        return {
          key: HUB_KEY(node.hubId),
          title: node.hubName,
          icon: ({ expanded: isOpen }: { expanded: boolean }) =>
            isOpen ? <FolderOpenOutlined /> : <FolderOutlined />,
          selectable: false,
          children: node.loading
            ? [
                {
                  key: `${HUB_KEY(node.hubId)}:loading`,
                  title: <Skeleton.Input active size="small" style={{ width: 120 }} />,
                  selectable: false,
                  isLeaf: true,
                  icon: null,
                },
              ]
            : agents.map((agent) => ({
                key: AGENT_KEY(node.hubId, agent.id),
                title: agent.display_name,
                isLeaf: true,
                icon: <RobotOutlined />,
              })),
        } as DataNode;
      })
      .filter((node) => !lowered || (node.children?.length ?? 0) > 0);
  }, [nodes, keyword]);

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <Typography.Text strong>门户</Typography.Text>
        <Typography.Text type="secondary" className="sidebar-count">
          {hubs.length}
        </Typography.Text>
      </div>

      <div className="sidebar-search">
        <Input
          allowClear
          size="small"
          prefix={<SearchOutlined />}
          placeholder="搜索 Agent"
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
        />
      </div>

      <div className="sidebar-tree">
        {treeData.length === 0 ? (
          <Empty
            image={null}
            description={<Typography.Text type="secondary">没有匹配的门户</Typography.Text>}
          />
        ) : (
          <Tree
            showIcon
            blockNode
            treeData={treeData}
            expandedKeys={expanded}
            selectedKeys={hubId && agentId ? [AGENT_KEY(hubId, agentId)] : []}
            onExpand={(keys) => setExpanded(keys as string[])}
            onSelect={(keys) => {
              const key = String(keys[0] ?? '');
              if (!key.startsWith('agent:')) return;
              const [, nextHub, nextAgent] = key.split(':');
              navigate(`/hubs/${nextHub}/agents/${nextAgent}`);
            }}
          />
        )}
      </div>

      <div className="sidebar-foot">
        <MessageOutlined />
        <span>选中左侧的 Agent 开始对话</span>
      </div>
    </aside>
  );
}
