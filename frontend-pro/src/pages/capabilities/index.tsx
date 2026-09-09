import { ApartmentOutlined, CheckCircleOutlined, ExperimentOutlined, PlusOutlined, RocketOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { App, Button, Drawer, Empty, Form, Input, InputNumber, Modal, Progress, Segmented, Select, Space, Spin, Switch, Tag, Typography } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { useWorkspace } from '@/hooks/useWorkspace';
import { getCapabilities, getPolicies } from '@/services/eval';
import type { EvalCapability, EvalPolicy } from '@/services/eval';
import styles from './style.module.css';

const stages = [
  { key: 'development', title: '开发验证', copy: '提示词与工具快速试验', icon: <ExperimentOutlined /> },
  { key: 'regression', title: '持续回归', copy: '阻断能力退化', icon: <ApartmentOutlined /> },
  { key: 'release', title: '发布门禁', copy: '版本上线前质量判定', icon: <SafetyCertificateOutlined /> },
  { key: 'production', title: '生产监控', copy: '真实流量与异常回灌', icon: <RocketOutlined /> },
];

export default function CapabilitiesPage() {
  const workspace = useWorkspace();
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [createForm] = Form.useForm();
  const [capabilities, setCapabilities] = useState<EvalCapability[]>([]);
  const [policies, setPolicies] = useState<EvalPolicy[]>([]);
  const [stage, setStage] = useState('regression');
  const [view, setView] = useState<'policies' | 'dimensions'>('policies');
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<EvalPolicy>();
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!workspace) return;
    setLoading(true);
    void Promise.all([getCapabilities(workspace.id), getPolicies(workspace.id)]).then(([capabilityResult, policyResult]) => {
      setCapabilities(capabilityResult.items);
      setPolicies(policyResult.items);
    }).finally(() => setLoading(false));
  }, [workspace?.id]);

  const stagePolicies = useMemo(() => policies.filter((policy) => policy.lifecycle === stage), [policies, stage]);
  const dimensions = capabilities.flatMap((capability) => capability.dimensions.map((dimension) => ({ ...dimension, capability: capability.name })));

  const openEditor = (policy: EvalPolicy) => {
    setEditing(policy);
    form.setFieldsValue({ ...policy, evaluators: policy.evaluators, success_rate: Math.round(Number(policy.gates.success_rate ?? 0.85) * 100), safety_rate: Math.round(Number(policy.gates.safety_violation_rate ?? 0) * 100) });
  };

  const savePolicy = async () => {
    const values = await form.validateFields();
    setPolicies((current) => current.map((policy) => policy.id === editing?.id ? { ...policy, ...values, gates: { ...policy.gates, success_rate: values.success_rate / 100, safety_violation_rate: values.safety_rate / 100 } } : policy));
    setEditing(undefined);
    message.success('策略配置已保存到前端原型');
  };

  const createPolicy = async () => {
    const values = await createForm.validateFields();
    const policy: EvalPolicy = { id: `draft-${Date.now()}`, name: values.name, lifecycle: values.lifecycle, dataset_name: values.dataset_name, dataset_version: 'draft', evaluators: values.evaluators, trigger_type: values.trigger_type, gates: { success_rate: values.success_rate / 100 }, enabled: true, binding_count: 0 };
    setPolicies((current) => [policy, ...current]);
    setStage(policy.lifecycle);
    setCreating(false);
    createForm.resetFields();
    message.success('策略草稿已创建');
  };

  return <PageContainer title="评测策略" content="把能力模型、数据集、评估器和质量门禁编排进 Agent 生命周期。" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>创建策略</Button>}>
    <section className={styles.overview}><div><span>已启用策略</span><strong>{policies.filter((item) => item.enabled).length}</strong></div><i /><div><span>能力域</span><strong>{capabilities.length}</strong></div><i /><div><span>评分维度</span><strong>{dimensions.length}</strong></div><i /><div><span>Agent 绑定</span><strong>{policies.reduce((sum, item) => sum + item.binding_count, 0)}</strong></div></section>
    <section className={styles.workbench}>
      <aside className={styles.lifecycle}><header><small>EVALUATION LIFECYCLE</small><strong>评测生命周期</strong></header>{stages.map((item, index) => <button type="button" key={item.key} className={item.key === stage ? styles.active : ''} onClick={() => setStage(item.key)}><span>{item.icon}</span><div><strong>{item.title}</strong><small>{item.copy}</small></div><b>{policies.filter((policy) => policy.lifecycle === item.key).length}</b>{index < stages.length - 1 && <i />}</button>)}</aside>
      <main className={styles.canvas}>
        <header className={styles.toolbar}><div><Typography.Title className={styles.viewTitle} level={4}>{stages.find((item) => item.key === stage)?.title}</Typography.Title><Typography.Text type="secondary">{stages.find((item) => item.key === stage)?.copy}</Typography.Text></div><Segmented value={view} onChange={(value) => setView(value as 'policies' | 'dimensions')} options={[{ label: '策略编排', value: 'policies' }, { label: '能力维度', value: 'dimensions' }]} /></header>
        <Spin spinning={loading}>{view === 'policies' ? <div className={styles.policyGrid}>{stagePolicies.length ? stagePolicies.map((policy) => <article key={policy.id} className={styles.policyCard}><header><div><Tag color={policy.enabled ? 'success' : 'default'}>{policy.enabled ? '已启用' : '已停用'}</Tag><small>{policy.trigger_type}</small></div><h3>{policy.name}</h3><p>{policy.dataset_name} · {policy.dataset_version}</p></header><section><span>评估器</span><div>{policy.evaluators.map((evaluator) => <Tag key={evaluator}>{evaluator}</Tag>)}</div></section><section><span>质量门禁</span>{Object.entries(policy.gates).length ? Object.entries(policy.gates).map(([name, threshold]) => <div className={styles.gate} key={name}><small>{name.replaceAll('_', ' ')}</small><strong>{Math.round(Number(threshold) * 100)}%</strong><Progress percent={Math.round(Number(threshold) * 100)} showInfo={false} size="small" /></div>) : <Typography.Text type="secondary">未设置硬门禁</Typography.Text>}</section><footer><span><CheckCircleOutlined /> {policy.binding_count} 个 Agent 已绑定</span><Button size="small" onClick={() => openEditor(policy)}>配置</Button></footer></article>) : <Empty description="当前生命周期暂无策略" />}</div> : <div className={styles.dimensionGrid}>{dimensions.map((dimension) => <article key={dimension.id}><header><div><small>{dimension.capability}</small><h3>{dimension.name}</h3></div><strong>{dimension.score}</strong></header><Progress percent={dimension.score} strokeColor={dimension.score >= dimension.threshold * 100 ? '#55b99d' : '#e07a7f'} /><footer><span>权重 {dimension.weight}</span><span>阈值 {Math.round(dimension.threshold * 100)}</span></footer></article>)}</div>}</Spin>
      </main>
    </section>
    <Drawer open={Boolean(editing)} onClose={() => setEditing(undefined)} width={560} title={<div className={styles.drawerTitle}><small>POLICY CONTROL</small><strong>{editing?.name}</strong></div>} extra={<Space><Tag color={editing?.enabled ? 'success' : 'default'}>{editing?.enabled ? '已启用' : '已停用'}</Tag><Switch size="small" checked={editing?.enabled} onChange={(enabled) => setEditing((current) => current ? { ...current, enabled } : current)} /></Space>} footer={<div className={styles.drawerFooter}><Button onClick={() => setEditing(undefined)}>取消</Button><Button type="primary" onClick={() => void savePolicy()}>保存配置</Button></div>}>
      {editing && <Form form={form} layout="vertical" requiredMark="optional" className={styles.editorForm}>
        <div className={styles.editorIntro}><span>{stages.find((item) => item.key === editing.lifecycle)?.icon}</span><div><strong>策略链路配置</strong><p>调整触发时机、评估器和门禁阈值。变更仅保存在当前 UI 原型，后端重构后再接正式接口。</p></div></div>
        <section><header><b>01</b><div><strong>运行方式</strong><small>决定策略在哪个阶段、以什么方式触发</small></div></header><div className={styles.formGrid}><Form.Item label="生命周期" name="lifecycle" rules={[{ required: true }]}><Select options={stages.map((item) => ({ label: item.title, value: item.key }))} /></Form.Item><Form.Item label="触发方式" name="trigger_type" rules={[{ required: true }]}><Select options={[{ label: '手动触发', value: 'manual' }, { label: '发布后自动触发', value: 'release' }, { label: '定时运行', value: 'schedule' }, { label: '生产异常触发', value: 'incident' }]} /></Form.Item></div></section>
        <section><header><b>02</b><div><strong>评估信号</strong><small>组合确定性规则、模型评分和策略合规检查</small></div></header><Form.Item label="评估器" name="evaluators" rules={[{ required: true }]}><Select mode="multiple" options={[{ value: 'deterministic_match', label: '确定性匹配' }, { value: 'llm_judge', label: 'LLM Judge' }, { value: 'policy_compliance', label: '策略合规' }, { value: 'trajectory_quality', label: '轨迹质量' }]} /></Form.Item></section>
        <section><header><b>03</b><div><strong>质量门禁</strong><small>任何硬门禁失败都会阻断对应生命周期动作</small></div></header><div className={styles.thresholdRow}><div><strong>任务成功率</strong><small>通过任务占全部评测任务的比例</small></div><Form.Item name="success_rate"><InputNumber min={0} max={100} suffix="%" /></Form.Item></div><div className={styles.thresholdRow}><div><strong>安全违规上限</strong><small>允许出现策略违规的最大比例</small></div><Form.Item name="safety_rate"><InputNumber min={0} max={100} suffix="%" /></Form.Item></div></section>
      </Form>}
    </Drawer>
    <Modal open={creating} title="创建评测策略" width={620} okText="创建草稿" cancelText="取消" onCancel={() => setCreating(false)} onOk={() => void createPolicy()} destroyOnHidden>
      <div className={styles.createHint}><SafetyCertificateOutlined /><span>先建立可评审的策略草稿，绑定 Agent 和正式发布可以在后续步骤完成。</span></div>
      <Form form={createForm} layout="vertical" initialValues={{ lifecycle: 'regression', trigger_type: 'manual', evaluators: ['deterministic_match'], success_rate: 85 }}>
        <Form.Item label="策略名称" name="name" rules={[{ required: true, message: '请输入策略名称' }]}><Input placeholder="例如：客服 Agent 发布门禁" /></Form.Item>
        <div className={styles.formGrid}><Form.Item label="生命周期" name="lifecycle" rules={[{ required: true }]}><Select options={stages.map((item) => ({ label: item.title, value: item.key }))} /></Form.Item><Form.Item label="触发方式" name="trigger_type"><Select options={[{ label: '手动触发', value: 'manual' }, { label: '发布后触发', value: 'release' }, { label: '定时运行', value: 'schedule' }]} /></Form.Item></div>
        <Form.Item label="数据集" name="dataset_name" rules={[{ required: true, message: '请选择数据集' }]}><Select placeholder="选择评测数据集" options={[{ label: '客服策略回归 / v1.0', value: '客服策略回归' }, { label: '工具调用基准 / v2.1', value: '工具调用基准' }]} /></Form.Item>
        <Form.Item label="评估器" name="evaluators"><Select mode="multiple" options={[{ value: 'deterministic_match', label: '确定性匹配' }, { value: 'llm_judge', label: 'LLM Judge' }, { value: 'policy_compliance', label: '策略合规' }]} /></Form.Item>
        <Form.Item label="最低成功率" name="success_rate"><InputNumber min={0} max={100} suffix="%" style={{ width: '100%' }} /></Form.Item>
      </Form>
    </Modal>
  </PageContainer>;
}
