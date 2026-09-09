import { PauseCircleOutlined, PlayCircleOutlined, PlusOutlined, ReloadOutlined, SearchOutlined, StopOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { App, Button, Drawer, Empty, Form, Input, InputNumber, Modal, Progress, Segmented, Select, Space, Steps, Table, Tag, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useWorkspace } from '@/hooks/useWorkspace';
import { getRun, getRuns, runAction } from '@/services/eval';
import type { EvalRun, EvalRunDetail, TraceEvent } from '@/services/eval';
import styles from './style.module.css';

const labels: Record<string, string> = { queued: '排队中', running: '运行中', paused: '已暂停', completed: '已完成', failed: '失败', cancelled: '已停止' };
const colors: Record<string, string> = { queued: 'default', running: 'processing', paused: 'warning', completed: 'success', failed: 'error', cancelled: 'default' };
const phases = ['provisioning', 'executing', 'scoring', 'completed'];
const phaseLabels = ['准备环境', '执行任务', '汇总评分', '完成'];

function duration(seconds: number) {
  return `${Math.floor(seconds / 60)}m ${String(Math.round(seconds % 60)).padStart(2, '0')}s`;
}

function parseTrace(value?: string) {
  if (!value) return '';
  try { return JSON.stringify(JSON.parse(value), null, 2); } catch { return value; }
}

function TraceRail({ events }: { events: TraceEvent[] }) {
  if (!events.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无 Trace 事件" />;
  return <div className={styles.traceRail}>{events.map((event) => <article key={event.id} className={styles.traceEvent}>
    <span className={`${styles.traceNode} ${styles[event.event_type] ?? ''}`} />
    <div className={styles.traceCopy}>
      <header><strong>{event.name}</strong><Tag variant="filled">{event.event_type}</Tag><time>{new Date(event.started_at).toLocaleTimeString('zh-CN', { hour12: false })}</time></header>
      <p>{parseTrace(event.output) || parseTrace(event.input) || event.actor}</p>
    </div>
  </article>)}</div>;
}

export default function RunsPage() {
  const workspace = useWorkspace();
  const { message } = App.useApp();
  const [createForm] = Form.useForm();
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [selected, setSelected] = useState<EvalRunDetail>();
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [createOpen, setCreateOpen] = useState(false);
  const [trialsOpen, setTrialsOpen] = useState(false);

  const refresh = useCallback(async () => {
    if (!workspace) return;
    setLoading(true);
    try {
      const result = await getRuns(workspace.id);
      setRuns(result.items);
      const target = result.items.find((item) => item.id === selected?.id) ?? result.items[0];
      setSelected(target ? await getRun(workspace.id, target.id) : undefined);
    } finally { setLoading(false); }
  }, [workspace, selected?.id]);

  useEffect(() => { void refresh(); }, [workspace?.id]);

  const choose = async (run: EvalRun) => {
    if (!workspace) return;
    if (run.id.startsWith('draft-')) {
      setSelected({ ...run, trials: [], traces: [], scores: [] });
      return;
    }
    setSelected(await getRun(workspace.id, run.id));
  };

  const act = async (action: 'pause' | 'resume' | 'stop') => {
    if (!workspace || !selected) return;
    setSelected(await runAction(workspace.id, selected.id, action));
    message.success(action === 'pause' ? '暂停请求已提交' : action === 'resume' ? '恢复请求已提交' : '停止请求已提交');
    await refresh();
  };

  const visible = useMemo(() => runs.filter((item) => (status === 'all' || item.status === status) && `${item.name} ${item.agent_name} ${item.dataset_name}`.toLowerCase().includes(query.toLowerCase())), [runs, query, status]);
  const average = runs.length ? Math.round(runs.reduce((sum, item) => sum + item.score, 0) / runs.length * 100) : 0;
  const columns: TableColumnsType<EvalRun> = [
    { title: '运行实例', dataIndex: 'name', render: (_, item) => <Space vertical size={1}><Typography.Text strong>{item.name}</Typography.Text><Typography.Text type="secondary" className={styles.secondary}>{item.agent_name} · {item.dataset_name}</Typography.Text></Space> },
    { title: '状态', dataIndex: 'status', width: 92, render: (value) => <Tag color={colors[value]}>{labels[value] ?? value}</Tag> },
    { title: '进度', dataIndex: 'progress', width: 130, render: (value) => <Progress percent={value} size="small" showInfo={false} /> },
    { title: '得分', dataIndex: 'score', width: 70, render: (value, item) => item.status === 'completed' ? <strong>{Math.round(value * 100)}</strong> : '—' },
    { title: '更新', dataIndex: 'updated_at', width: 108, render: (value) => <Typography.Text type="secondary" className={styles.secondary}>{new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })}</Typography.Text> },
  ];
  const phaseIndex = selected?.phase === 'failed' ? 2 : Math.max(0, phases.indexOf(selected?.phase ?? 'provisioning'));

  const createDraftRun = async () => {
    const values = await createForm.validateFields();
    const timestamp = new Date().toISOString();
    const draft: EvalRunDetail = { id: `draft-${Date.now()}`, name: values.name, agent_name: values.agent, agent_version: values.version, dataset_name: values.dataset, status: 'queued', phase: 'provisioning', progress: 0, passed: 0, total: 0, score: 0, cost: 0, duration_seconds: 0, updated_at: timestamp, trials: [], traces: [], scores: [] };
    setRuns((current) => [draft, ...current]);
    setSelected(draft);
    setCreateOpen(false);
    createForm.resetFields();
    message.success('运行草稿已创建，等待后端执行接口接入');
  };

  return <PageContainer title="实验运行" content="对比版本质量、定位失败任务，并查看每次执行的完整轨迹。" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建运行</Button>}>
    <section className={styles.signalBar}>
      <div><span>运行总数</span><strong>{runs.length}</strong></div><i />
      <div><span className={styles.liveDot} />运行中<strong>{runs.filter((item) => item.status === 'running').length}</strong></div><i />
      <div><span className={styles.failDot} />失败<strong>{runs.filter((item) => item.status === 'failed').length}</strong></div><i />
      <div><span>平均得分</span><strong>{average}<small>/100</small></strong></div>
      <Button type="text" icon={<ReloadOutlined />} loading={loading} onClick={() => void refresh()}>刷新</Button>
    </section>
    <section className={styles.workbench}>
      <header className={styles.toolbar}>
        <Segmented value={status} onChange={(value) => setStatus(String(value))} options={[{ label: '全部', value: 'all' }, { label: '运行中', value: 'running' }, { label: '已完成', value: 'completed' }, { label: '失败', value: 'failed' }, { label: '已暂停', value: 'paused' }]} />
        <Input allowClear prefix={<SearchOutlined />} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索运行、Agent 或数据集" />
      </header>
      <div className={styles.workspace}>
        <div className={styles.listPane}><Table<EvalRun> rowKey="id" loading={loading} pagination={false} columns={columns} dataSource={visible} onRow={(item) => ({ onClick: () => void choose(item), className: item.id === selected?.id ? styles.selectedRow : '' })} /></div>
        <aside className={styles.inspector}>
          {selected ? <>
            <header className={styles.inspectorHeader}><div><Tag color={colors[selected.status]}>{labels[selected.status]}</Tag><code>{selected.id}</code></div><h2>{selected.name}</h2><p>{selected.agent_name} / {selected.agent_version} · {selected.dataset_name}</p></header>
            <div className={styles.actions}>{['running', 'paused'].includes(selected.status) ? <><Button icon={selected.status === 'paused' ? <PlayCircleOutlined /> : <PauseCircleOutlined />} onClick={() => void act(selected.status === 'paused' ? 'resume' : 'pause')}>{selected.status === 'paused' ? '恢复' : '暂停'}</Button><Button danger icon={<StopOutlined />} onClick={() => void act('stop')}>停止</Button></> : <Typography.Text type="secondary">结果已固化，可用于版本对比和失败回灌</Typography.Text>}</div>
            <div className={styles.inspectorMetrics}><div><span>质量得分</span><strong>{selected.status === 'completed' ? Math.round(selected.score * 100) : '—'}<small>/100</small></strong></div><div><span>任务通过</span><strong>{selected.passed}<small>/{selected.total}</small></strong></div><div><span>成本</span><strong>${selected.cost.toFixed(2)}</strong></div><div><span>耗时</span><strong>{duration(selected.duration_seconds)}</strong></div></div>
            <section className={styles.section}><header><span>执行进度</span><strong>{selected.progress}%</strong></header><Progress percent={selected.progress} showInfo={false} /><Steps current={phaseIndex} size="small" items={phaseLabels.map((title) => ({ title }))} status={selected.phase === 'failed' ? 'error' : 'process'} /></section>
            <section className={`${styles.section} ${styles.traceSection}`}><header><span>最近事件</span><Space size={4}><small>{selected.status === 'running' ? '实时更新' : '已固化'}</small><Button type="link" size="small" onClick={() => setTrialsOpen(true)}>任务明细</Button></Space></header><TraceRail events={selected.traces} /></section>
          </> : <Empty description="选择一个运行查看详情" />}
        </aside>
      </div>
    </section>
    <Drawer open={trialsOpen} onClose={() => setTrialsOpen(false)} width={720} title={<div className={styles.drawerTitle}><small>RUN EVIDENCE</small><strong>{selected?.name} · 任务与评分明细</strong></div>}>
      {selected && <><div className={styles.evidenceSummary}><div><span>通过任务</span><strong>{selected.passed}<small>/{selected.total}</small></strong></div><div><span>平均得分</span><strong>{Math.round(selected.score * 100)}</strong></div><div><span>总成本</span><strong>${selected.cost.toFixed(2)}</strong></div><div><span>Trace 事件</span><strong>{selected.traces.length}</strong></div></div><Typography.Title level={5}>Trial 结果</Typography.Title><Table rowKey="id" size="small" pagination={false} dataSource={selected.trials} columns={[{ title: 'Trial ID', dataIndex: 'id', render: (value: string) => <code>{value}</code> }, { title: '状态', dataIndex: 'status', width: 100, render: (value: string) => <Tag color={value === 'completed' || value === 'passed' ? 'success' : value === 'failed' ? 'error' : 'default'}>{value}</Tag> }, { title: '得分', dataIndex: 'score', width: 90, render: (value: number) => Math.round(value * 100) }, { title: '耗时', dataIndex: 'duration_ms', width: 110, render: (value: number) => `${value} ms` }]} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="运行后将在这里展示逐任务证据" /> }} /><Typography.Title level={5} className={styles.scoreTitle}>维度评分</Typography.Title><div className={styles.scoreGrid}>{selected.scores.length ? selected.scores.map((score) => <article key={score.id}><span>{score.dimension_id}</span><strong>{Math.round(score.value * 100)}</strong><Progress percent={Math.round(score.value * 100)} showInfo={false} /></article>) : <Typography.Text type="secondary">暂无维度评分</Typography.Text>}</div></>}
    </Drawer>
    <Modal open={createOpen} title="新建评测运行" width={640} okText="创建运行草稿" cancelText="取消" onCancel={() => setCreateOpen(false)} onOk={() => void createDraftRun()} destroyOnHidden>
      <div className={styles.createHint}><PlusOutlined /><div><strong>定义一次可复现的评测运行</strong><span>选择 Agent 版本和数据集，限制预算；执行动作将在后端接口稳定后接入。</span></div></div>
      <Form form={createForm} layout="vertical" initialValues={{ agent: 'Customer Support Agent', version: '1.0.0', dataset: '客服策略回归', concurrency: 4, budget: 10 }}>
        <Form.Item label="运行名称" name="name" rules={[{ required: true, message: '请输入运行名称' }]}><Input placeholder="例如：v1.2 发布前回归" /></Form.Item>
        <div className={styles.formGrid}><Form.Item label="Agent" name="agent" rules={[{ required: true }]}><Select options={[...new Set(runs.map((item) => item.agent_name))].map((value) => ({ label: value, value }))} /></Form.Item><Form.Item label="版本" name="version"><Select options={[...new Set(runs.map((item) => item.agent_version))].map((value) => ({ label: value, value }))} /></Form.Item></div>
        <Form.Item label="评测数据集" name="dataset" rules={[{ required: true }]}><Select options={[...new Set(runs.map((item) => item.dataset_name))].map((value) => ({ label: value, value }))} /></Form.Item>
        <div className={styles.formGrid}><Form.Item label="并发任务数" name="concurrency"><InputNumber min={1} max={32} style={{ width: '100%' }} /></Form.Item><Form.Item label="成本上限" name="budget"><InputNumber min={1} max={1000} prefix="$" style={{ width: '100%' }} /></Form.Item></div>
      </Form>
    </Modal>
  </PageContainer>;
}
