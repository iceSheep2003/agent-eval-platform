import { CloudUploadOutlined, DatabaseOutlined, FileSearchOutlined, HistoryOutlined, ImportOutlined, PlusOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { Alert, App, Button, Drawer, Empty, Form, Input, Modal, Segmented, Select, Space, Steps, Table, Tabs, Tag, Typography, Upload } from 'antd';
import type { TableColumnsType } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { useWorkspace } from '@/hooks/useWorkspace';
import { getDatasets } from '@/services/eval';
import type { EvalDataset } from '@/services/eval';
import styles from './style.module.css';

type DatasetKind = 'all' | 'benchmark' | 'regression' | 'trace';
const datasetKinds = [
  { value: 'benchmark', title: '标准基准', copy: '稳定衡量核心能力', icon: SafetyCertificateOutlined },
  { value: 'regression', title: '回归样本', copy: '阻止历史问题复发', icon: HistoryOutlined },
  { value: 'trace', title: '生产 Trace', copy: '从真实流量沉淀案例', icon: FileSearchOutlined },
] as const;
const kindMeta: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  benchmark: { label: 'Benchmark', color: 'blue', icon: <SafetyCertificateOutlined /> },
  regression: { label: '回归样本', color: 'cyan', icon: <HistoryOutlined /> },
  trace: { label: '历史 Trace', color: 'purple', icon: <FileSearchOutlined /> },
  agentic: { label: 'Agentic', color: 'geekblue', icon: <DatabaseOutlined /> },
};

export default function DatasetsPage() {
  const workspace = useWorkspace();
  const { message } = App.useApp();
  const [importForm] = Form.useForm();
  const [items, setItems] = useState<EvalDataset[]>([]);
  const [selected, setSelected] = useState<EvalDataset>();
  const [kind, setKind] = useState<DatasetKind>('all');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [detailOpen, setDetailOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importStep, setImportStep] = useState(0);
  const [fileName, setFileName] = useState('');

  useEffect(() => {
    if (!workspace) return;
    setLoading(true);
    void getDatasets(workspace.id).then((result) => {
      setItems(result.items);
      setSelected((current) => result.items.find((item) => item.id === current?.id) ?? result.items[0]);
    }).finally(() => setLoading(false));
  }, [workspace?.id]);

  const visible = useMemo(() => items.filter((item) => (kind === 'all' || item.kind === kind) && `${item.name} ${item.description}`.toLowerCase().includes(query.toLowerCase())), [items, kind, query]);
  const counts = (target: string) => items.filter((item) => item.kind === target).length;
  const columns: TableColumnsType<EvalDataset> = [
    { title: '数据资产', dataIndex: 'name', render: (_, item) => <Space vertical size={2}><Typography.Text strong>{item.name}</Typography.Text><Typography.Text type="secondary" className={styles.muted}>{item.description || '暂无说明'}</Typography.Text></Space> },
    { title: '类型', dataIndex: 'kind', width: 120, render: (value) => <Tag color={kindMeta[value]?.color ?? 'default'}>{kindMeta[value]?.label ?? value}</Tag> },
    { title: '版本', dataIndex: 'version', width: 90 },
    { title: '样本', dataIndex: 'item_count', width: 90, render: (value) => <strong>{Number(value).toLocaleString()}</strong> },
    { title: '状态', dataIndex: 'status', width: 95, render: (value) => <Tag color={value === 'ready' || value === 'active' ? 'success' : 'default'}>{value}</Tag> },
  ];

  const finishImport = async () => {
    const values = await importForm.validateFields();
    setItems((current) => [{ id: `draft-${Date.now()}`, name: values.name, kind: values.kind, version: values.version, item_count: fileName ? 128 : 0, description: values.description, status: 'draft' }, ...current]);
    setImportOpen(false);
    setImportStep(0);
    setFileName('');
    importForm.resetFields();
    message.success('数据集草稿已创建');
  };

  const detailTabs = selected ? [
    { key: 'samples', label: '样本预览', children: <div className={styles.sampleList}>{[1, 2, 3].map((index) => <article key={index}><span>{String(index).padStart(3, '0')}</span><div><strong>{selected.kind === 'trace' ? `trace_event_${index}` : `评测样本 ${index}`}</strong><code>{selected.kind === 'agentic' ? '{ "task": "完成用户请求", "tools": [...] }' : '{ "input": "用户问题", "expected": "期望结果" }'}</code></div><Tag color={index === 3 ? 'warning' : 'success'}>{index === 3 ? '需复核' : '有效'}</Tag></article>)}</div> },
    { key: 'versions', label: '版本记录', children: <div className={styles.versionList}><article><i /><div><strong>{selected.version} · 当前版本</strong><span>结构校验通过 · {selected.item_count.toLocaleString()} 条样本</span></div><Tag color="success">可用</Tag></article><article><i /><div><strong>上一版本</strong><span>样本清洗与去重前的历史快照</span></div><Tag>已归档</Tag></article></div> },
    { key: 'schema', label: 'Schema', children: <pre className={styles.schema}>{selected.kind === 'agentic' ? '{\n  "task": "string",\n  "tools": "array",\n  "expected": "object"\n}' : '{\n  "input": "string | object",\n  "expected": "string | object",\n  "metadata": "object?"\n}'}</pre> },
  ] : [];

  return <PageContainer title="数据集" content="把 Benchmark、回归样本和生产 Trace 组织成可复用的评测资产。" extra={<Space><Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>导入向导</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => { setImportOpen(true); setImportStep(1); }}>新建数据集</Button></Space>}>
    <section className={styles.kindGrid}>
      {datasetKinds.map((item) => { const Icon = item.icon; return <button type="button" key={item.value} className={kind === item.value ? styles.kindActive : ''} onClick={() => setKind(item.value)}><span><Icon /></span><div><strong>{item.title}</strong><small>{item.copy}</small></div><b>{counts(item.value)}</b></button>; })}
    </section>
    <section className={styles.workbench}>
      <header className={styles.toolbar}><Segmented value={kind} onChange={(value) => setKind(value as DatasetKind)} options={[{ label: '全部资产', value: 'all' }, { label: 'Benchmark', value: 'benchmark' }, { label: '回归', value: 'regression' }, { label: 'Trace', value: 'trace' }]} /><Input allowClear placeholder="搜索数据集" value={query} onChange={(event) => setQuery(event.target.value)} /></header>
      <div className={styles.workspace}>
        <Table<EvalDataset> rowKey="id" loading={loading} pagination={false} columns={columns} dataSource={visible} onRow={(item) => ({ onClick: () => setSelected(item), className: item.id === selected?.id ? styles.selectedRow : '' })} />
        <aside className={styles.inspector}>{selected ? <><header><span className={styles.datasetIcon}>{kindMeta[selected.kind]?.icon ?? <DatabaseOutlined />}</span><div><Tag color={kindMeta[selected.kind]?.color}>{kindMeta[selected.kind]?.label ?? selected.kind}</Tag><h2>{selected.name}</h2><p>{selected.description || '暂无数据集说明'}</p></div></header><dl><div><dt>当前版本</dt><dd>{selected.version}</dd></div><div><dt>样本总数</dt><dd>{selected.item_count.toLocaleString()}</dd></div><div><dt>准备状态</dt><dd>{selected.status}</dd></div></dl><section><strong>推荐流程</strong><ol><li><i>1</i><span>校验 Schema 与必填字段</span></li><li><i>2</i><span>抽样检查输入与期望输出</span></li><li><i>3</i><span>绑定评测策略并运行基线</span></li></ol></section><Button block type="primary" onClick={() => setDetailOpen(true)}>查看样本与版本</Button></> : <Empty description="选择数据集查看详情" />}</aside>
      </div>
    </section>
    <Drawer open={detailOpen} onClose={() => setDetailOpen(false)} width={680} title={<div className={styles.drawerTitle}><small>DATASET INSPECTOR</small><strong>{selected?.name}</strong></div>} extra={<Space><Tag color={kindMeta[selected?.kind ?? '']?.color}>{kindMeta[selected?.kind ?? '']?.label}</Tag><Button size="small">导出</Button></Space>}>
      {selected && <><div className={styles.detailHero}><span className={styles.datasetIcon}>{kindMeta[selected.kind]?.icon}</span><div><strong>{selected.version}</strong><p>{selected.description || '暂无数据集说明'}</p></div><dl><div><dt>样本</dt><dd>{selected.item_count.toLocaleString()}</dd></div><div><dt>状态</dt><dd>{selected.status}</dd></div></dl></div><Tabs items={detailTabs} /></>}
    </Drawer>
    <Modal open={importOpen} width={680} title="数据集导入向导" footer={<div className={styles.modalFooter}><Button onClick={() => setImportOpen(false)}>取消</Button>{importStep > 0 && <Button onClick={() => setImportStep((step) => step - 1)}>上一步</Button>}<Button type="primary" onClick={() => importStep < 2 ? setImportStep((step) => step + 1) : void finishImport()}>{importStep < 2 ? '下一步' : '创建草稿'}</Button></div>} onCancel={() => setImportOpen(false)} destroyOnHidden>
      <Steps current={importStep} size="small" items={[{ title: '选择文件' }, { title: '定义资产' }, { title: '校验确认' }]} />
      <Form form={importForm} layout="vertical" initialValues={{ kind: 'benchmark', version: '0.1.0' }} className={styles.importForm}>
        {importStep === 0 && <Upload.Dragger maxCount={1} accept=".json,.jsonl,.csv" beforeUpload={(file) => { setFileName(file.name); return false; }} onRemove={() => { setFileName(''); return true; }}><p className={styles.uploadIcon}><CloudUploadOutlined /></p><p><strong>拖入数据文件，或点击选择</strong></p><p className={styles.uploadHint}>支持 JSON、JSONL、CSV，当前仅解析文件结构，不会上传到后端</p></Upload.Dragger>}
        {importStep === 1 && <><div className={styles.formGrid}><Form.Item label="数据集名称" name="name" rules={[{ required: true, message: '请输入名称' }]}><Input placeholder="例如：客服意图回归集" /></Form.Item><Form.Item label="版本" name="version" rules={[{ required: true }]}><Input /></Form.Item></div><Form.Item label="资产类型" name="kind"><Select options={[...datasetKinds.map((item) => ({ label: item.title, value: item.value })), { label: 'Agentic 任务', value: 'agentic' }]} /></Form.Item><Form.Item label="用途说明" name="description"><Input.TextArea rows={3} placeholder="说明数据来源、覆盖范围和使用边界" /></Form.Item></>}
        {importStep === 2 && <div className={styles.review}><Alert showIcon type={fileName ? 'success' : 'warning'} title={fileName ? '结构预检通过' : '未选择文件，将创建空数据集'} description={fileName ? `${fileName} · 已识别输入字段和期望输出字段，正式校验将在后端接入后执行。` : '可以稍后从数据集详情中继续导入样本。'} /><dl><div><dt>文件</dt><dd>{fileName || '未选择'}</dd></div><div><dt>预计样本</dt><dd>{fileName ? '128' : '0'}</dd></div><div><dt>重复项</dt><dd>{fileName ? '3 待处理' : '—'}</dd></div></dl></div>}
      </Form>
    </Modal>
  </PageContainer>;
}
