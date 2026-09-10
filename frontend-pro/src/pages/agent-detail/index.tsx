import {
  ApiOutlined,
  ArrowLeftOutlined,
  CheckCircleFilled,
  CodeOutlined,
  CopyOutlined,
  DatabaseOutlined,
  ReloadOutlined,
  SearchOutlined,
  ToolOutlined,
  WarningFilled,
} from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { history, useParams } from '@umijs/max';
import {
  App,
  Badge,
  Button,
  Drawer,
  Empty,
  Input,
  Progress,
  Segmented,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
} from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { useWorkspace } from '@/hooks/useWorkspace';
import type {
  AgentTrace as ServiceTrace,
  AgentTraceSpan,
  AgentTraceSummary,
  EvalAgentDetail,
} from '@/services/eval/agents';
import { getAgent, getAgentTraces, getTrace } from '@/services/eval/agents';
import styles from './style.module.css';

type Lifecycle = 'test' | 'livesh' | 'live';
type SpanType = AgentTraceSpan['type'];
type TraceSpan = AgentTraceSpan;
//: 列表里先只拿到摘要，选中后再拉完整 Span 树
type AgentTrace = AgentTraceSummary & { spans: TraceSpan[] };

const lifecycleMeta: Record<Lifecycle, { label: string; title: string }> = {
  test: { label: 'TEST', title: '离线验证' },
  livesh: { label: 'LIVESH', title: '影子流量' },
  live: { label: 'LIVE', title: '生产环境' },
};

const typeMeta: Record<
  SpanType,
  { label: string; color: string; background: string; icon: React.ReactNode }
> = {
  agent: {
    label: 'Agent',
    color: '#315efb',
    background: '#edf3ff',
    icon: <ApiOutlined />,
  },
  llm: {
    label: 'LLM',
    color: '#7254c7',
    background: '#f3efff',
    icon: <CodeOutlined />,
  },
  tool: {
    label: 'Tool',
    color: '#087f6e',
    background: '#edf8f5',
    icon: <ToolOutlined />,
  },
  retriever: {
    label: 'Retriever',
    color: '#a56514',
    background: '#fff6e8',
    icon: <DatabaseOutlined />,
  },
};

function safeJson(value?: string) {
  if (!value) return '—';
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

const demoExperiments = [
  {
    id: 'exp-482',
    name: '退款任务回归 · v1.7.3',
    lifecycle: 'test',
    dataset: 'Support Golden Set v12',
    comparison: 'v1.7.3 vs v1.7.2',
    score: 94.2,
    status: '通过',
    updatedAt: '8 分钟前',
  },
  {
    id: 'exp-119',
    name: '生产流量影子对比',
    lifecycle: 'livesh',
    dataset: 'Live traffic sample · 5%',
    comparison: 'candidate vs LIVE',
    score: 91.8,
    status: '运行中',
    updatedAt: '12 分钟前',
  },
  {
    id: 'exp-468',
    name: '工具调用轨迹基准',
    lifecycle: 'test',
    dataset: 'Tool Routing v7',
    comparison: 'v1.7.3 vs v1.6.9',
    score: 89.7,
    status: '通过',
    updatedAt: '昨天',
  },
];

const demoBenchmarks = [
  {
    id: 'bench-support',
    dataset: 'Support Golden Set',
    version: 'v12',
    purpose: '回答质量、忠实度与拒答策略',
    items: 1240,
    threshold: 88,
    latest: 94.2,
  },
  {
    id: 'bench-tools',
    dataset: 'Tool Routing',
    version: 'v7',
    purpose: '工具选择、参数正确性与重试轨迹',
    items: 486,
    threshold: 86,
    latest: 89.7,
  },
  {
    id: 'bench-safety',
    dataset: 'Support Safety',
    version: 'v4',
    purpose: '越权操作、隐私与提示注入',
    items: 320,
    threshold: 96,
    latest: 98.1,
  },
];

export default function AgentDetailPage() {
  const { id = '' } = useParams<{ id: string }>();
  const workspace = useWorkspace();
  const { message } = App.useApp();
  const [agent, setAgent] = useState<EvalAgentDetail>();
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [environment, setEnvironment] = useState<'all' | Lifecycle>('all');
  const [selectedTraceId, setSelectedTraceId] = useState('');
  const [selectedSpanId, setSelectedSpanId] = useState('');
  const [spanView, setSpanView] = useState<'tree' | 'timeline'>('tree');
  const [refreshKey, setRefreshKey] = useState(0);
  const [compact, setCompact] = useState(false);
  const [compactTraceOpen, setCompactTraceOpen] = useState(false);

  useEffect(() => {
    const media = window.matchMedia('(max-width: 880px)');
    const update = () => setCompact(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  useEffect(() => {
    if (!workspace || !id) return;
    setLoading(true);
    void getAgent(workspace.id, id)
      .then(setAgent)
      .catch(() => setAgent(undefined))
      .finally(() => setLoading(false));
  }, [workspace?.id, id, refreshKey]);

  // Trace 列表来自后端；Span 树在选中某条 Trace 时按需拉取
  const [traceSummaries, setTraceSummaries] = useState<AgentTraceSummary[]>([]);
  const [spansByTrace, setSpansByTrace] = useState<Record<string, TraceSpan[]>>({});

  useEffect(() => {
    if (!workspace || !id) return;
    void getAgentTraces(workspace.id, id)
      .then((result) => setTraceSummaries(result.items))
      .catch(() => setTraceSummaries([]));
  }, [workspace?.id, id, refreshKey]);

  const traces = useMemo<AgentTrace[]>(
    () =>
      traceSummaries.map((summary) => ({
        ...summary,
        spans: spansByTrace[summary.id] ?? [],
      })),
    [traceSummaries, spansByTrace],
  );
  const visible = useMemo(
    () =>
      traces.filter(
        (trace) =>
          (status === 'all' || trace.status === status) &&
          (environment === 'all' || trace.environment === environment) &&
          `${trace.name} ${trace.input} ${trace.id}`
            .toLowerCase()
            .includes(query.toLowerCase()),
      ),
    [traces, status, environment, query],
  );
  const selectedTrace =
    visible.find((trace) => trace.id === selectedTraceId) ?? visible[0];
  useEffect(() => {
    if (!workspace || !selectedTrace?.id || spansByTrace[selectedTrace.id]) return;
    const traceId = selectedTrace.id;
    void getTrace(workspace.id, traceId)
      .then((full) =>
        setSpansByTrace((current) => ({ ...current, [traceId]: full.spans })),
      )
      .catch(() => setSpansByTrace((current) => ({ ...current, [traceId]: [] })));
  }, [workspace?.id, selectedTrace?.id, spansByTrace]);

  const selectedSpan =
    selectedTrace?.spans.find((span) => span.id === selectedSpanId) ??
    selectedTrace?.spans[0];
  const successRate = traces.length
    ? Math.round(
        (traces.filter((trace) => trace.status === 'success').length /
          traces.length) *
          100,
      )
    : 0;
  const averageLlmCalls = traces.length
    ? traces.reduce(
        (total, trace) =>
          total + trace.spans.filter((span) => span.type === 'llm').length,
        0,
      ) / traces.length
    : 0;
  const averageToolCalls = traces.length
    ? traces.reduce(
        (total, trace) =>
          total + trace.spans.filter((span) => span.type === 'tool').length,
        0,
      ) / traces.length
    : 0;
  const averageCost = traces.length
    ? traces.reduce((total, trace) => total + trace.cost, 0) / traces.length
    : 0;
  const currentLifecycle: Lifecycle =
    agent?.lifecycle ??
    (agent?.environment &&
    ['sandbox', 'testing', 'development'].some((value) =>
      agent.environment.toLowerCase().includes(value),
    )
      ? 'test'
      : agent?.environment &&
          ['livesh', 'shadow', 'staging'].some((value) =>
            agent.environment.toLowerCase().includes(value),
          )
        ? 'livesh'
        : 'live');

  useEffect(() => {
    if (selectedTrace && selectedTrace.id !== selectedTraceId) {
      setSelectedTraceId(selectedTrace.id);
      setSelectedSpanId(selectedTrace.spans[0]?.id ?? '');
    }
  }, [selectedTrace?.id]);

  const copyValue = async (value: string) => {
    await navigator.clipboard.writeText(value);
    message.success('已复制');
  };

  const traceWorkspace = (
    <section className={styles.observatory}>
      <header className={styles.filters}>
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索 Trace ID、名称或输入"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <Select
          value={environment}
          onChange={setEnvironment}
          options={[
            { label: '全部环境', value: 'all' },
            ...(['test', 'livesh', 'live'] as Lifecycle[]).map((value) => ({
              label: `${lifecycleMeta[value].label} · ${lifecycleMeta[value].title}`,
              value,
            })),
          ]}
        />
        <Select
          value={status}
          onChange={setStatus}
          options={[
            { label: '全部状态', value: 'all' },
            { label: '成功', value: 'success' },
            { label: '异常', value: 'error' },
          ]}
        />
        <Select
          defaultValue="24h"
          options={[
            { label: '最近 1 小时', value: '1h' },
            { label: '最近 24 小时', value: '24h' },
            { label: '最近 7 天', value: '7d' },
          ]}
        />
      </header>

      <div className={styles.traceWorkspace}>
        <aside className={styles.traceList}>
          <header>
            <strong>Traces</strong>
            <span>{visible.length} results</span>
          </header>
          {visible.length ? (
            visible.map((trace) => (
              <button
                type="button"
                key={trace.id}
                className={
                  trace.id === selectedTrace?.id ? styles.traceActive : ''
                }
                onClick={() => {
                  setSelectedTraceId(trace.id);
                  setSelectedSpanId(trace.spans[0].id);
                  if (compact) setCompactTraceOpen(true);
                }}
              >
                <span
                  className={
                    trace.status === 'success'
                      ? styles.statusOk
                      : styles.statusError
                  }
                >
                  {trace.status === 'success' ? (
                    <CheckCircleFilled />
                  ) : (
                    <WarningFilled />
                  )}
                </span>
                <div>
                  <strong>{trace.name}</strong>
                  <p>{trace.input.replace(/[{}"\\]/g, '').slice(0, 54)}</p>
                  <footer>
                    <code>{trace.id.slice(0, 12)}</code>
                    <time>
                      {new Date(trace.startedAt).toLocaleTimeString('zh-CN', {
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                        hour12: false,
                      })}
                    </time>
                  </footer>
                </div>
                <b>{(trace.duration / 1000).toFixed(2)}s</b>
              </button>
            ))
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="没有符合条件的 Trace"
            />
          )}
          <footer className={styles.listFooter}>
            1–{visible.length} of {visible.length}
          </footer>
        </aside>

        <main className={styles.spanPanel}>
          {selectedTrace ? (
            <>
              <header className={styles.traceHeader}>
                <div>
                  <Space size={8}>
                    <Tag
                      color={
                        selectedTrace.status === 'success' ? 'success' : 'error'
                      }
                    >
                      {selectedTrace.status}
                    </Tag>
                    <Tag>{lifecycleMeta[selectedTrace.environment as Lifecycle]?.label ?? selectedTrace.environment}</Tag>
                  </Space>
                  <h2>{selectedTrace.name}</h2>
                  <code>{selectedTrace.id}</code>
                </div>
                <Segmented
                  size="small"
                  value={spanView}
                  onChange={setSpanView}
                  options={[
                    { label: 'Tree', value: 'tree' },
                    { label: 'Timeline', value: 'timeline' },
                  ]}
                />
              </header>
              <div className={styles.traceStats}>
                <span>
                  <small>Duration</small>
                  <b>{selectedTrace.duration} ms</b>
                </span>
                <span>
                  <small>LLM calls</small>
                  <b>
                    {
                      selectedTrace.spans.filter((span) => span.type === 'llm')
                        .length
                    }
                  </b>
                </span>
                <span>
                  <small>Tool calls</small>
                  <b>
                    {
                      selectedTrace.spans.filter((span) => span.type === 'tool')
                        .length
                    }
                  </b>
                </span>
                <span>
                  <small>Tokens</small>
                  <b>{selectedTrace.tokens}</b>
                </span>
                <span>
                  <small>Cost</small>
                  <b>${selectedTrace.cost.toFixed(4)}</b>
                </span>
              </div>
              <div className={styles.spanList}>
                <header>
                  <span>Span</span>
                  <span>Duration</span>
                </header>
                {selectedTrace.spans.map((span) => {
                  const meta = typeMeta[span.type];
                  const width = Math.max(
                    8,
                    Math.round((span.duration / selectedTrace.duration) * 100),
                  );
                  return (
                    <button
                      type="button"
                      key={span.id}
                      className={
                        span.id === selectedSpan?.id ? styles.spanActive : ''
                      }
                      onClick={() => setSelectedSpanId(span.id)}
                    >
                      <i
                        style={{
                          marginLeft: span.depth * 22,
                          color: meta.color,
                          background: meta.background,
                        }}
                      >
                        {meta.icon}
                      </i>
                      <div>
                        <strong>{span.name}</strong>
                        <small>
                          {meta.label}
                          {span.model ? ` · ${span.model}` : ''}
                        </small>
                      </div>
                      {spanView === 'timeline' && (
                        <span className={styles.durationBar}>
                          <i
                            style={{
                              width: `${width}%`,
                              background: meta.color,
                            }}
                          />
                        </span>
                      )}
                      <b>{span.duration} ms</b>
                    </button>
                  );
                })}
              </div>
            </>
          ) : (
            <Empty description="选择一个 Trace" />
          )}
        </main>

        <aside className={styles.inspector}>
          {selectedSpan ? (
            <>
              <header>
                <span
                  style={{
                    color: typeMeta[selectedSpan.type].color,
                    background: typeMeta[selectedSpan.type].background,
                  }}
                >
                  {typeMeta[selectedSpan.type].icon}
                </span>
                <div>
                  <small>
                    {typeMeta[selectedSpan.type].label.toUpperCase()} SPAN
                  </small>
                  <strong>{selectedSpan.name}</strong>
                </div>
                <Tag
                  color={
                    selectedSpan.status === 'success' ? 'success' : 'error'
                  }
                >
                  {selectedSpan.status}
                </Tag>
              </header>
              <Tabs
                size="small"
                items={[
                  {
                    key: 'io',
                    label: 'Input / Output',
                    children: (
                      <div className={styles.ioPanel}>
                        <section>
                          <header>
                            <span>INPUT</span>
                            <Button
                              type="text"
                              size="small"
                              icon={<CopyOutlined />}
                              onClick={() => void copyValue(selectedSpan.input)}
                            />
                          </header>
                          <pre>{safeJson(selectedSpan.input)}</pre>
                        </section>
                        <section>
                          <header>
                            <span>OUTPUT</span>
                            <Button
                              type="text"
                              size="small"
                              icon={<CopyOutlined />}
                              onClick={() =>
                                void copyValue(selectedSpan.output)
                              }
                            />
                          </header>
                          <pre>{safeJson(selectedSpan.output)}</pre>
                        </section>
                      </div>
                    ),
                  },
                  {
                    key: 'attributes',
                    label: 'Attributes',
                    children: (
                      <dl className={styles.attributes}>
                        <div>
                          <dt>span_id</dt>
                          <dd>{selectedSpan.id}</dd>
                        </div>
                        <div>
                          <dt>type</dt>
                          <dd>{selectedSpan.type}</dd>
                        </div>
                        <div>
                          <dt>duration</dt>
                          <dd>{selectedSpan.duration} ms</dd>
                        </div>
                        {Object.entries(selectedSpan.attributes).map(
                          ([key, value]) => (
                            <div key={key}>
                              <dt>{key}</dt>
                              <dd>{String(value)}</dd>
                            </div>
                          ),
                        )}
                      </dl>
                    ),
                  },
                  {
                    key: 'scores',
                    label: 'Scores',
                    children: (
                      <div className={styles.scores}>
                        {[
                          ['Answer relevancy', 94],
                          [
                            'Tool correctness',
                            selectedSpan.status === 'error' ? 42 : 91,
                          ],
                          ['Faithfulness', 88],
                        ].map(([name, score]) => (
                          <article key={String(name)}>
                            <span>{name}</span>
                            <b>{score}</b>
                            <Progress
                              percent={Number(score)}
                              showInfo={false}
                              status={
                                Number(score) < 80 ? 'exception' : 'normal'
                              }
                            />
                          </article>
                        ))}
                      </div>
                    ),
                  },
                ]}
              />
            </>
          ) : (
            <Empty description="选择一个 Span" />
          )}
        </aside>
      </div>
    </section>
  );

  return (
    <PageContainer title={false}>
      <header className={styles.pageHeader}>
        <div className={styles.headerTrail}>
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => history.push('/agents')}
          >
            Agent 管理
          </Button>
          <span>运行档案</span>
        </div>
        <div className={styles.heroMain}>
          <span className={styles.agentMark}>
            {agent?.name?.slice(0, 1).toUpperCase() || 'A'}
          </span>
          <div className={styles.identity}>
            <div className={styles.identityTitle}>
              <h1>{agent?.name || 'Customer Support Agent'}</h1>
              <span className={styles.liveState}>
                <i /> Active
              </span>
              <Tag>{lifecycleMeta[currentLifecycle].label}</Tag>
            </div>
            <p>{agent?.description || '订单、退款与售后服务 Agent'}</p>
            <div className={styles.identityMeta}>
              <span>
                版本 <code>{agent?.version || 'v1.7.3'}</code>
              </span>
              <span>
                负责人 <b>{agent?.owner || 'Agent Platform'}</b>
              </span>
              <span>最近更新 6 分钟前</span>
            </div>
          </div>
          <div className={styles.headerActions}>
            <Button>编辑配置</Button>
            <Tooltip title="刷新数据">
              <Button
                icon={<ReloadOutlined />}
                loading={loading}
                onClick={() => setRefreshKey((value) => value + 1)}
              />
            </Tooltip>
          </div>
        </div>
      </header>

      <section className={styles.contextBar}>
        <article>
          <small>成功率</small>
          <b className={styles.good}>{successRate}%</b>
          <span>最近 24 小时</span>
        </article>
        <article>
          <small>P95 延迟</small>
          <b>
            1.84 <em>s</em>
          </b>
          <span>目标低于 2.5s</span>
        </article>
        <article>
          <small>Trace</small>
          <b>18,429</b>
          <span>24h · 较昨日 +8.4%</span>
        </article>
        <article>
          <small>平均成本</small>
          <b>${averageCost.toFixed(4)}</b>
          <span>$184.62 / 24h</span>
        </article>
        <aside>
          <span>
            <small>LLM 调用</small>
            <b>{averageLlmCalls.toFixed(1)}</b>
          </span>
          <span>
            <small>Tool 调用</small>
            <b>{averageToolCalls.toFixed(1)}</b>
          </span>
          <p>每条 Trace 平均</p>
        </aside>
      </section>

      <Tabs
        className={styles.productTabs}
        defaultActiveKey="traces"
        items={[
          {
            key: 'traces',
            label: `Traces ${traces.length}`,
            children: traceWorkspace,
          },
          {
            key: 'threads',
            label: 'Threads',
            children: <Empty description="Threads 接口已预留" />,
          },
          {
            key: 'metrics',
            label: 'Metrics',
            children: (
              <Table
                size="small"
                pagination={false}
                rowKey="name"
                dataSource={[
                  {
                    name: 'Answer relevancy',
                    score: 94,
                    threshold: 85,
                    failure: '3.2%',
                  },
                  {
                    name: 'Tool correctness',
                    score: 91,
                    threshold: 88,
                    failure: '4.6%',
                  },
                  {
                    name: 'Faithfulness',
                    score: 88,
                    threshold: 85,
                    failure: '5.1%',
                  },
                ]}
                columns={[
                  { title: 'Metric', dataIndex: 'name' },
                  { title: 'Score', dataIndex: 'score' },
                  { title: 'Threshold', dataIndex: 'threshold' },
                  { title: 'Failure rate', dataIndex: 'failure' },
                ]}
              />
            ),
          },
          {
            key: 'experiments',
            label: '实验',
            children: (
              <div className={styles.experimentHub}>
                <header>
                  <div>
                    <strong>评测证据</strong>
                    <span>
                      实验结果与生命周期发布门禁绑定，便于比较候选版本与当前基线。
                    </span>
                  </div>
                  <Space>
                    <Button
                      onClick={() =>
                        history.push(`/evaluation/datasets?agent_id=${id}`)
                      }
                    >
                      管理 Benchmark
                    </Button>
                    <Button
                      type="primary"
                      onClick={() =>
                        history.push(`/evaluation/runs?agent_id=${id}`)
                      }
                    >
                      运行实验
                    </Button>
                  </Space>
                </header>
                <section>
                  <div className={styles.sectionTitle}>
                    <strong>最近实验</strong>
                    <Button
                      type="link"
                      onClick={() =>
                        history.push(`/evaluation/runs?agent_id=${id}`)
                      }
                    >
                      查看全部
                    </Button>
                  </div>
                  <Table
                    size="small"
                    rowKey="id"
                    pagination={false}
                    dataSource={demoExperiments}
                    columns={[
                      {
                        title: '实验',
                        dataIndex: 'name',
                        render: (value, item) => (
                          <button
                            type="button"
                            className={styles.inlineLink}
                            onClick={() =>
                              history.push(`/evaluation/runs/${item.id}`)
                            }
                          >
                            {value}
                          </button>
                        ),
                      },
                      {
                        title: '阶段',
                        dataIndex: 'lifecycle',
                        render: (value: Lifecycle) => (
                          <Tag>{value.toUpperCase()}</Tag>
                        ),
                      },
                      { title: '数据 / 流量', dataIndex: 'dataset' },
                      { title: '版本对比', dataIndex: 'comparison' },
                      { title: '得分', dataIndex: 'score' },
                      {
                        title: '状态',
                        dataIndex: 'status',
                        render: (value) => (
                          <Badge
                            status={value === '通过' ? 'success' : 'processing'}
                            text={value}
                          />
                        ),
                      },
                      { title: '更新时间', dataIndex: 'updatedAt' },
                    ]}
                  />
                </section>
                <section>
                  <div className={styles.sectionTitle}>
                    <strong>已绑定 Benchmark</strong>
                    <span>TEST 回归与晋级门禁默认使用这些版本化数据集</span>
                  </div>
                  <Table
                    size="small"
                    rowKey="id"
                    pagination={false}
                    dataSource={demoBenchmarks}
                    columns={[
                      { title: 'Benchmark', dataIndex: 'dataset' },
                      { title: '版本', dataIndex: 'version' },
                      { title: '用途', dataIndex: 'purpose' },
                      { title: '样本', dataIndex: 'items' },
                      { title: '门槛', dataIndex: 'threshold' },
                      {
                        title: '最近得分',
                        dataIndex: 'latest',
                        render: (value, item) => (
                          <span
                            className={
                              value >= item.threshold
                                ? styles.good
                                : styles.metricBad
                            }
                          >
                            {value}
                          </span>
                        ),
                      },
                    ]}
                  />
                </section>
              </div>
            ),
          },
          {
            key: 'versions',
            label: 'Versions',
            children: <Empty description="版本记录将从 Agent 版本接口加载" />,
          },
          {
            key: 'settings',
            label: 'Settings',
            children: <Empty description="Agent 配置接口已预留" />,
          },
        ]}
      />

      <Drawer
        open={compact && compactTraceOpen}
        onClose={() => setCompactTraceOpen(false)}
        size="large"
        title={
          selectedTrace
            ? `${selectedTrace.name} · ${selectedTrace.id.slice(0, 12)}`
            : 'Trace'
        }
        className={styles.compactDrawer}
      >
        {selectedTrace && selectedSpan ? (
          <div className={styles.compactTraceDetail}>
            <div className={styles.compactStats}>
              <span>
                <small>Duration</small>
                <b>{selectedTrace.duration} ms</b>
              </span>
              <span>
                <small>LLM calls</small>
                <b>
                  {
                    selectedTrace.spans.filter((span) => span.type === 'llm')
                      .length
                  }
                </b>
              </span>
              <span>
                <small>Tokens</small>
                <b>{selectedTrace.tokens}</b>
              </span>
              <span>
                <small>Cost</small>
                <b>${selectedTrace.cost.toFixed(4)}</b>
              </span>
            </div>
            <div className={styles.compactBody}>
              <nav>
                {selectedTrace.spans.map((span) => {
                  const meta = typeMeta[span.type];
                  return (
                    <button
                      type="button"
                      key={span.id}
                      className={
                        span.id === selectedSpan.id
                          ? styles.compactSpanActive
                          : ''
                      }
                      onClick={() => setSelectedSpanId(span.id)}
                    >
                      <i
                        style={{
                          color: meta.color,
                          background: meta.background,
                        }}
                      >
                        {meta.icon}
                      </i>
                      <span>
                        <strong>{span.name}</strong>
                        <small>
                          {meta.label}
                          {span.model ? ` · ${span.model}` : ''}
                        </small>
                      </span>
                      <b>{span.duration} ms</b>
                    </button>
                  );
                })}
              </nav>
              <section className={styles.compactInspector}>
                <header>
                  <span>{typeMeta[selectedSpan.type].label} span</span>
                  <Tag
                    color={
                      selectedSpan.status === 'success' ? 'success' : 'error'
                    }
                  >
                    {selectedSpan.status}
                  </Tag>
                </header>
                <div className={styles.ioPanel}>
                  <section>
                    <header>
                      <span>INPUT</span>
                      <Button
                        type="text"
                        size="small"
                        icon={<CopyOutlined />}
                        onClick={() => void copyValue(selectedSpan.input)}
                      />
                    </header>
                    <pre>{safeJson(selectedSpan.input)}</pre>
                  </section>
                  <section>
                    <header>
                      <span>OUTPUT</span>
                      <Button
                        type="text"
                        size="small"
                        icon={<CopyOutlined />}
                        onClick={() => void copyValue(selectedSpan.output)}
                      />
                    </header>
                    <pre>{safeJson(selectedSpan.output)}</pre>
                  </section>
                </div>
              </section>
            </div>
          </div>
        ) : (
          <Empty description="没有 Trace 数据" />
        )}
      </Drawer>
    </PageContainer>
  );
}
