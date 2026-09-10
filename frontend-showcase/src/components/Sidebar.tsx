import {
  FileTextOutlined,
  FolderOpenOutlined,
  FolderOutlined,
  ReadOutlined,
  RobotOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { Empty, Input, Skeleton, Tree, Typography } from 'antd';
import type { DataNode } from 'antd/es/tree';
import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { listAgents, type PortalAgent } from '../api/portal';
import { groupDocs } from '../docs';
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
const DOC_GROUP_KEY = (group: string) => `docgroup:${group}`;
const DOC_KEY = (slug: string) => `doc:${slug}`;

export default function Sidebar() {
  const { session } = useSession();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { hubId, agentId, slug } = useParams();
  const [nodes, setNodes] = useState<HubNode[]>([]);
  const [expanded, setExpanded] = useState<string[]>([]);
  const [keyword, setKeyword] = useState('');

  const hubs = session?.hubs ?? [];
  // 文档区用同一块侧栏，但换成文档目录——避免在文档页还占着一栏 Agent 树
  const inDocs = pathname.startsWith('/docs');

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

  // 进文档区时把分组都展开——一共没几组，让它自己找反而费事
  useEffect(() => {
    if (inDocs) setExpanded(groupDocs().map((item) => DOC_GROUP_KEY(item.group)));
  }, [inDocs]);

  const lowered = keyword.trim().toLowerCase();

  const hubTree = useMemo<DataNode[]>(
    () =>
      nodes
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
        .filter((node) => !lowered || (node.children?.length ?? 0) > 0),
    [nodes, lowered],
  );

  const docTree = useMemo<DataNode[]>(
    () =>
      groupDocs()
        .map((group) => ({
          key: DOC_GROUP_KEY(group.group),
          title: group.group,
          icon: <ReadOutlined />,
          selectable: false,
          children: group.items
            .filter(
              (doc) =>
                !lowered ||
                `${doc.title} ${doc.summary}`.toLowerCase().includes(lowered),
            )
            .map((doc) => ({
              key: DOC_KEY(doc.slug),
              title: doc.title,
              isLeaf: true,
              icon: <FileTextOutlined />,
            })),
        }))
        .filter((node) => !lowered || (node.children?.length ?? 0) > 0),
    [lowered],
  );

  const treeData = inDocs ? docTree : hubTree;

  const selectedKeys = inDocs
    ? slug
      ? [DOC_KEY(slug)]
      : []
    : hubId && agentId
      ? [AGENT_KEY(hubId, agentId)]
      : [];

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <Typography.Text strong>{inDocs ? '使用文档' : '门户'}</Typography.Text>
        <Typography.Text type="secondary" className="sidebar-count">
          {inDocs ? groupDocs().reduce((sum, g) => sum + g.items.length, 0) : hubs.length}
        </Typography.Text>
      </div>

      <div className="sidebar-search">
        <Input
          allowClear
          size="small"
          prefix={<SearchOutlined />}
          placeholder={inDocs ? '搜索文档' : '搜索 Agent'}
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
        />
      </div>

      <div className="sidebar-tree">
        {treeData.length === 0 ? (
          <Empty
            image={null}
            description={
              <Typography.Text type="secondary">
                {inDocs ? '没有匹配的文档' : '没有匹配的门户'}
              </Typography.Text>
            }
          />
        ) : (
          <Tree
            showIcon
            blockNode
            treeData={treeData}
            expandedKeys={expanded}
            selectedKeys={selectedKeys}
            onExpand={(keys) => setExpanded(keys as string[])}
            onSelect={(keys) => {
              const key = String(keys[0] ?? '');
              if (key.startsWith('doc:')) {
                navigate(`/docs/${key.slice(4)}`);
                return;
              }
              if (key.startsWith('agent:')) {
                const [, nextHub, nextAgent] = key.split(':');
                navigate(`/hubs/${nextHub}/agents/${nextAgent}`);
              }
            }}
          />
        )}
      </div>

      <div className="sidebar-foot">
        {inDocs ? <FileTextOutlined /> : <RobotOutlined />}
        <span>{inDocs ? '选中文档查看正文' : '选中 Agent 开始对话'}</span>
      </div>
    </aside>
  );
}
