import {
  ApiOutlined,
  BranchesOutlined,
  CheckCircleFilled,
  ClockCircleOutlined,
  DatabaseOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import {
  App,
  Button,
  Descriptions,
  Empty,
  Input,
  Modal,
  Progress,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
} from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useWorkspace } from '@/hooks/useWorkspace';
import type {
  AssetChannel,
  CapabilityAsset,
  CapabilityBinding,
  CapabilityKind,
  CapabilityVersion,
  ChannelName,
  ResourceMetrics,
} from '@/services/capability';
import {
  createCapabilityAsset,
  createCapabilityVersion,
  getResourceMetrics,
  listCapabilityAssets,
  listCapabilityVersions,
  listProviderBindings,
} from '@/services/capability';
import styles from './style.module.css';

type Props = { kind: CapabilityKind };

const CHANNELS: ChannelName[] = ['test', 'livesh', 'live'];

const channelMeta: Record<
  ChannelName,
  { label: string; title: string; copy: string }
> = {
  test: { label: 'TEST', title: '离线验证', copy: '固定测试集与发布门禁' },
  livesh: {
    label: 'LIVESH',
    title: '影子验证',
    copy: '复制真实流量，不影响用户',
  },
  live: { label: 'LIVE', title: '生产版本', copy: '在线监控与快速回退' },
};

const pageMeta: Record<
  CapabilityKind,
  {
    title: string;
    description: string;
    noun: string;
    color: string;
    icon: React.ReactNode;
  }
> = {
  skill: {
    title: 'Skill 管理',
    description: '管理 Agent 的可复用任务能力、指令、依赖和评测版本。',
    noun: 'Skill',
    color: '#6d5bd0',
    icon: <BranchesOutlined />,
  },
  mcp: {
    title: 'MCP 管理',
    description: '管理工具服务、Schema、鉴权、调用质量和兼容版本。',
    noun: 'MCP Server',
    color: '#138b78',
    icon: <ApiOutlined />,
  },
  knowledge_base: {
    title: '知识库管理',
    description: '管理知识来源、索引构建、检索质量和内容版本。',
    noun: '知识库',
    color: '#3d72b4',
    icon: <DatabaseOutlined />,
  },
};

/** 新建资源时预填的 spec 骨架——把必填项摆在明面上，省得用户对着空对象猜。 */
const specTemplate: Record<CapabilityKind, Record<string, unknown>> = {
  skill: {
    kind: 'skill',
    instructions: '',
    input_schema: { type: 'object' },
    output_schema: { type: 'object' },
    allowed_tools: [],
    max_steps: 8,
    timeout_ms: 12000,
  },
  mcp: {
    kind: 'mcp',
    endpoint: 'https://',
    transport: 'streamable-http',
    authentication: { type: 'bearer', secret_ref: '' },
    tools: [
      { name: 'tool.name', description: '', input_schema: { type: 'object' } },
    ],
  },
  knowledge_base: {
    kind: 'knowledge_base',
    embedding_model: '',
    index_name: '',
    chunk_strategy: { mode: 'fixed', size: 512, overlap: 64 },
    retrieval: { mode: 'hybrid', top_k: 5 },
    sources: [
      { id: 's1', name: '', connector: 'http', uri: 'https://', enabled: true },
    ],
  },
};

const lifecycleColor: Record<string, string> = {
  draft: 'default',
  evaluating: 'processing',
  ready: 'success',
  blocked: 'error',
  retired: 'default',
};

function channelOf(
  channels: AssetChannel[],
  name: ChannelName,
): AssetChannel | undefined {
  return channels.find((item) => item.channel === name);
}

/** 解析后端 422 的 `ValidationIssue[]`：把 `a.b.c` 的字段路径原样带出来。 */
function parseIssues(error: unknown): string[] {
  const data = (error as { data?: { errorMessage?: string } })?.data;
  if (!data?.errorMessage) return [];
  return data.errorMessage.split('；').filter(Boolean);
}

function SpecView({ spec }: { spec: Record<string, unknown> }) {
  const entries = Object.entries(spec).filter(([key]) => key !== 'kind');
  return (
    <div className={styles.domainGrid}>
      <section className={styles.primarySpec}>
        <header>
          <div>
            <span>SPEC</span>
            <strong>版本配置</strong>
          </div>
        </header>
        <Descriptions column={1} size="small">
          {entries.map(([key, value]) => (
            <Descriptions.Item key={key} label={key}>
              {typeof value === 'string' ? (
                value
              ) : (
                <code>{JSON.stringify(value)}</code>
              )}
            </Descriptions.Item>
          ))}
        </Descriptions>
      </section>
    </div>
  );
}

export default function AssetWorkspace({ kind }: Props) {
  const workspace = useWorkspace();
  const { message } = App.useApp();
  const meta = pageMeta[kind];

  const [assets, setAssets] = useState<CapabilityAsset[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [channel, setChannel] = useState<ChannelName>('test');
  const [versions, setVersions] = useState<CapabilityVersion[]>([]);
  const [bindings, setBindings] = useState<CapabilityBinding[]>([]);
  const [metrics, setMetrics] = useState<ResourceMetrics | null>(null);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState<'create' | 'version' | null>(null);
  const [form, setForm] = useState({
    name: '',
    description: '',
    tenantId: '',
    spec: '',
  });

  const loadAssets = useCallback(async () => {
    if (!workspace) return;
    setLoading(true);
    try {
      const result = await listCapabilityAssets(workspace.id, kind);
      setAssets(result?.items ?? []);
    } catch {
      setAssets([]);
    } finally {
      setLoading(false);
    }
  }, [workspace, kind]);

  useEffect(() => {
    void loadAssets();
  }, [loadAssets]);

  const filtered = useMemo(
    () =>
      assets.filter((asset) =>
        (asset.name + asset.description)
          .toLowerCase()
          .includes(query.toLowerCase()),
      ),
    [assets, query],
  );
  const selected =
    assets.find((asset) => asset.id === selectedId) ?? filtered[0];

  // 版本与引用是**两套接口**：通道只给指针，版本详情单独取。
  useEffect(() => {
    if (!workspace || !selected) {
      setVersions([]);
      setBindings([]);
      return;
    }
    void Promise.all([
      listCapabilityVersions(workspace.id, selected.id),
      listProviderBindings(workspace.id, selected.id),
    ])
      .then(([versionResult, bindingResult]) => {
        setVersions(versionResult?.items ?? []);
        setBindings(bindingResult?.items ?? []);
      })
      .catch(() => {
        setVersions([]);
        setBindings([]);
      });
  }, [workspace, selected]);

  const activeChannel = selected
    ? channelOf(selected.channels, channel)
    : undefined;
  const activeVersion = versions.find(
    (item) => item.id === activeChannel?.version_id,
  );

  useEffect(() => {
    if (!workspace || !selected || !activeVersion) {
      setMetrics(null);
      return;
    }
    void getResourceMetrics(workspace.id, selected.id, activeVersion.id, 24)
      .then(setMetrics)
      .catch(() => setMetrics(null));
  }, [workspace, selected, activeVersion]);

  const openModal = (next: 'create' | 'version') => {
    setForm({
      name: '',
      description: '',
      tenantId: '',
      spec: JSON.stringify(specTemplate[kind], null, 2),
    });
    setModal(next);
  };

  const submit = async () => {
    if (!workspace) return;
    let spec: Record<string, unknown>;
    try {
      spec = JSON.parse(form.spec);
    } catch {
      message.error('spec 不是合法 JSON');
      return;
    }
    setLoading(true);
    try {
      if (modal === 'create') {
        const created = await createCapabilityAsset(workspace.id, {
          kind,
          name: form.name,
          description: form.description,
          spec,
          tenant_id: form.tenantId || null,
        });
        message.success('已创建');
        await loadAssets();
        setSelectedId(created.id);
      } else if (selected) {
        await createCapabilityVersion(workspace.id, selected.id, { spec });
        message.success('已冻结新版本');
        setVersions(
          (await listCapabilityVersions(workspace.id, selected.id)).items ?? [],
        );
      }
      setModal(null);
    } catch (error) {
      const issues = parseIssues(error);
      message.error(issues.length ? issues.join('；') : '提交失败');
    } finally {
      setLoading(false);
    }
  };

  const versionView = (
    <Table<CapabilityVersion>
      rowKey="id"
      size="small"
      pagination={false}
      dataSource={versions}
      columns={[
        { title: '版本', dataIndex: 'version_label' },
        {
          title: '状态',
          dataIndex: 'lifecycle',
          render: (value: string) => (
            <Tag color={lifecycleColor[value] ?? 'default'}>{value}</Tag>
          ),
        },
        {
          title: '冻结时间',
          dataIndex: 'created_at',
          render: (value: string) => new Date(value).toLocaleString('zh-CN'),
        },
        {
          title: '配置',
          render: (_, row) => (
            <Tooltip title={<code>{JSON.stringify(row.spec)}</code>}>
              <a>查看 spec</a>
            </Tooltip>
          ),
        },
      ]}
    />
  );

  const bindingView = bindings.length ? (
    <Table<CapabilityBinding>
      rowKey="id"
      size="small"
      pagination={false}
      dataSource={bindings}
      columns={[
        {
          title: '引用方 Agent',
          dataIndex: 'consumer_asset_name',
          render: (value: string | null, row) => value ?? row.consumer_asset_id,
        },
        {
          title: '范围',
          dataIndex: 'consumer_version_id',
          render: (value: string | null) =>
            value ? <Tag>指定版本</Tag> : <Tag>全部版本</Tag>,
        },
        {
          title: '解析方式',
          dataIndex: 'resolve_mode',
          render: (value: string, row) =>
            value === 'pinned' ? (
              <Tag color="purple">锁定版本</Tag>
            ) : (
              <Tag color="blue">跟随 {row.provider_channel?.toUpperCase()}</Tag>
            ),
        },
        {
          title: '当前解析到',
          dataIndex: 'resolved_version_label',
          render: (value: string | null) =>
            value ?? <Tag color="warning">通道未绑定版本</Tag>,
        },
      ]}
    />
  ) : (
    <Empty description="还没有 Agent 引用这个资源" />
  );

  const metricsView = metrics ? (
    <div className={styles.evidenceGrid}>
      <article>
        <header>
          <span>调用次数</span>
        </header>
        <strong>{metrics.invocations}</strong>
        <small>近 {metrics.window_hours} 小时</small>
      </article>
      <article>
        <header>
          <span>{metrics.success_metric ?? '成功率'}</span>
          {metrics.success_rate === 1 && <CheckCircleFilled />}
        </header>
        <strong>
          {metrics.success_rate === null
            ? '—'
            : `${Math.round(metrics.success_rate * 100)}%`}
        </strong>
        <small>口径：{metrics.success_metric ?? '该类型暂无口径'}</small>
      </article>
      <article>
        <header>
          <span>P95 延迟</span>
        </header>
        <strong>
          {metrics.p95_latency_ms === null
            ? '—'
            : `${metrics.p95_latency_ms} ms`}
        </strong>
        <small>错误率 {Math.round(metrics.error_rate * 100)}%</small>
      </article>
      <article>
        <header>
          <span>归因覆盖率</span>
        </header>
        <strong>
          {metrics.attribution_coverage === null
            ? '—'
            : `${Math.round(metrics.attribution_coverage * 100)}%`}
        </strong>
        <small>掉下去说明归因规则失效，不是资源变差了</small>
        <Progress
          percent={Math.round((metrics.attribution_coverage ?? 0) * 100)}
          showInfo={false}
          strokeColor={meta.color}
        />
      </article>
    </div>
  ) : (
    <Empty description="该版本还没有可归因的调用数据" />
  );

  return (
    <PageContainer
      title={meta.title}
      content={meta.description}
      extra={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => openModal('create')}
        >
          新建 {meta.noun}
        </Button>
      }
    >
      <section className={styles.summary}>
        <div>
          <span style={{ color: meta.color }}>{meta.icon}</span>
          <small>{meta.noun} 总数</small>
          <strong>{assets.length}</strong>
        </div>
        <i />
        <div>
          <CheckCircleFilled />
          <small>已上 LIVE</small>
          <strong>
            {
              assets.filter(
                (asset) => channelOf(asset.channels, 'live')?.version_id,
              ).length
            }
          </strong>
        </div>
        <i />
        <div>
          <ClockCircleOutlined />
          <small>被引用次数</small>
          <strong>
            {assets.reduce((total, asset) => total + asset.binding_count, 0)}
          </strong>
        </div>
        <Button
          type="text"
          icon={<ReloadOutlined />}
          loading={loading}
          onClick={() => void loadAssets()}
        >
          刷新
        </Button>
      </section>
      <section className={styles.workspace}>
        <aside className={styles.catalog}>
          <header>
            <strong>{meta.noun} 目录</strong>
            <Input
              allowClear
              placeholder={`搜索 ${meta.noun}`}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </header>
          {filtered.map((asset) => (
            <button
              type="button"
              key={asset.id}
              className={asset.id === selected?.id ? styles.assetActive : ''}
              onClick={() => setSelectedId(asset.id)}
            >
              <span
                style={{ color: meta.color, background: `${meta.color}10` }}
              >
                {meta.icon}
              </span>
              <div>
                <strong>{asset.name}</strong>
                <small>
                  {asset.owner} · {asset.binding_count} 处引用
                </small>
                <code>
                  {channelOf(asset.channels, 'live')?.version_label ??
                    'not live'}
                </code>
              </div>
              <i />
            </button>
          ))}
          {!filtered.length && <Empty description={`暂无 ${meta.noun}`} />}
        </aside>
        <main className={styles.detail}>
          {selected ? (
            <>
              <header className={styles.hero}>
                <span
                  style={{ color: meta.color, background: `${meta.color}10` }}
                >
                  {meta.icon}
                </span>
                <div>
                  <Space>
                    <h2>{selected.name}</h2>
                    <Tag>{meta.noun}</Tag>
                    {selected.tenant_scope === 'tenant_bound' && (
                      <Tag color="orange">租户级</Tag>
                    )}
                  </Space>
                  <p>{selected.description || '暂无描述'}</p>
                  <small>
                    {selected.owner} · 更新于{' '}
                    {new Date(
                      selected.updated_at ?? selected.created_at,
                    ).toLocaleString('zh-CN')}
                  </small>
                </div>
                <Space>
                  <Button onClick={() => openModal('version')}>新建版本</Button>
                </Space>
              </header>
              <section className={styles.versionBar}>
                {CHANNELS.map((name) => {
                  const pointer = channelOf(selected.channels, name);
                  const isActive = name === channel;
                  return (
                    <button
                      type="button"
                      key={name}
                      onClick={() => setChannel(name)}
                      style={{ opacity: isActive ? 1 : 0.6, cursor: 'pointer' }}
                    >
                      <span>{channelMeta[name].label}</span>
                      <strong>{pointer?.version_label ?? '未部署'}</strong>
                      <small>{channelMeta[name].copy}</small>
                    </button>
                  );
                })}
              </section>
              <Tabs
                className={styles.tabs}
                items={[
                  {
                    key: 'spec',
                    label: '配置',
                    children: activeVersion ? (
                      <SpecView spec={activeVersion.spec} />
                    ) : (
                      <Empty description="该通道没有绑定版本" />
                    ),
                  },
                  {
                    key: 'versions',
                    label: `版本 ${versions.length}`,
                    children: versionView,
                  },
                  {
                    key: 'bindings',
                    label: `引用 ${bindings.length}`,
                    children: bindingView,
                  },
                  {
                    key: 'metrics',
                    label: '使用质量',
                    children: metricsView,
                  },
                ]}
              />
            </>
          ) : (
            <Empty description={`暂无 ${meta.noun}`} />
          )}
        </main>
      </section>

      <Modal
        open={modal !== null}
        title={
          modal === 'create'
            ? `新建 ${meta.noun}`
            : `为 ${selected?.name} 新建版本`
        }
        onCancel={() => setModal(null)}
        onOk={() => void submit()}
        confirmLoading={loading}
        okText={modal === 'create' ? '创建' : '冻结版本'}
        width={720}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          {modal === 'create' && (
            <>
              <Input
                placeholder="名称（工作区内同类型唯一）"
                value={form.name}
                onChange={(event) =>
                  setForm({ ...form, name: event.target.value })
                }
              />
              <Input
                placeholder="描述"
                value={form.description}
                onChange={(event) =>
                  setForm({ ...form, description: event.target.value })
                }
              />
              {kind === 'knowledge_base' && (
                <Input
                  placeholder="租户 id（留空 = 工作区共享）"
                  value={form.tenantId}
                  onChange={(event) =>
                    setForm({ ...form, tenantId: event.target.value })
                  }
                />
              )}
            </>
          )}
          <Input.TextArea
            rows={14}
            value={form.spec}
            onChange={(event) => setForm({ ...form, spec: event.target.value })}
          />
          <small>spec 一旦冻结不可修改，改动只能通过新建版本。</small>
        </Space>
      </Modal>
    </PageContainer>
  );
}
