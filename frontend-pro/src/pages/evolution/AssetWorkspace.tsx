/* biome-ignore-all lint/a11y/noLabelWithoutControl: Ant Design composite inputs are nested inside their labels. */
import {
  ApiOutlined,
  ArrowLeftOutlined,
  ArrowRightOutlined,
  BranchesOutlined,
  CheckCircleFilled,
  ClockCircleOutlined,
  CloudSyncOutlined,
  CodeOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  HistoryOutlined,
  LinkOutlined,
  PlusOutlined,
  ReloadOutlined,
  RollbackOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { history, useParams } from '@umijs/max';
import {
  App,
  Button,
  Empty,
  Input,
  InputNumber,
  Modal,
  Progress,
  Select,
  Skeleton,
  Space,
  Tabs,
  Tag,
} from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useWorkspace } from '@/hooks/useWorkspace';
import type {
  AssetChannel,
  CapabilityDeployment,
  CapabilityAsset,
  CapabilityBinding,
  CapabilityKind,
  CapabilityVersion,
  ChannelName,
  ResourceMetrics,
  RetrievalTestResult,
  PromotionPreview,
} from '@/services/capability';
import {
  checkMcpConnection,
  createCapabilityAsset,
  createCapabilityVersion,
  getCapabilityAsset,
  getPromotionPreview,
  getResourceMetrics,
  listCapabilityAssets,
  listCapabilityDeployments,
  listCapabilityVersions,
  listProviderBindings,
  promoteCapabilityVersion,
  rollbackCapabilityChannel,
  rebuildKnowledgeIndex,
  testKnowledgeRetrieval,
} from '@/services/capability';
import styles from './style.module.css';

type Props = { kind: CapabilityKind };
type Draft = {
  name: string;
  description: string;
  tenantId: string;
  instructions: string;
  allowedTools: string;
  maxSteps: number;
  timeoutMs: number;
  endpoint: string;
  transport: 'stdio' | 'sse' | 'streamable-http';
  authType: string;
  secretRef: string;
  tools: string;
  embeddingModel: string;
  indexName: string;
  chunkSize: number;
  chunkOverlap: number;
  retrievalMode: string;
  topK: number;
  reranker: string;
  sources: string;
};

const CHANNELS: ChannelName[] = ['test', 'livesh', 'live'];
const channelMeta = {
  test: { label: 'TEST', title: '验证', copy: '固定测试集与配置检查' },
  livesh: { label: 'LIVESH', title: '影子', copy: '复制真实流量，不影响用户' },
  live: { label: 'LIVE', title: '生产', copy: '在线监控、受控放量与回退' },
} satisfies Record<ChannelName, { label: string; title: string; copy: string }>;
const pageMeta = {
  skill: {
    title: 'Skill 管理',
    noun: 'Skill',
    description: '管理可复用的任务指令、资源包、工具权限和运行契约。',
    path: '/skills',
    color: '#5b5bd6',
    icon: <BranchesOutlined />,
  },
  mcp: {
    title: 'MCP 管理',
    noun: 'MCP Server',
    description: '管理服务连接、授权、工具发现与调用健康度。',
    path: '/mcp',
    color: '#087f73',
    icon: <ApiOutlined />,
  },
  knowledge_base: {
    title: '知识库管理',
    noun: '知识库',
    description: '管理数据源、切分策略、索引同步与检索质量。',
    path: '/knowledge',
    color: '#b45f28',
    icon: <DatabaseOutlined />,
  },
} satisfies Record<
  CapabilityKind,
  {
    title: string;
    noun: string;
    description: string;
    path: string;
    color: string;
    icon: React.ReactNode;
  }
>;
const emptyDraft: Draft = {
  name: '',
  description: '',
  tenantId: '',
  instructions: '',
  allowedTools: '',
  maxSteps: 8,
  timeoutMs: 12000,
  endpoint: 'https://',
  transport: 'streamable-http',
  authType: 'bearer',
  secretRef: '',
  tools: 'tool.name | 说明这个工具做什么',
  embeddingModel: '',
  indexName: '',
  chunkSize: 800,
  chunkOverlap: 200,
  retrievalMode: 'hybrid',
  topK: 5,
  reranker: '',
  sources: '产品文档 | https://docs.example.com',
};

const channelOf = (channels: AssetChannel[], channel: ChannelName) =>
  channels.find((item) => item.channel === channel);
const formatDate = (value?: string | null) =>
  value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—';
const lines = (value: string) =>
  value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean);

function specFromDraft(
  kind: CapabilityKind,
  draft: Draft,
  base: Record<string, unknown> = {},
) {
  if (kind === 'skill')
    return {
      ...base,
      kind,
      instructions: draft.instructions,
      input_schema: base.input_schema ?? { type: 'object' },
      output_schema: base.output_schema ?? { type: 'object' },
      allowed_tools: draft.allowedTools
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
      max_steps: draft.maxSteps,
      timeout_ms: draft.timeoutMs,
    };
  if (kind === 'mcp')
    return {
      ...base,
      kind,
      endpoint: draft.endpoint,
      transport: draft.transport,
      authentication: { type: draft.authType, secret_ref: draft.secretRef },
      tools: lines(draft.tools).map((line) => {
        const [name, description = ''] = line
          .split('|')
          .map((item) => item.trim());
        return { name, description, input_schema: { type: 'object' } };
      }),
    };
  return {
    ...base,
    kind,
    embedding_model: draft.embeddingModel,
    index_name: draft.indexName,
    chunk_strategy: {
      mode: 'fixed',
      size: draft.chunkSize,
      overlap: draft.chunkOverlap,
    },
    retrieval: {
      mode: draft.retrievalMode,
      top_k: draft.topK,
      ...(draft.reranker ? { reranker: draft.reranker } : {}),
    },
    sources: lines(draft.sources).map((line, index) => {
      const [name, uri = ''] = line.split('|').map((item) => item.trim());
      return {
        id: `source-${index + 1}`,
        name,
        connector: uri.startsWith('http') ? 'http' : 'file',
        uri,
        enabled: true,
      };
    }),
  };
}

function draftFromSpec(spec?: Record<string, unknown>): Draft {
  if (!spec) return { ...emptyDraft };
  const auth = (spec.authentication ?? {}) as Record<string, unknown>;
  const chunk = (spec.chunk_strategy ?? {}) as Record<string, unknown>;
  const retrieval = (spec.retrieval ?? {}) as Record<string, unknown>;
  const tools = (spec.tools ?? []) as Array<Record<string, unknown>>;
  const sources = (spec.sources ?? []) as Array<Record<string, unknown>>;
  return {
    ...emptyDraft,
    instructions: String(spec.instructions ?? ''),
    allowedTools: ((spec.allowed_tools ?? []) as string[]).join(', '),
    maxSteps: Number(spec.max_steps ?? 8),
    timeoutMs: Number(spec.timeout_ms ?? 12000),
    endpoint: String(spec.endpoint ?? 'https://'),
    transport: (spec.transport as Draft['transport']) ?? 'streamable-http',
    authType: String(auth.type ?? 'bearer'),
    secretRef: String(auth.secret_ref ?? ''),
    tools: tools
      .map((tool) => `${tool.name ?? ''} | ${tool.description ?? ''}`)
      .join('\n'),
    embeddingModel: String(spec.embedding_model ?? ''),
    indexName: String(spec.index_name ?? ''),
    chunkSize: Number(chunk.size ?? 800),
    chunkOverlap: Number(chunk.overlap ?? 200),
    retrievalMode: String(retrieval.mode ?? 'hybrid'),
    topK: Number(retrieval.top_k ?? 5),
    reranker: String(retrieval.reranker ?? ''),
    sources: sources
      .map((source) => `${source.name ?? ''} | ${source.uri ?? ''}`)
      .join('\n'),
  };
}

function ResourceEditor({
  kind,
  draft,
  onChange,
  isCreate,
}: {
  kind: CapabilityKind;
  draft: Draft;
  onChange: (next: Draft) => void;
  isCreate: boolean;
}) {
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    onChange({ ...draft, [key]: value });
  return (
    <div className={styles.editorForm}>
      {isCreate && (
        <div className={styles.formGrid}>
          <label>
            <span>名称</span>
            <Input
              value={draft.name}
              onChange={(e) => set('name', e.target.value)}
              placeholder="工作区内唯一"
            />
          </label>
          <label>
            <span>描述</span>
            <Input
              value={draft.description}
              onChange={(e) => set('description', e.target.value)}
              placeholder="说清它解决什么问题"
            />
          </label>
        </div>
      )}
      {kind === 'skill' && (
        <>
          <label>
            <span>核心指令</span>
            <small>激活 Skill 后会加载的完整操作说明</small>
            <Input.TextArea
              rows={8}
              value={draft.instructions}
              onChange={(e) => set('instructions', e.target.value)}
              placeholder="写明步骤、输入输出和异常分支…"
            />
          </label>
          <label>
            <span>允许的工具</span>
            <small>用逗号分隔，权限保持最小化</small>
            <Input
              value={draft.allowedTools}
              onChange={(e) => set('allowedTools', e.target.value)}
              placeholder="web.search, database.query"
            />
          </label>
          <div className={styles.formGrid}>
            <label>
              <span>最大步数</span>
              <InputNumber
                min={1}
                value={draft.maxSteps}
                onChange={(v) => set('maxSteps', v ?? 1)}
              />
            </label>
            <label>
              <span>超时（ms）</span>
              <InputNumber
                min={100}
                step={1000}
                value={draft.timeoutMs}
                onChange={(v) => set('timeoutMs', v ?? 100)}
              />
            </label>
          </div>
        </>
      )}
      {kind === 'mcp' && (
        <>
          <div className={styles.formGrid}>
            <label>
              <span>传输方式</span>
              <Select
                value={draft.transport}
                options={[
                  { value: 'streamable-http', label: 'Streamable HTTP' },
                  { value: 'sse', label: 'SSE（兼容）' },
                  { value: 'stdio', label: 'stdio' },
                ]}
                onChange={(v) => set('transport', v)}
              />
            </label>
            <label>
              <span>服务端点 / 启动命令</span>
              <Input
                value={draft.endpoint}
                onChange={(e) => set('endpoint', e.target.value)}
              />
            </label>
          </div>
          <div className={styles.formGrid}>
            <label>
              <span>鉴权类型</span>
              <Select
                value={draft.authType}
                options={[
                  { value: 'bearer', label: 'Bearer Token' },
                  { value: 'oauth2', label: 'OAuth 2.1' },
                  { value: 'none', label: '无鉴权' },
                ]}
                onChange={(v) => set('authType', v)}
              />
            </label>
            <label>
              <span>密钥引用</span>
              <Input
                value={draft.secretRef}
                onChange={(e) => set('secretRef', e.target.value)}
                placeholder="vault://team/mcp-token"
              />
            </label>
          </div>
          <label>
            <span>工具清单</span>
            <small>每行一个：稳定工具名 | 用途说明</small>
            <Input.TextArea
              rows={7}
              value={draft.tools}
              onChange={(e) => set('tools', e.target.value)}
            />
          </label>
        </>
      )}
      {kind === 'knowledge_base' && (
        <>
          {isCreate && (
            <label>
              <span>租户 ID（可选）</span>
              <Input
                value={draft.tenantId}
                onChange={(e) => set('tenantId', e.target.value)}
                placeholder="留空为工作区共享"
              />
            </label>
          )}
          <div className={styles.formGrid}>
            <label>
              <span>Embedding 模型</span>
              <Input
                value={draft.embeddingModel}
                onChange={(e) => set('embeddingModel', e.target.value)}
              />
            </label>
            <label>
              <span>索引名</span>
              <Input
                value={draft.indexName}
                onChange={(e) => set('indexName', e.target.value)}
              />
            </label>
          </div>
          <label>
            <span>数据源</span>
            <small>每行一个：来源名 | URL 或存储路径</small>
            <Input.TextArea
              rows={6}
              value={draft.sources}
              onChange={(e) => set('sources', e.target.value)}
            />
          </label>
          <div className={styles.formGridThree}>
            <label>
              <span>分块大小</span>
              <InputNumber
                min={1}
                value={draft.chunkSize}
                onChange={(v) => set('chunkSize', v ?? 1)}
              />
            </label>
            <label>
              <span>重叠</span>
              <InputNumber
                min={0}
                value={draft.chunkOverlap}
                onChange={(v) => set('chunkOverlap', v ?? 0)}
              />
            </label>
            <label>
              <span>Top K</span>
              <InputNumber
                min={1}
                value={draft.topK}
                onChange={(v) => set('topK', v ?? 1)}
              />
            </label>
          </div>
          <div className={styles.formGrid}>
            <label>
              <span>检索方式</span>
              <Select
                value={draft.retrievalMode}
                options={[
                  { value: 'hybrid', label: '混合检索' },
                  { value: 'semantic', label: '向量检索' },
                  { value: 'keyword', label: '关键词检索' },
                ]}
                onChange={(v) => set('retrievalMode', v)}
              />
            </label>
            <label>
              <span>Reranker（可选）</span>
              <Input
                value={draft.reranker}
                onChange={(e) => set('reranker', e.target.value)}
              />
            </label>
          </div>
        </>
      )}
    </div>
  );
}

function LifecycleRail({
  asset,
  active,
  onChange,
}: {
  asset: CapabilityAsset;
  active: ChannelName;
  onChange: (channel: ChannelName) => void;
}) {
  return (
    <section className={styles.lifecycleRail} aria-label="版本生命周期">
      {CHANNELS.map((channel, index) => {
        const pointer = channelOf(asset.channels, channel);
        return (
          <div className={styles.stageGroup} key={channel}>
            <button
              type="button"
              className={active === channel ? styles.stageActive : ''}
              onClick={() => onChange(channel)}
            >
              <span className={styles.stageIndex}>{index + 1}</span>
              <div>
                <b>{channelMeta[channel].label}</b>
                <strong>{channelMeta[channel].title}</strong>
                <small>{channelMeta[channel].copy}</small>
              </div>
              <Tag color={pointer?.version_id ? 'success' : 'default'}>
                {pointer?.version_label ?? '未部署'}
              </Tag>
            </button>
            {index < 2 && <ArrowRightOutlined className={styles.stageArrow} />}
          </div>
        );
      })}
    </section>
  );
}

function MetricCards({
  metrics,
  color,
}: {
  metrics: ResourceMetrics | null;
  color: string;
}) {
  if (!metrics)
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="该版本还没有可归因的调用数据"
      />
    );
  const coverage = Math.round((metrics.attribution_coverage ?? 0) * 100);
  return (
    <div className={styles.metricGrid}>
      <article>
        <span>调用量</span>
        <strong>{metrics.invocations}</strong>
        <small>近 {metrics.window_hours} 小时</small>
      </article>
      <article>
        <span>{metrics.success_metric ?? '成功率'}</span>
        <strong>
          {metrics.success_rate === null
            ? '—'
            : `${Math.round(metrics.success_rate * 100)}%`}
        </strong>
        <small>{metrics.error_count} 次错误</small>
      </article>
      <article>
        <span>P95 延迟</span>
        <strong>
          {metrics.p95_latency_ms === null
            ? '—'
            : `${metrics.p95_latency_ms} ms`}
        </strong>
        <small>成本 ${metrics.cost_usd.toFixed(3)}</small>
      </article>
      <article>
        <span>归因覆盖</span>
        <strong>
          {metrics.attribution_coverage === null ? '—' : `${coverage}%`}
        </strong>
        <Progress percent={coverage} showInfo={false} strokeColor={color} />
      </article>
    </div>
  );
}

const JsonSchemaBox = ({ title, value }: { title: string; value: unknown }) => (
  <div className={styles.schemaBox}>
    <span>{title}</span>
    <code>{JSON.stringify(value ?? { type: 'object' }, null, 2)}</code>
  </div>
);
function SkillSpec({ spec }: { spec: Record<string, unknown> }) {
  const allowed = (spec.allowed_tools ?? []) as string[];
  return (
    <div className={styles.domainGrid}>
      <section className={styles.paper}>
        <header>
          <FileTextOutlined />
          <div>
            <span>SKILL.md</span>
            <strong>指令正文</strong>
          </div>
        </header>
        <pre>{String(spec.instructions || '暂无指令')}</pre>
      </section>
      <aside className={styles.factStack}>
        <section>
          <header>
            <SafetyCertificateOutlined />
            <strong>工具权限</strong>
          </header>
          <div className={styles.chips}>
            {allowed.length ? (
              allowed.map((tool) => <Tag key={tool}>{tool}</Tag>)
            ) : (
              <small>未授权额外工具</small>
            )}
          </div>
        </section>
        <section>
          <header>
            <ClockCircleOutlined />
            <strong>运行边界</strong>
          </header>
          <dl>
            <div>
              <dt>最大步数</dt>
              <dd>{String(spec.max_steps ?? '—')}</dd>
            </div>
            <div>
              <dt>超时</dt>
              <dd>{String(spec.timeout_ms ?? '—')} ms</dd>
            </div>
          </dl>
        </section>
      </aside>
      <JsonSchemaBox title="INPUT SCHEMA" value={spec.input_schema} />
      <JsonSchemaBox title="OUTPUT SCHEMA" value={spec.output_schema} />
    </div>
  );
}
function McpSpec({
  spec,
  busy,
  onCheck,
}: {
  spec: Record<string, unknown>;
  busy: boolean;
  onCheck: () => void;
}) {
  const auth = (spec.authentication ?? {}) as Record<string, unknown>;
  const tools = (spec.tools ?? []) as Array<Record<string, unknown>>;
  return (
    <div className={styles.domainGrid}>
      <section className={styles.connectionCard}>
        <header>
          <div className={styles.liveDot} />
          <div>
            <span>SERVER CONNECTION</span>
            <strong>{String(spec.endpoint ?? '未配置')}</strong>
          </div>
          <Button
            icon={<ThunderboltOutlined />}
            loading={busy}
            onClick={onCheck}
          >
            测试连接
          </Button>
        </header>
        <dl>
          <div>
            <dt>传输</dt>
            <dd>{String(spec.transport ?? '—')}</dd>
          </div>
          <div>
            <dt>鉴权</dt>
            <dd>{String(auth.type ?? '—')}</dd>
          </div>
          <div>
            <dt>密钥引用</dt>
            <dd>{String(auth.secret_ref ?? '无')}</dd>
          </div>
        </dl>
      </section>
      <section className={styles.registryPanel}>
        <header>
          <div>
            <span>DISCOVERED TOOLS</span>
            <strong>{tools.length} 个工具入口</strong>
          </div>
          <Tag color="cyan">Schema 已冻结</Tag>
        </header>
        {tools.map((tool, index) => (
          <article key={String(tool.name ?? index)}>
            <CodeOutlined />
            <div>
              <strong>{String(tool.name)}</strong>
              <small>{String(tool.description || '暂无说明')}</small>
            </div>
            <span>JSON Schema</span>
          </article>
        ))}
        {!tools.length && (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="未声明工具"
          />
        )}
      </section>
    </div>
  );
}
function KnowledgeSpec({
  spec,
  busy,
  onRebuild,
  onTest,
}: {
  spec: Record<string, unknown>;
  busy: boolean;
  onRebuild: () => void;
  onTest: (query: string) => void;
}) {
  const [query, setQuery] = useState('');
  const chunk = (spec.chunk_strategy ?? {}) as Record<string, unknown>;
  const retrieval = (spec.retrieval ?? {}) as Record<string, unknown>;
  const sources = (spec.sources ?? []) as Array<Record<string, unknown>>;
  return (
    <div className={styles.domainGrid}>
      <section className={styles.registryPanel}>
        <header>
          <div>
            <span>KNOWLEDGE SOURCES</span>
            <strong>{sources.length} 个数据源</strong>
          </div>
          <Button
            icon={<CloudSyncOutlined />}
            loading={busy}
            onClick={onRebuild}
          >
            同步并重建索引
          </Button>
        </header>
        {sources.map((source, index) => (
          <article key={String(source.id ?? index)}>
            <DatabaseOutlined />
            <div>
              <strong>{String(source.name || source.id)}</strong>
              <small>{String(source.uri)}</small>
            </div>
            <Tag color={source.enabled ? 'success' : 'default'}>
              {source.enabled ? '已启用' : '已停用'}
            </Tag>
          </article>
        ))}
      </section>
      <aside className={styles.factStack}>
        <section>
          <header>
            <BranchesOutlined />
            <strong>索引策略</strong>
          </header>
          <dl>
            <div>
              <dt>Embedding</dt>
              <dd>{String(spec.embedding_model ?? '—')}</dd>
            </div>
            <div>
              <dt>分块 / 重叠</dt>
              <dd>
                {String(chunk.size ?? '—')} / {String(chunk.overlap ?? '—')}
              </dd>
            </div>
            <div>
              <dt>检索</dt>
              <dd>
                {String(retrieval.mode ?? '—')} · Top{' '}
                {String(retrieval.top_k ?? '—')}
              </dd>
            </div>
          </dl>
        </section>
      </aside>
      <section className={styles.retrievalLab}>
        <header>
          <SearchOutlined />
          <div>
            <span>RETRIEVAL LAB</span>
            <strong>用真实查询检查召回</strong>
          </div>
        </header>
        <div>
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onPressEnter={() => query && onTest(query)}
            placeholder="输入用户可能提出的问题"
          />
          <Button
            type="primary"
            loading={busy}
            disabled={!query}
            onClick={() => onTest(query)}
          >
            测试检索
          </Button>
        </div>
      </section>
    </div>
  );
}

export default function AssetWorkspace({ kind }: Props) {
  const workspace = useWorkspace();
  const { message } = App.useApp();
  const meta = pageMeta[kind];
  const [assets, setAssets] = useState<CapabilityAsset[]>([]);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<'all' | 'live' | 'draft'>('all');
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [draft, setDraft] = useState<Draft>({ ...emptyDraft });
  const load = useCallback(async () => {
    if (!workspace) return;
    setLoading(true);
    try {
      setAssets((await listCapabilityAssets(workspace.id, kind)).items ?? []);
    } catch {
      setAssets([]);
    } finally {
      setLoading(false);
    }
  }, [workspace, kind]);
  useEffect(() => {
    void load();
  }, [load]);
  const filtered = useMemo(
    () =>
      assets.filter((asset) => {
        const matches = `${asset.name} ${asset.description} ${asset.owner}`
          .toLowerCase()
          .includes(query.toLowerCase());
        const isLive = Boolean(channelOf(asset.channels, 'live')?.version_id);
        return (
          matches &&
          (filter === 'all' || (filter === 'live' ? isLive : !isLive))
        );
      }),
    [assets, query, filter],
  );
  const create = async () => {
    if (!workspace || !draft.name.trim()) {
      message.warning('请填写名称');
      return;
    }
    setLoading(true);
    try {
      const created = await createCapabilityAsset(workspace.id, {
        kind,
        name: draft.name.trim(),
        description: draft.description,
        tenant_id: draft.tenantId || null,
        spec: specFromDraft(kind, draft),
      });
      message.success('资源已创建');
      setCreateOpen(false);
      history.push(`${meta.path}/${created.id}`);
    } catch {
      message.error('创建失败，请检查必填项');
    } finally {
      setLoading(false);
    }
  };
  return (
    <PageContainer
      title={meta.title}
      content={meta.description}
      extra={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            setDraft({ ...emptyDraft });
            setCreateOpen(true);
          }}
        >
          新建 {meta.noun}
        </Button>
      }
    >
      <section
        className={styles.directoryHeader}
        style={{ '--accent': meta.color } as React.CSSProperties}
      >
        <div>
          <span>CAPABILITY REGISTRY</span>
          <strong>{assets.length}</strong>
          <small>个受控资源</small>
        </div>
        <div className={styles.lifecycleMini}>
          {CHANNELS.map((channel, index) => (
            <div key={channel}>
              <b>{index + 1}</b>
              <span>{channelMeta[channel].label}</span>
              {index < 2 && <i />}
            </div>
          ))}
        </div>
        <div>
          <span>LIVE</span>
          <strong>
            {
              assets.filter(
                (asset) => channelOf(asset.channels, 'live')?.version_id,
              ).length
            }
          </strong>
          <small>已进入生产</small>
        </div>
      </section>
      <section className={styles.directoryPanel}>
        <header>
          <Input
            prefix={<SearchOutlined />}
            allowClear
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={`搜索 ${meta.noun}、描述或负责人`}
          />
          <Select
            value={filter}
            onChange={setFilter}
            options={[
              { value: 'all', label: '全部状态' },
              { value: 'live', label: '已上 LIVE' },
              { value: 'draft', label: '待发布' },
            ]}
          />
          <Button
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={() => void load()}
          />
        </header>
        <div className={styles.registryHead}>
          <span>资源</span>
          <span>生命周期</span>
          <span>影响面</span>
          <span>版本 / 更新</span>
          <span />
        </div>
        <div className={styles.registryRows}>
          {filtered.map((asset) => (
            <button
              type="button"
              key={asset.id}
              onClick={() => history.push(`${meta.path}/${asset.id}`)}
            >
              <span className={styles.resourceCell}>
                <i style={{ color: meta.color, background: `${meta.color}12` }}>
                  {meta.icon}
                </i>
                <span>
                  <strong>{asset.name}</strong>
                  <small>{asset.description || '暂无描述'}</small>
                  <code>{asset.owner}</code>
                </span>
              </span>
              <span className={styles.channelDots}>
                {CHANNELS.map((channel) => (
                  <i
                    key={channel}
                    className={
                      channelOf(asset.channels, channel)?.version_id
                        ? styles.channelReady
                        : ''
                    }
                  >
                    <b>{channelMeta[channel].label}</b>
                    <small>
                      {channelOf(asset.channels, channel)?.version_label ?? '—'}
                    </small>
                  </i>
                ))}
              </span>
              <span>
                <strong>{asset.binding_count}</strong>
                <small>Agent 引用</small>
              </span>
              <span>
                <strong>{asset.version_count}</strong>
                <small>{formatDate(asset.updated_at)}</small>
              </span>
              <ArrowRightOutlined />
            </button>
          ))}
          {!loading && !filtered.length && (
            <Empty
              description={query ? '没有匹配的资源' : `还没有 ${meta.noun}`}
            />
          )}
          {loading && !assets.length && (
            <Skeleton active paragraph={{ rows: 6 }} />
          )}
        </div>
      </section>
      <Modal
        open={createOpen}
        title={`新建 ${meta.noun}`}
        width={760}
        onCancel={() => setCreateOpen(false)}
        onOk={() => void create()}
        okText="创建并打开"
        confirmLoading={loading}
      >
        <ResourceEditor
          kind={kind}
          draft={draft}
          onChange={setDraft}
          isCreate
        />
      </Modal>
    </PageContainer>
  );
}

export function AssetDetail({ kind }: Props) {
  const { id = '' } = useParams<{ id: string }>();
  const workspace = useWorkspace();
  const { message } = App.useApp();
  const meta = pageMeta[kind];
  const [asset, setAsset] = useState<CapabilityAsset | null>(null);
  const [versions, setVersions] = useState<CapabilityVersion[]>([]);
  const [bindings, setBindings] = useState<CapabilityBinding[]>([]);
  const [deployments, setDeployments] = useState<CapabilityDeployment[]>([]);
  const [metrics, setMetrics] = useState<ResourceMetrics | null>(null);
  const [channel, setChannel] = useState<ChannelName>('test');
  const [loading, setLoading] = useState(true);
  const [actionBusy, setActionBusy] = useState(false);
  const [versionOpen, setVersionOpen] = useState(false);
  const [promotionTarget, setPromotionTarget] =
    useState<ChannelName | null>(null);
  const [promotionPreview, setPromotionPreview] =
    useState<PromotionPreview | null>(null);
  const [rollbackOpen, setRollbackOpen] = useState(false);
  const [rollbackVersionId, setRollbackVersionId] = useState('');
  const [rollbackReason, setRollbackReason] = useState('');
  const [draft, setDraft] = useState<Draft>({ ...emptyDraft });
  const [baseSpec, setBaseSpec] = useState<Record<string, unknown>>({});
  const [retrievalResult, setRetrievalResult] =
    useState<RetrievalTestResult | null>(null);
  const load = useCallback(async () => {
    if (!workspace || !id) return;
    setLoading(true);
    try {
      const [nextAsset, versionResult, bindingResult, deploymentResult] =
        await Promise.all([
        getCapabilityAsset(workspace.id, id),
        listCapabilityVersions(workspace.id, id),
        listProviderBindings(workspace.id, id),
          listCapabilityDeployments(workspace.id, id).catch(() => ({ items: [] })),
        ]);
      setAsset(nextAsset);
      setVersions(versionResult.items ?? []);
      setBindings(bindingResult.items ?? []);
      setDeployments(deploymentResult.items ?? []);
    } catch {
      message.error('资源加载失败');
    } finally {
      setLoading(false);
    }
  }, [workspace, id, message]);
  useEffect(() => {
    void load();
  }, [load]);
  const pointer = asset ? channelOf(asset.channels, channel) : undefined;
  const activeVersion =
    versions.find((item) => item.id === pointer?.version_id) ??
    (channel === 'test' ? versions[0] : undefined);
  useEffect(() => {
    if (!workspace || !asset || !activeVersion) {
      setMetrics(null);
      return;
    }
    void getResourceMetrics(workspace.id, asset.id, activeVersion.id, 24)
      .then(setMetrics)
      .catch(() => setMetrics(null));
  }, [workspace, asset, activeVersion]);
  const runAction = async (task: () => Promise<unknown>, success: string) => {
    setActionBusy(true);
    try {
      await task();
      message.success(success);
    } catch {
      message.warning('前端已就绪，对应管理面接口尚未接入');
    } finally {
      setActionBusy(false);
    }
  };
  const openVersion = () => {
    const spec = activeVersion?.spec ?? asset?.latest_version?.spec ?? {};
    setBaseSpec(spec);
    setDraft(draftFromSpec(spec));
    setVersionOpen(true);
  };
  const createVersion = async () => {
    if (!workspace || !asset) return;
    setLoading(true);
    try {
      await createCapabilityVersion(workspace.id, asset.id, {
        spec: specFromDraft(kind, draft, baseSpec),
      });
      message.success('新版本已冻结并进入 TEST');
      setVersionOpen(false);
      await load();
    } catch {
      message.error('创建失败，请检查配置');
    } finally {
      setLoading(false);
    }
  };
  const openPromotion = (target: ChannelName) => {
    if (!workspace || !asset || !activeVersion) return;
    setPromotionTarget(target);
    setPromotionPreview(null);
    void getPromotionPreview(workspace.id, asset.id, activeVersion.id, target)
      .then(setPromotionPreview)
      .catch(() => setPromotionPreview(null));
  };
  const submitPromotion = async () => {
    if (!workspace || !asset || !activeVersion || !promotionTarget) return;
    await runAction(async () => {
      await promoteCapabilityVersion(
        workspace.id,
        asset.id,
        activeVersion.id,
        {
          channel: promotionTarget,
          evidence_ids: promotionPreview?.gates
            .map((gate) => gate.evidence_id)
            .filter((id): id is string => Boolean(id)),
        },
      );
      setPromotionTarget(null);
      await load();
    }, `已晋级至 ${channelMeta[promotionTarget].label}`);
  };
  const openRollback = () => {
    const currentVersionId = channelOf(asset?.channels ?? [], channel)?.version_id;
    const firstCandidate = deployments.find(
      (item) => item.channel === channel && item.to_version_id !== currentVersionId,
    );
    setRollbackVersionId(firstCandidate?.to_version_id ?? '');
    setRollbackReason('');
    setRollbackOpen(true);
  };
  const submitRollback = async () => {
    if (!workspace || !asset || !rollbackVersionId || !rollbackReason.trim())
      return;
    await runAction(async () => {
      await rollbackCapabilityChannel(workspace.id, asset.id, {
        channel,
        target_version_id: rollbackVersionId,
        reason: rollbackReason.trim(),
      });
      setRollbackOpen(false);
      await load();
    }, `${channelMeta[channel].label} 已回退`);
  };
  if (loading && !asset)
    return (
      <PageContainer>
        <Skeleton active paragraph={{ rows: 10 }} />
      </PageContainer>
    );
  if (!asset)
    return (
      <PageContainer>
        <Empty description="资源不存在" />
      </PageContainer>
    );
  const specContent = activeVersion ? (
    kind === 'skill' ? (
      <SkillSpec spec={activeVersion.spec} />
    ) : kind === 'mcp' ? (
      <McpSpec
        spec={activeVersion.spec}
        busy={actionBusy}
        onCheck={() =>
          workspace &&
          void runAction(
            () => checkMcpConnection(workspace.id, asset.id, activeVersion.id),
            '连接正常',
          )
        }
      />
    ) : (
      <KnowledgeSpec
        spec={activeVersion.spec}
        busy={actionBusy}
        onRebuild={() =>
          workspace &&
          void runAction(
            () =>
              rebuildKnowledgeIndex(workspace.id, asset.id, activeVersion.id),
            '索引任务已进入队列',
          )
        }
        onTest={(query) =>
          workspace &&
          void runAction(async () => {
            const result = await testKnowledgeRetrieval(
              workspace.id,
              asset.id,
              activeVersion.id,
              { query },
            );
            setRetrievalResult(result);
          }, '检索完成')
        }
      />
    )
  ) : (
    <Empty description={`${channelMeta[channel].label} 尚未绑定版本`} />
  );
  const nextChannel =
    channel === 'test' ? 'livesh' : channel === 'livesh' ? 'live' : null;
  const currentPointer = channelOf(asset.channels, channel);
  const rollbackOptions = Array.from(
    new Map(
      deployments
        .filter(
          (item) =>
            item.channel === channel &&
            item.to_version_id !== currentPointer?.version_id,
        )
        .map((item) => [item.to_version_id, item]),
    ).values(),
  );
  const visibleDeployments = deployments.length
    ? deployments
    : asset.channels
        .filter((item) => item.version_id)
        .map((item) => ({
          id: `current-${item.channel}`,
          asset_id: asset.id,
          channel: item.channel,
          action: 'initial' as const,
          from_version_id: null,
          from_version_label: null,
          to_version_id: item.version_id as string,
          to_version_label: item.version_label ?? '未知版本',
          reason: null,
          evidence_ids: [],
          actor_id: item.bound_by ?? '系统',
          created_at: item.bound_at ?? asset.created_at,
        }));
  return (
    <PageContainer title={false}>
      <button
        className={styles.backLink}
        type="button"
        onClick={() => history.push(meta.path)}
      >
        <ArrowLeftOutlined /> 返回{meta.title}
      </button>
      <section
        className={styles.detailHero}
        style={{ '--accent': meta.color } as React.CSSProperties}
      >
        <div className={styles.heroIcon}>{meta.icon}</div>
        <div>
          <Space>
            <span className={styles.eyebrow}>{meta.noun.toUpperCase()}</span>
            {asset.tenant_scope === 'tenant_bound' && (
              <Tag color="orange">租户隔离</Tag>
            )}
          </Space>
          <h1>{asset.name}</h1>
          <p>{asset.description || '暂无描述'}</p>
          <small>
            {asset.owner} · 更新于 {formatDate(asset.updated_at)}
          </small>
        </div>
        <div className={styles.heroActions}>
          <Button onClick={() => void load()} icon={<ReloadOutlined />} />
          <Button type="primary" icon={<PlusOutlined />} onClick={openVersion}>
            创建新版本
          </Button>
        </div>
      </section>
      <LifecycleRail asset={asset} active={channel} onChange={setChannel} />
      <section className={styles.detailBody}>
        <div className={styles.versionContext}>
          <div>
            <span>当前查看</span>
            <strong>
              {channelMeta[channel].label} /{' '}
              {activeVersion?.version_label ?? '未部署'}
            </strong>
          </div>
          <div>
            <span>状态</span>
            <Tag color={activeVersion ? 'processing' : 'default'}>
              {activeVersion?.lifecycle ?? '空置'}
            </Tag>
          </div>
          <div>
            <span>创建时间</span>
            <strong>{formatDate(activeVersion?.created_at)}</strong>
          </div>
          {nextChannel && activeVersion && (
            <Button
              className={styles.promoteButton}
              type="primary"
              ghost
              onClick={() => openPromotion(nextChannel)}
            >
              晋级至 {channelMeta[nextChannel].label}
            </Button>
          )}
          {currentPointer?.version_id && (
            <Button icon={<RollbackOutlined />} onClick={openRollback}>
              回退
            </Button>
          )}
        </div>
        <Tabs
          items={[
            {
              key: 'config',
              label: '配置与调试',
              children: (
                <>
                  {specContent}
                  {retrievalResult && (
                    <section className={styles.resultPanel}>
                      <header>
                        <CheckCircleFilled /> 命中{' '}
                        {retrievalResult.matches.length} 个片段 ·{' '}
                        {retrievalResult.latency_ms} ms
                      </header>
                      {retrievalResult.matches.map((match) => (
                        <article key={match.id}>
                          <b>{Math.round(match.score * 100)}%</b>
                          <div>
                            <strong>{match.title ?? match.source_id}</strong>
                            <p>{match.content}</p>
                          </div>
                        </article>
                      ))}
                    </section>
                  )}
                </>
              ),
            },
            {
              key: 'versions',
              label: `版本 ${versions.length}`,
              children: (
                <div className={styles.versionList}>
                  {versions.map((version) => (
                    <article key={version.id}>
                      <span />
                      <div>
                        <strong>{version.version_label}</strong>
                        <small>
                          {formatDate(version.created_at)} ·{' '}
                          {version.created_by}
                        </small>
                      </div>
                      <Tag>{version.lifecycle}</Tag>
                      <code>{JSON.stringify(version.spec).length} B</code>
                    </article>
                  ))}
                </div>
              ),
            },
            {
              key: 'bindings',
              label: `引用 ${bindings.length}`,
              children: bindings.length ? (
                <div className={styles.bindingList}>
                  {bindings.map((binding) => (
                    <article key={binding.id}>
                      <LinkOutlined />
                      <div>
                        <strong>
                          {binding.consumer_asset_name ??
                            binding.consumer_asset_id}
                        </strong>
                        <small>
                          {binding.consumer_version_id
                            ? '指定 Agent 版本'
                            : 'Agent 全部版本'}
                        </small>
                      </div>
                      <Tag
                        color={
                          binding.resolve_mode === 'pinned' ? 'purple' : 'blue'
                        }
                      >
                        {binding.resolve_mode === 'pinned'
                          ? '锁定版本'
                          : `跟随 ${binding.provider_channel?.toUpperCase()}`}
                      </Tag>
                      <b>{binding.resolved_version_label ?? '未解析'}</b>
                    </article>
                  ))}
                </div>
              ) : (
                <Empty description="还没有 Agent 引用这个资源" />
              ),
            },
            {
              key: 'metrics',
              label: '运行质量',
              children: <MetricCards metrics={metrics} color={meta.color} />,
            },
            {
              key: 'feedback',
              label: '迭代回流',
              children: (
                <div className={styles.feedbackEmpty}>
                  <CloudSyncOutlined />
                  <strong>回流通道已预留</strong>
                  <p>
                    后续将把 LIVE 的失败
                    Trace、用户反馈和低置信样本沉淀为候选数据集，发起新一轮 TEST
                    评测。
                  </p>
                  <Button disabled>创建迭代提案</Button>
                </div>
              ),
            },
          ]}
        />
      </section>
      <Modal
        open={versionOpen}
        title={`为 ${asset.name} 创建新版本`}
        width={760}
        onCancel={() => setVersionOpen(false)}
        onOk={() => void createVersion()}
        okText="冻结版本并进入 TEST"
        confirmLoading={loading}
      >
        <div className={styles.versionNotice}>
          <SafetyCertificateOutlined />
          <span>版本创建后不可修改。先进入 TEST，通过评测门禁后再晋级。</span>
        </div>
        <ResourceEditor
          kind={kind}
          draft={draft}
          onChange={setDraft}
          isCreate={false}
        />
      </Modal>
    </PageContainer>
  );
}
