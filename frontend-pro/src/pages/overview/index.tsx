import {
  ApiOutlined,
  BranchesOutlined,
  CheckCircleOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  RightOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import {
  PageContainer,
  ProCard,
  StatisticCard,
} from '@ant-design/pro-components';
import { history } from '@umijs/max';
import { Button, Progress, Space, Table, Tag, Typography } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { useWorkspace } from '@/hooks/useWorkspace';
import type { EvalAgent, EvalCapability, EvalRun } from '@/services/eval';
import { getAgents, getCapabilities, getRuns } from '@/services/eval';
import type {
  EvolutionAssetKind,
  EvolutionOverview,
} from '@/services/evolution';
import { getEvolutionOverview } from '@/services/evolution';
import {
  demoEvolutionOverview,
  demoOverviewAgents,
  demoOverviewCapabilities,
  demoOverviewRuns,
} from './evolution-data';
import styles from './style.module.css';

const statusColor: Record<string, string> = {
  running: 'processing',
  completed: 'success',
  failed: 'error',
  paused: 'warning',
  queued: 'default',
};

const assetMeta: Record<
  EvolutionAssetKind,
  {
    label: string;
    route: string;
    color: string;
    icon: React.ReactNode;
    copy: string;
  }
> = {
  skill: {
    label: 'Skill',
    route: '/skills',
    color: '#6d5bd0',
    icon: <BranchesOutlined />,
    copy: '任务指令、工具依赖与执行边界',
  },
  mcp: {
    label: 'MCP',
    route: '/mcp',
    color: '#138b78',
    icon: <ApiOutlined />,
    copy: '工具服务、协议与调用质量',
  },
  knowledge: {
    label: '知识库',
    route: '/knowledge',
    color: '#3d72b4',
    icon: <DatabaseOutlined />,
    copy: '知识来源、索引与检索质量',
  },
};

export default function OverviewPage() {
  const workspace = useWorkspace();
  const [runs, setRuns] = useState<EvalRun[]>(demoOverviewRuns);
  const [agents, setAgents] = useState<EvalAgent[]>(demoOverviewAgents);
  const [capabilities, setCapabilities] = useState<EvalCapability[]>(
    demoOverviewCapabilities,
  );
  const [evolution, setEvolution] = useState<EvolutionOverview>(
    demoEvolutionOverview,
  );
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!workspace) return;
    setLoading(true);
    Promise.all([
      getRuns(workspace.id),
      getAgents(workspace.id),
      getCapabilities(workspace.id),
      getEvolutionOverview(workspace.id),
    ])
      .then(([runData, agentData, capabilityData, evolutionData]) => {
        setRuns(runData.items?.length ? runData.items : demoOverviewRuns);
        setAgents(
          agentData.items?.length ? agentData.items : demoOverviewAgents,
        );
        setCapabilities(
          capabilityData.items?.length
            ? capabilityData.items
            : demoOverviewCapabilities,
        );
        setEvolution(
          evolutionData?.assets?.length ? evolutionData : demoEvolutionOverview,
        );
      })
      .catch(() => {
        setRuns(demoOverviewRuns);
        setAgents(demoOverviewAgents);
        setCapabilities(demoOverviewCapabilities);
        setEvolution(demoEvolutionOverview);
      })
      .finally(() => setLoading(false));
  }, [workspace]);

  const completed = runs.filter((item) => item.status === 'completed');
  const averageScore = completed.length
    ? completed.reduce((sum, item) => sum + item.score, 0) / completed.length
    : 0;
  const running = runs.filter((item) => item.status === 'running').length;
  const dimensions = useMemo(
    () => capabilities.flatMap((item) => item.dimensions).slice(0, 6),
    [capabilities],
  );

  return (
    <PageContainer
      title="评测总览"
      content={`当前工作区：${workspace?.name ?? '-'} · 监控 Agent 质量、评测运行与能力资产健康度`}
    >
      <ProCard gutter={16} ghost wrap className={styles.metrics}>
        <StatisticCard
          loading={loading}
          statistic={{
            title: '运行中',
            value: running,
            icon: <ExperimentOutlined />,
          }}
        />
        <StatisticCard
          loading={loading}
          statistic={{
            title: 'Agent',
            value: agents.length,
            icon: <RobotOutlined />,
          }}
        />
        <StatisticCard
          loading={loading}
          statistic={{
            title: '已完成评测',
            value: completed.length,
            icon: <CheckCircleOutlined />,
          }}
        />
        <StatisticCard
          loading={loading}
          statistic={{
            title: '平均得分',
            value: Math.round(averageScore * 100),
            suffix: '/ 100',
          }}
        />
      </ProCard>

      <section className={styles.assetSummary}>
        <header>
          <div>
            <span>EVOLUTION ASSETS</span>
            <h2>能力资产健康度</h2>
          </div>
          <p>
            详细配置与 TEST / LIVESH / LIVE 生命周期管理请进入左侧对应目录。
          </p>
        </header>
        <div>
          {(Object.keys(assetMeta) as EvolutionAssetKind[]).map((kind) => {
            const meta = assetMeta[kind];
            const assets = evolution.assets.filter(
              (asset) => asset.kind === kind,
            );
            const live = assets.filter(
              (asset) => asset.channels.live?.status === 'active',
            ).length;
            const pending = evolution.proposals.filter(
              (proposal) =>
                proposal.asset_kind === kind && proposal.status === 'pending',
            ).length;
            return (
              <article key={kind}>
                <span
                  style={{ color: meta.color, background: `${meta.color}10` }}
                >
                  {meta.icon}
                </span>
                <div>
                  <h3>{meta.label}</h3>
                  <p>{meta.copy}</p>
                  <Space size={16}>
                    <small>{assets.length} 个资产</small>
                    <small>{live} 个 LIVE</small>
                    <small>{pending} 个待审提案</small>
                  </Space>
                </div>
                <Button
                  type="text"
                  icon={<RightOutlined />}
                  onClick={() => history.push(meta.route)}
                >
                  进入管理
                </Button>
              </article>
            );
          })}
        </div>
      </section>

      <div className={styles.grid}>
        <ProCard title="最近运行" headerBordered>
          <Table<EvalRun>
            rowKey="id"
            loading={loading}
            pagination={false}
            dataSource={runs.slice(0, 6)}
            columns={[
              {
                title: '运行',
                dataIndex: 'name',
                render: (_, item) => (
                  <Space orientation="vertical" size={0}>
                    <Typography.Text strong>{item.name}</Typography.Text>
                    <Typography.Text type="secondary">
                      {item.agent_name} · {item.dataset_name}
                    </Typography.Text>
                  </Space>
                ),
              },
              {
                title: '状态',
                dataIndex: 'status',
                width: 100,
                render: (value) => (
                  <Tag color={statusColor[value]}>{value}</Tag>
                ),
              },
              {
                title: '进度',
                dataIndex: 'progress',
                width: 150,
                render: (value) => <Progress percent={value} size="small" />,
              },
              {
                title: '得分',
                dataIndex: 'score',
                width: 80,
                render: (value, item) =>
                  item.status === 'completed' ? Math.round(value * 100) : '-',
              },
            ]}
          />
        </ProCard>
        <ProCard title="能力信号" headerBordered>
          <Space orientation="vertical" size={18} className={styles.capabilities}>
            {dimensions.map((item) => (
              <div key={item.id}>
                <span>
                  <Typography.Text>{item.name}</Typography.Text>
                  <Typography.Text strong>{item.score}</Typography.Text>
                </span>
                <Progress
                  percent={item.score}
                  showInfo={false}
                  strokeColor={
                    item.score < item.threshold ? '#d4380d' : '#315efb'
                  }
                />
              </div>
            ))}
          </Space>
        </ProCard>
      </div>
    </PageContainer>
  );
}
