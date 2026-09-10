import {
  CloudUploadOutlined,
  CodeOutlined,
  GithubOutlined,
  KeyOutlined,
  MoreOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  SwapOutlined,
} from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { history } from '@umijs/max';
import {
  App,
  Badge,
  Button,
  Dropdown,
  Form,
  Input,
  Modal,
  Segmented,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Upload,
} from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useWorkspace } from '@/hooks/useWorkspace';
import type { EvalAgent } from '@/services/eval/agents';
import {
  getAgents,
  getShadowComparison,
  promoteAgentVersion,
  registerAgent,
} from '@/services/eval/agents';
import type { AgentCredential } from '@/services/eval/credentials';
import { getAgentCredentials } from '@/services/eval/credentials';
import type { LifecyclePolicy } from '@/services/eval/lifecycle';
import {
  describeCheck,
  getLifecyclePolicy,
  transitionTo,
} from '@/services/eval/lifecycle';
import type { Member } from '@/services/eval/members';
import { getWorkspaceMembers } from '@/services/eval/members';
import {
  bindSecret,
  listAgentVersions,
  putSecret,
} from '@/services/eval/secrets';
import styles from './style.module.css';

type Lifecycle = 'test' | 'livesh' | 'live';

const fmtRate = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`;
type SourceKind = 'package' | 'github' | 'sdk';
type AgentRow = EvalAgent & {
  source_kind: SourceKind;
  source_ref: string;
  credential_state: 'ready' | 'missing' | 'expiring';
  updated_at: string;
  // 后端可能返回 null（该通道没有绑定版本）
  test_version?: string | null;
  livesh_version?: string | null;
  live_version?: string | null;
  test_version_id?: string | null;
  livesh_version_id?: string | null;
  live_version_id?: string | null;
};

const lifecycleOptions: Array<{ label: string; value: Lifecycle }> = [
  { label: 'TEST · 离线验证', value: 'test' },
  { label: 'LIVESH · 影子验证', value: 'livesh' },
  { label: 'LIVE · 生产运行', value: 'live' },
];

const sourceMeta: Record<SourceKind, { label: string; icon: React.ReactNode }> =
  {
    package: { label: '代码包', icon: <CloudUploadOutlined /> },
    github: { label: 'GitHub', icon: <GithubOutlined /> },
    sdk: { label: 'SDK', icon: <CodeOutlined /> },
  };

const resolveLifecycle = (agent: EvalAgent): Lifecycle => {
  if (agent.lifecycle) return agent.lifecycle;
  if (agent.status === 'draft' || /sandbox|test|dev/i.test(agent.environment))
    return 'test';
  if (/shadow|staging|livesh/i.test(agent.environment)) return 'livesh';
  return 'live';
};

const normalizeAgent = (agent: EvalAgent): AgentRow => {
  const lifecycle = resolveLifecycle(agent);
  const source = (
    ['package', 'github', 'sdk'].includes(agent.connect_type)
      ? agent.connect_type
      : 'sdk'
  ) as SourceKind;
  // 后端已经给出真实值；取不到就显示「—」，不再用演示数字冒充
  return {
    ...agent,
    lifecycle,
    source_kind: source,
    source_ref: agent.source_ref ?? '—',
    credential_state: agent.credential_state ?? 'missing',
    updated_at: agent.updated_at ?? agent.created_at ?? '',
  };
};

export default function AgentsPage() {
  const workspace = useWorkspace();
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [agents, setAgents] = useState<AgentRow[]>([]);
  const [credentials, setCredentials] = useState<AgentCredential[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  // 治理策略：晋级要做哪些检查由后端声明，前端不写死
  const [policy, setPolicy] = useState<LifecyclePolicy>();
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState('');
  const [lifecycle, setLifecycle] = useState<'all' | Lifecycle>('all');
  const [source, setSource] = useState<'all' | SourceKind>('all');
  const [status, setStatus] = useState('all');
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [connectOpen, setConnectOpen] = useState(false);
  const [connectKind, setConnectKind] = useState<SourceKind>('github');
  const [releaseAgent, setReleaseAgent] = useState<AgentRow>();
  const [targetLifecycle, setTargetLifecycle] = useState<Lifecycle>('test');

  const refresh = useCallback(async () => {
    if (!workspace) return;
    setLoading(true);
    try {
      const result = await getAgents(workspace.id);
      setAgents(result.items.map(normalizeAgent));
      const keys = await getAgentCredentials(workspace.id);
      setCredentials(keys.items);
      const roster = await getWorkspaceMembers(workspace.id);
      setMembers(roster.items);
      setPolicy(await getLifecyclePolicy());
    } catch {
      setAgents([]);
    } finally {
      setLoading(false);
    }
  }, [workspace]);

  useEffect(() => {
    void refresh();
  }, [workspace?.id]);

  const visible = useMemo(
    () =>
      agents.filter(
        (agent) =>
          (lifecycle === 'all' || agent.lifecycle === lifecycle) &&
          (source === 'all' || agent.source_kind === source) &&
          (status === 'all' || agent.status === status) &&
          `${agent.name} ${agent.owner} ${agent.source_ref}`
            .toLowerCase()
            .includes(query.toLowerCase()),
      ),
    [agents, lifecycle, source, status, query],
  );

  const finishConnect = async () => {
    if (!workspace) return;
    const values = await form.validateFields();
    // 三种接入方式的差异全部收敛到 source，后端按 connect_type 校验各自必填字段
    const source: Record<string, unknown> = {};
    if (connectKind === 'github') {
      Object.assign(source, {
        repository: values.repository,
        ref: values.ref,
        build_path: values.build_path,
        entrypoint: values.entrypoint,
      });
    } else if (connectKind === 'package') {
      const file = values.artifact?.[0]?.originFileObj ?? values.artifact?.[0];
      Object.assign(source, {
        artifact_id: file?.name ?? values.name,
        runtime: values.runtime,
        entrypoint: values.entrypoint,
      });
    } else {
      Object.assign(source, {
        sdk: values.sdk,
        credential_id: values.credential,
      });
    }
    // 平台托管的 Agent 必须声明记忆作用域——`sdk` 接入自己管，不用声明。
    if (connectKind !== 'sdk') {
      Object.assign(source, {
        memory: { scope: values.memory_scope ?? 'thread' },
      });
    }
    // 模型覆盖：表单里填的是**明文**，要「存密钥 → 声明引用 → 绑到版本」三步走，
    // 只把它塞进 source 是没用的——spec 里只能有引用，不能有值。
    const modelValues = (
      [
        ['model_base_url', values.model_base_url],
        ['model_auth_token', values.model_auth_token],
        ['model_name', values.model_name],
      ] as Array<[string, string | undefined]>
    ).filter(([, value]) => typeof value === 'string' && value.trim());
    if (modelValues.length) {
      Object.assign(source, {
        secrets: modelValues.map(([name]) => ({ name, required: false })),
      });
    }
    try {
      const created = await registerAgent(workspace.id, {
        name: values.name,
        description: values.description ?? '',
        owner_id: values.owner_id,
        connect_type: connectKind,
        source,
      });

      // 填了明文模型配置才需要「存 + 绑」这两步。失败不回滚 Agent——
      // Agent 已经建成，密钥可以事后在「密钥管理」里补，不用让人重来一遍。
      if (modelValues.length) {
        try {
          // 用返回的 **agent id**，不是名字——接口按 id 查。
          const versions = await listAgentVersions(workspace.id, created.id);
          const firstVersion = versions.items?.[0];
          if (firstVersion) {
            for (const [name, value] of modelValues) {
              const secret = await putSecret(workspace.id, {
                name,
                value: value as string,
                description: `Agent「${values.name}」的模型配置`,
              });
              for (const channel of ['test', 'live']) {
                await bindSecret(
                  workspace.id,
                  created.id,
                  firstVersion.id,
                  channel,
                  {
                    resource_secret_id: secret.id,
                    secret_name: name,
                  },
                );
              }
            }
          }
        } catch {
          message.warning(
            'Agent 已接入，但模型配置没绑上，请到「密钥管理」里补',
          );
        }
      }

      setConnectOpen(false);
      form.resetFields();
      message.success('Agent 接入成功');
      await refresh();
    } catch {
      // 失败提示由 requestErrorConfig 统一弹出，这里不吞不猜
    }
  };

  const openRelease = (item: AgentRow) => {
    setReleaseAgent(item);
    setTargetLifecycle(item.lifecycle ?? 'test');
  };

  const showShadowComparison = async (agentId: string, versionId: string) => {
    if (!workspace) return;
    try {
      const comparison = await getShadowComparison(
        workspace.id,
        agentId,
        versionId,
      );
      const candidate = comparison.candidate;
      const baseline = comparison.baseline;
      if (!candidate) return;
      const lines = [
        `候选（影子）：样本 ${candidate.trace_count}，成功率 ${fmtRate(candidate.success_rate)}，P95 ${candidate.p95_latency_ms ?? '—'}ms`,
        baseline
          ? `基线（生产）：样本 ${baseline.trace_count}，成功率 ${fmtRate(baseline.success_rate)}，P95 ${baseline.p95_latency_ms ?? '—'}ms`
          : '基线：LIVE 尚无版本，不做比对',
        `门槛：影子样本至少 ${comparison.min_samples} 条（近 ${comparison.window_days} 天）`,
      ];
      Modal.info({
        title: '影子验证详情',
        width: 560,
        content: (
          <div style={{ lineHeight: 2 }}>
            {lines.map((line) => (
              <div key={line}>{line}</div>
            ))}
          </div>
        ),
      });
    } catch {
      // 拿不到比对结果不影响主流程
    }
  };

  const confirmLifecycle = async () => {
    if (!releaseAgent || !workspace) return;
    const target = releaseAgent;
    // 晋级只能逐级走：TEST → LIVESH → LIVE。目标通道决定从哪个通道取版本。
    const versionId =
      targetLifecycle === 'livesh'
        ? target.test_version_id
        : target.livesh_version_id;
    if (targetLifecycle === 'test' || !versionId) {
      setReleaseAgent(undefined);
      message.info(
        targetLifecycle === 'test'
          ? 'TEST 是候选通道，无需晋级操作'
          : `没有可晋级的版本（${targetLifecycle === 'livesh' ? 'TEST' : 'LIVESH'} 通道为空）`,
      );
      return;
    }
    try {
      await promoteAgentVersion(workspace.id, {
        asset_id: target.id,
        version_id: versionId,
        to_channel: targetLifecycle,
        confirm: true,
      });
      setReleaseAgent(undefined);
      message.success(
        `${target.name} → ${targetLifecycle.toUpperCase()} 晋级成功`,
      );
      await refresh();
    } catch (error) {
      const info = (
        error as { info?: { errorCode?: string; errorMessage?: string } }
      ).info;
      if (info?.errorCode === 'gate_blocked') {
        message.error(`门禁未通过，晋级被阻断：${info.errorMessage ?? ''}`);
        // LIVESH → LIVE 的阻断多半是影子样本不足或劣于基线，把原始指标摊出来才好排查
        if (targetLifecycle === 'live') {
          void showShadowComparison(target.id, versionId);
        }
      }
      // 其余错误由 requestErrorConfig 统一提示
    }
  };

  const agentTable = (
    <section className={styles.inventory}>
      <header className={styles.toolbar}>
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索名称、负责人、仓库或密钥"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <Select
          value={lifecycle}
          onChange={setLifecycle}
          options={[
            { label: '全部生命周期', value: 'all' },
            { label: 'TEST', value: 'test' },
            { label: 'LIVESH', value: 'livesh' },
            { label: 'LIVE', value: 'live' },
          ]}
        />
        <Select
          value={source}
          onChange={setSource}
          options={[
            { label: '全部接入方式', value: 'all' },
            { label: '代码包上传', value: 'package' },
            { label: 'GitHub 仓库', value: 'github' },
            { label: 'SDK 接入', value: 'sdk' },
          ]}
        />
        <Select
          value={status}
          onChange={setStatus}
          options={[
            { label: '全部状态', value: 'all' },
            { label: '运行正常', value: 'active' },
            { label: '异常', value: 'failed' },
            { label: '草稿', value: 'draft' },
          ]}
        />
        <Button
          icon={<ReloadOutlined />}
          loading={loading}
          onClick={() => void refresh()}
        >
          刷新
        </Button>
      </header>
      {selectedKeys.length > 0 && (
        <div className={styles.batchBar}>
          <strong>已选择 {selectedKeys.length} 个 Agent</strong>
          <Button size="small">批量绑定策略</Button>
          <Button size="small">变更负责人</Button>
          <Button size="small">导出</Button>
          <Button type="text" size="small" onClick={() => setSelectedKeys([])}>
            取消选择
          </Button>
        </div>
      )}
      <Table<AgentRow>
        size="small"
        rowKey="id"
        loading={loading}
        dataSource={visible}
        scroll={{ x: 1680 }}
        pagination={{
          pageSize: 10,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 个 Agent`,
        }}
        rowSelection={{
          selectedRowKeys: selectedKeys,
          onChange: setSelectedKeys,
          preserveSelectedRowKeys: true,
        }}
        columns={[
          {
            title: 'Agent',
            dataIndex: 'name',
            fixed: 'left',
            width: 230,
            sorter: (a, b) => a.name.localeCompare(b.name),
            render: (_, item) => (
              <button
                type="button"
                className={styles.nameCell}
                onClick={() => history.push(`/agents/${item.id}`)}
              >
                <span>{item.name.slice(0, 1)}</span>
                <div>
                  <strong>{item.name}</strong>
                  <small>{item.description}</small>
                </div>
              </button>
            ),
          },
          {
            title: '接入来源',
            dataIndex: 'source_kind',
            width: 240,
            render: (_, item) => (
              <div className={styles.sourceCell}>
                <span>{sourceMeta[item.source_kind].icon}</span>
                <div>
                  <strong>{sourceMeta[item.source_kind].label}</strong>
                  <small>{item.source_ref}</small>
                </div>
              </div>
            ),
          },
          {
            title: '生命周期',
            dataIndex: 'lifecycle',
            width: 110,
            render: (value: Lifecycle) => (
              <Tag
                color={
                  value === 'live'
                    ? 'success'
                    : value === 'livesh'
                      ? 'processing'
                      : 'default'
                }
              >
                {value.toUpperCase()}
              </Tag>
            ),
          },
          {
            title: '三通道版本',
            width: 260,
            render: (_, item) => (
              <div className={styles.channels}>
                <span>
                  <i>T</i>
                  {item.test_version ?? '—'}
                </span>
                <span>
                  <i>S</i>
                  {item.livesh_version ?? '—'}
                </span>
                <span>
                  <i>L</i>
                  {item.live_version ?? '—'}
                </span>
              </div>
            ),
          },
          {
            title: '运行状态',
            dataIndex: 'status',
            width: 110,
            render: (value) => (
              <Badge
                status={
                  value === 'active'
                    ? 'success'
                    : value === 'failed'
                      ? 'error'
                      : 'default'
                }
                text={
                  value === 'active'
                    ? '正常'
                    : value === 'failed'
                      ? '异常'
                      : '草稿'
                }
              />
            ),
          },
          {
            title: '24h Traces',
            dataIndex: 'run_count',
            width: 110,
            sorter: (a, b) => (a.run_count ?? 0) - (b.run_count ?? 0),
            render: (value) => Number(value ?? 0).toLocaleString(),
          },
          {
            title: '成功率',
            dataIndex: 'success_rate',
            width: 100,
            sorter: (a, b) => (a.success_rate ?? 0) - (b.success_rate ?? 0),
            render: (value) => (
              <span
                className={Number(value) < 0.98 ? styles.warn : styles.healthy}
              >
                {(Number(value ?? 0) * 100).toFixed(1)}%
              </span>
            ),
          },
          {
            title: 'P95 延迟',
            dataIndex: 'latency_ms',
            width: 100,
            sorter: (a, b) => (a.latency_ms ?? 0) - (b.latency_ms ?? 0),
            render: (value) => `${Number(value ?? 0).toLocaleString()} ms`,
          },
          {
            title: '质量 / 成本',
            width: 130,
            render: (_, item) => (
              <div className={styles.metricPair}>
                <strong>{Number(item.quality_score ?? 0).toFixed(1)}</strong>
                <small>
                  ${Number(item.average_cost ?? 0).toFixed(4)} / trace
                </small>
              </div>
            ),
          },
          {
            title: '平均调用',
            width: 130,
            render: (_, item) => (
              <div className={styles.metricPair}>
                <strong>
                  LLM {Number(item.average_llm_calls ?? 0).toFixed(1)}
                </strong>
                <small>
                  Tool {Number(item.average_tool_calls ?? 0).toFixed(1)}
                </small>
              </div>
            ),
          },
          { title: '负责人', dataIndex: 'owner', width: 130, ellipsis: true },
          {
            title: '凭证',
            dataIndex: 'credential_state',
            width: 100,
            render: (value) => (
              <Tag
                color={
                  value === 'ready'
                    ? 'success'
                    : value === 'expiring'
                      ? 'warning'
                      : 'error'
                }
              >
                {value === 'ready'
                  ? '可用'
                  : value === 'expiring'
                    ? '即将过期'
                    : '未配置'}
              </Tag>
            ),
          },
          {
            title: '发布控制',
            fixed: 'right',
            width: 122,
            render: (_, item) => (
              <Space size={2}>
                <Button
                  type="link"
                  size="small"
                  icon={<SwapOutlined />}
                  onClick={() => openRelease(item)}
                >
                  变更
                </Button>
                <Dropdown
                  menu={{
                    items: [
                      {
                        key: 'detail',
                        label: '查看详情',
                        onClick: () => history.push(`/agents/${item.id}`),
                      },
                      {
                        key: 'evaluate',
                        label: '运行评测',
                        onClick: () =>
                          history.push(`/evaluation/runs?agent_id=${item.id}`),
                      },
                      { key: 'credential', label: '管理凭证' },
                    ],
                  }}
                >
                  <Button type="text" size="small" icon={<MoreOutlined />} />
                </Dropdown>
              </Space>
            ),
          },
        ]}
      />
    </section>
  );

  const keyTable = (
    <section className={styles.inventory}>
      <header className={styles.keyHeader}>
        <div>
          <strong>SDK 接入密钥</strong>
          <span>
            密钥按工作区隔离，可绑定多个 Agent；原文仅在创建时显示一次。
          </span>
        </div>
        <Button
          type="primary"
          icon={<KeyOutlined />}
          onClick={() => message.info('创建密钥接口已预留')}
        >
          创建密钥
        </Button>
      </header>
      <Table
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={credentials}
        columns={[
          {
            title: '名称',
            dataIndex: 'name',
            render: (value, item) => (
              <div className={styles.keyName}>
                <KeyOutlined />
                <div>
                  <strong>{value}</strong>
                  <code>{item.prefix}</code>
                </div>
              </div>
            ),
          },
          {
            title: '权限范围',
            render: (_, item) => item.scopes.join(', ') || '—',
          },
          {
            title: '绑定 Agent',
            render: (_, item) => `${item.agent_ids.length} 个`,
          },
          {
            title: '状态',
            render: (_, item) => (
              <Badge
                status={item.status === 'active' ? 'success' : 'warning'}
                text={item.status === 'active' ? '可用' : '即将过期'}
              />
            ),
          },
          {
            title: '最后使用',
            render: (_, item) =>
              item.last_used_at?.slice(0, 16).replace('T', ' ') ?? '—',
          },
          {
            title: '创建时间',
            render: (_, item) => item.created_at.slice(0, 10),
          },
          {
            title: '操作',
            render: () => (
              <Space>
                <Button type="link" size="small">
                  轮换
                </Button>
                <Button type="link" size="small">
                  查看绑定
                </Button>
              </Space>
            ),
          },
        ]}
      />
    </section>
  );

  return (
    <PageContainer
      title="Agent 管理"
      content="统一管理 Agent 的代码来源、接入凭证、生命周期版本和生产运行状态。"
      extra={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setConnectOpen(true)}
        >
          接入 Agent
        </Button>
      }
    >
      <section className={styles.summaryLine}>
        <span>
          <small>全部 Agent</small>
          <b>{agents.length}</b>
        </span>
        <span>
          <small>LIVE</small>
          <b>{agents.filter((item) => item.lifecycle === 'live').length}</b>
        </span>
        <span>
          <small>LIVESH</small>
          <b>{agents.filter((item) => item.lifecycle === 'livesh').length}</b>
        </span>
        <span>
          <small>TEST</small>
          <b>{agents.filter((item) => item.lifecycle === 'test').length}</b>
        </span>
        <span>
          <small>需要处理</small>
          <b className={styles.warn}>
            {
              agents.filter(
                (item) =>
                  item.status === 'failed' || item.credential_state !== 'ready',
              ).length
            }
          </b>
        </span>
      </section>
      <Tabs
        className={styles.assetTabs}
        items={[
          { key: 'agents', label: 'Agent 资产', children: agentTable },
          {
            key: 'keys',
            label: `接入凭证 ${credentials.length}`,
            children: keyTable,
          },
        ]}
      />

      <Modal
        open={connectOpen}
        title="接入 Agent"
        width={720}
        okText="创建接入草稿"
        cancelText="取消"
        onCancel={() => setConnectOpen(false)}
        onOk={() => void finishConnect()}
        destroyOnHidden
      >
        <div className={styles.connectKinds}>
          <span>接入方式</span>
          <Segmented
            block
            value={connectKind}
            onChange={setConnectKind}
            options={[
              {
                label: 'GitHub 仓库',
                value: 'github',
                icon: <GithubOutlined />,
              },
              {
                label: '上传代码包',
                value: 'package',
                icon: <CloudUploadOutlined />,
              },
              { label: 'SDK 接入', value: 'sdk', icon: <CodeOutlined /> },
            ]}
          />
        </div>
        <Form form={form} layout="vertical" className={styles.connectForm}>
          <div className={styles.formGrid}>
            <Form.Item
              label="Agent 名称"
              name="name"
              rules={[{ required: true, message: '请输入名称' }]}
            >
              <Input placeholder="例如：Customer Support Agent" />
            </Form.Item>
            <Form.Item
              label="负责人"
              name="owner_id"
              rules={[{ required: true, message: '请选择负责人' }]}
            >
              {/* 负责人决定变更责任，必须从工作区成员里选，不能收任意字符串 */}
              <Select
                placeholder="选择工作区成员"
                options={members.map((item) => ({
                  label: `${item.display_name}（${item.username}）`,
                  value: item.user_id,
                }))}
              />
            </Form.Item>
          </div>
          <Form.Item label="用途说明" name="description">
            <Input placeholder="这个 Agent 负责什么任务" />
          </Form.Item>
          {connectKind === 'github' && (
            <>
              <div className={styles.formGrid}>
                <Form.Item
                  label="GitHub 仓库"
                  name="repository"
                  rules={[{ required: true }]}
                >
                  <Input
                    prefix={<GithubOutlined />}
                    placeholder="organization/repository"
                  />
                </Form.Item>
                <Form.Item label="分支或 Tag" name="ref" initialValue="main">
                  <Input />
                </Form.Item>
              </div>
              <div className={styles.formGrid}>
                <Form.Item label="构建目录" name="build_path" initialValue="/">
                  <Input />
                </Form.Item>
                <Form.Item label="入口文件" name="entrypoint">
                  <Input placeholder="src/agent.py" />
                </Form.Item>
              </div>
            </>
          )}
          {connectKind === 'package' && (
            <>
              <Form.Item
                label="代码包"
                name="artifact"
                rules={[{ required: true, message: '请选择代码包' }]}
              >
                <Upload.Dragger
                  accept=".zip,.tar.gz,.tgz"
                  maxCount={1}
                  beforeUpload={() => false}
                >
                  <p className="ant-upload-drag-icon">
                    <CloudUploadOutlined />
                  </p>
                  <p className="ant-upload-text">拖入代码包，或点击选择文件</p>
                  <p className="ant-upload-hint">
                    支持 ZIP、TAR.GZ；上传后生成不可变制品版本和 SHA-256 校验值
                  </p>
                </Upload.Dragger>
              </Form.Item>
              <div className={styles.formGrid}>
                <Form.Item
                  label="运行时"
                  name="runtime"
                  initialValue="python3.12"
                >
                  <Select
                    options={[
                      { label: 'Python 3.12', value: 'python3.12' },
                      { label: 'Node.js 22', value: 'node22' },
                    ]}
                  />
                </Form.Item>
                <Form.Item label="入口命令" name="entrypoint">
                  <Input placeholder="python -m app.agent" />
                </Form.Item>
              </div>
            </>
          )}
          {connectKind !== 'sdk' && (
            <>
              <Form.Item
                label="记忆作用域"
                name="memory_scope"
                initialValue="thread"
                extra="多 Agent 编排会并发调用同一个 Agent，隐式全局状态必然串味，所以记忆由平台托管、按作用域隔离"
              >
                <Select
                  options={[
                    { label: '按会话隔离（推荐）', value: 'thread' },
                    { label: '按租户共享', value: 'tenant' },
                    { label: '该版本全局共享', value: 'agent_version' },
                    { label: '不需要记忆', value: 'stateless' },
                  ]}
                />
              </Form.Item>

              <div className={styles.sdkNote}>
                <KeyOutlined />
                <div>
                  <strong>模型配置（可选覆盖）</strong>
                  <span>
                    留空则使用「密钥管理」里的工作区默认模型。填了就在本 Agent
                    上覆盖该项。
                  </span>
                </div>
              </div>
              <div className={styles.formGrid}>
                <Form.Item label="BASE_URL" name="model_base_url">
                  <Input placeholder="留空则用工作区默认" />
                </Form.Item>
                <Form.Item label="MODEL" name="model_name">
                  <Input placeholder="留空则用工作区默认" />
                </Form.Item>
              </div>
              <Form.Item
                label="AUTH_TOKEN"
                name="model_auth_token"
                extra="加密存储并由平台注入，不会出现在版本配置里"
              >
                <Input.Password
                  placeholder="留空则用工作区默认"
                  autoComplete="new-password"
                />
              </Form.Item>
            </>
          )}
          {connectKind === 'sdk' && (
            <>
              <div className={styles.sdkNote}>
                <KeyOutlined />
                <div>
                  <strong>使用工作区密钥上报 Trace</strong>
                  <span>创建后可在“接入凭证”中轮换、吊销并查看绑定关系。</span>
                </div>
              </div>
              <div className={styles.formGrid}>
                <Form.Item
                  label="接入密钥"
                  name="credential"
                  rules={[{ required: true }]}
                >
                  <Select
                    placeholder="选择已有密钥"
                    options={credentials.map((item) => ({
                      label: `${item.name} · ${item.prefix}`,
                      value: item.id,
                    }))}
                  />
                </Form.Item>
                <Form.Item label="SDK" name="sdk" initialValue="python">
                  <Select
                    options={[
                      { label: 'Python / DeepEval', value: 'python' },
                      { label: 'TypeScript', value: 'typescript' },
                      { label: 'OpenTelemetry', value: 'otel' },
                    ]}
                  />
                </Form.Item>
              </div>
            </>
          )}
        </Form>
      </Modal>

      <Modal
        open={Boolean(releaseAgent)}
        title="变更生命周期"
        width={760}
        okText={
          targetLifecycle === 'live'
            ? '通过门禁并发布'
            : targetLifecycle === 'livesh'
              ? '进入影子验证'
              : '保存 TEST 版本'
        }
        cancelText="取消"
        onCancel={() => setReleaseAgent(undefined)}
        onOk={confirmLifecycle}
        destroyOnHidden
      >
        {releaseAgent && (
          <div className={styles.releasePanel}>
            <header>
              <div>
                <strong>{releaseAgent.name}</strong>
                <span>{releaseAgent.source_ref}</span>
              </div>
              <code>{releaseAgent.version}</code>
            </header>
            <div className={styles.releaseTarget}>
              <label htmlFor="target-lifecycle">目标生命周期</label>
              <Select
                id="target-lifecycle"
                value={targetLifecycle}
                onChange={setTargetLifecycle}
                options={lifecycleOptions}
              />
              <span>变更必须引用最近一次通过的评测证据。</span>
            </div>

            {(() => {
              const transition = transitionTo(policy, targetLifecycle);
              if (targetLifecycle === 'test') {
                return (
                  <div className={styles.releaseGate}>
                    <strong>TEST 是候选通道</strong>
                    <span>冻结新版本即自动进入 TEST，无需晋级操作。</span>
                  </div>
                );
              }
              if (!transition) {
                return (
                  <div className={styles.releaseGate}>
                    <strong>没有声明这条迁移</strong>
                    <span>
                      当前治理策略里没有 {targetLifecycle.toUpperCase()}{' '}
                      方向的规则，
                      无法晋级。可在「组织与成员」的治理策略里配置。
                    </span>
                  </div>
                );
              }
              const enabled = transition.checks.filter((item) => item.enabled);
              return (
                <div className={styles.releaseGate}>
                  <div className={styles.releaseGateHeader}>
                    <strong>
                      {transition.from_channel.toUpperCase()} →{' '}
                      {transition.to_channel.toUpperCase()} 需要
                    </strong>
                    <code>{transition.permission}</code>
                  </div>
                  <ol>
                    {enabled.map((check) => (
                      <li key={check.name}>{describeCheck(check)}</li>
                    ))}
                  </ol>
                  {transition.requires_reauth && (
                    <span className={styles.releaseGateWarn}>
                      发布到生产需要二次确认，提交时会再校验一次。
                    </span>
                  )}
                </div>
              );
            })()}
            <div className={styles.lifecycleMatrix}>
              {[
                {
                  key: 'test',
                  name: 'TEST',
                  method: '固定数据集回归、能力/安全评测、轨迹评测',
                  evidence: 'Benchmark #482 · 94.2',
                  gate: '12 / 12 通过',
                },
                {
                  key: 'livesh',
                  name: 'LIVESH',
                  method: '镜像真实流量，与 LIVE 基线做配对对比',
                  evidence: 'Shadow #119 · +3.1%',
                  gate: '成本与延迟通过',
                },
                {
                  key: 'live',
                  name: 'LIVE',
                  method: '在线抽样评测、漂移监控、告警与自动回退',
                  evidence: '24h Monitor · 稳定',
                  gate: 'SLO 4 / 4 通过',
                },
              ].map((item) => (
                <section
                  key={item.key}
                  className={
                    item.key === targetLifecycle ? styles.lifecycleSelected : ''
                  }
                >
                  <div>
                    <Tag>{item.name}</Tag>
                    <strong>{item.method}</strong>
                  </div>
                  <span>{item.evidence}</span>
                  <b>{item.gate}</b>
                </section>
              ))}
            </div>
            <footer>
              <span>门禁指标</span>
              <Tag>质量 ≥ 88</Tag>
              <Tag>错误率 ≤ 2%</Tag>
              <Tag>P95 ≤ 2.5s</Tag>
              <Tag>成本增幅 ≤ 10%</Tag>
              <Tag>LLM 调用 ≤ 4.0</Tag>
            </footer>
          </div>
        )}
      </Modal>
    </PageContainer>
  );
}
