import { KeyOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import {
  App,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  Modal,
  Row,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useState } from 'react';
import { useWorkspace } from '@/hooks/useWorkspace';
import {
  MODEL_KEYS,
  listSecretBindings,
  listSecrets,
  putSecret,
  setModelConfig,
  unbindSecret,
  type ResourceSecret,
  type SecretBinding,
} from '@/services/eval/secrets';

const CHANNELS = ['test', 'livesh', 'live'] as const;

/** 这三个键是平台内置的模型配置，界面上单独成块展示。 */
const isModelKey = (name: string) => (MODEL_KEYS as readonly string[]).includes(name);

export default function SecretsPage() {
  const { message, modal } = App.useApp();
  const workspace = useWorkspace();

  const [secrets, setSecrets] = useState<ResourceSecret[]>([]);
  const [bindings, setBindings] = useState<SecretBinding[]>([]);
  const [loading, setLoading] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [createForm] = Form.useForm();
  const [modelForm] = Form.useForm();

  const refresh = useCallback(async () => {
    if (!workspace) return;
    setLoading(true);
    try {
      const [nextSecrets, nextBindings] = await Promise.all([
        listSecrets(workspace.id),
        listSecretBindings(workspace.id),
      ]);
      setSecrets(nextSecrets.items ?? []);
      setBindings(nextBindings.items ?? []);
    } catch {
      // 错误已由 requestErrorConfig 统一提示
    } finally {
      setLoading(false);
    }
  }, [workspace]);

  useEffect(() => {
    void refresh();
  }, [workspace?.id]);

  const modelBindings = bindings.filter((item) => isModelKey(item.secret_name));
  const otherBindings = bindings.filter((item) => !isModelKey(item.secret_name));

  /** 当前生效的模型配置：按通道归拢，便于一眼看出「测试和生产用的不是同一个」。 */
  const modelByChannel = CHANNELS.map((channel) => ({
    channel,
    values: Object.fromEntries(
      modelBindings
        .filter((item) => item.channel === channel)
        .map((item) => [item.secret_name, item]),
    ) as Record<string, SecretBinding | undefined>,
  }));

  const columns: ColumnsType<ResourceSecret> = [
    {
      title: '名称',
      dataIndex: 'name',
      render: (name: string) => (
        <Space size={6}>
          <KeyOutlined style={{ color: '#4f7cff' }} />
          <span>{name}</span>
          {isModelKey(name) && <Tag color="blue">平台内置</Tag>}
        </Space>
      ),
    },
    {
      title: '指纹',
      dataIndex: 'fingerprint',
      width: 140,
      render: (value: string) => (
        <Tooltip title="用于确认「用的是哪一把」，不可反推明文">
          <Typography.Text code>{value}</Typography.Text>
        </Tooltip>
      ),
    },
    { title: '说明', dataIndex: 'description', ellipsis: true },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 180,
      render: (value: string) => new Date(value).toLocaleString(),
    },
  ];

  const bindingColumns: ColumnsType<SecretBinding> = [
    { title: '密钥名', dataIndex: 'secret_name' },
    {
      title: '通道',
      dataIndex: 'channel',
      width: 110,
      render: (channel: string) => <Tag>{channel.toUpperCase()}</Tag>,
    },
    {
      title: '绑定的密钥',
      dataIndex: 'fingerprint',
      width: 160,
      render: (value: string | null) =>
        value ? <Typography.Text code>{value}</Typography.Text> : '—',
    },
    {
      title: '操作',
      width: 90,
      render: (_, item) => (
        <Button
          type="link"
          danger
          size="small"
          onClick={() =>
            modal.confirm({
              title: `解绑 ${item.secret_name}？`,
              content:
                '解绑后，没有单独覆盖该项的 Agent 会失去这个密钥——下次调用会直接失败，而不是拿到空值。',
              okButtonProps: { danger: true },
              onOk: async () => {
                await unbindSecret(workspace!.id, item.channel, item.secret_name);
                message.success('已解绑');
                await refresh();
              },
            })
          }
        >
          解绑
        </Button>
      ),
    },
  ];

  return (
    <PageContainer
      title="密钥管理"
      subTitle="Agent 运行时要用的凭证，密文入库、按通道绑定、可轮换可回滚"
      extra={[
        <Button key="refresh" icon={<ReloadOutlined />} onClick={() => void refresh()}>
          刷新
        </Button>,
        <Button key="model" onClick={() => setModelOpen(true)}>
          配置默认模型
        </Button>,
        <Button
          key="create"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setCreateOpen(true)}
        >
          新增密钥
        </Button>,
      ]}
    >
      <Row gutter={16}>
        <Col span={24}>
          <Card
            title="默认模型配置"
            size="small"
            style={{ marginBottom: 16 }}
            extra={
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                工作区级兜底，所有 Agent 自动获得；单个 Agent 可覆盖
              </Typography.Text>
            }
          >
            {modelBindings.length === 0 ? (
              <Empty
                image={null}
                description="还没配置默认模型。不配的话，Agent 要自己声明并绑定模型密钥。"
              />
            ) : (
              <Row gutter={16}>
                {modelByChannel.map(({ channel, values }) => (
                  <Col key={channel} span={8}>
                    <div style={{ fontWeight: 600, marginBottom: 8 }}>
                      <Tag>{channel.toUpperCase()}</Tag>
                    </div>
                    {MODEL_KEYS.map((key) => (
                      <div key={key} style={{ marginBottom: 4, fontSize: 13 }}>
                        <Typography.Text type="secondary">{key}</Typography.Text>
                        {': '}
                        {values[key] ? (
                          <Typography.Text code>
                            {values[key]?.fingerprint}
                          </Typography.Text>
                        ) : (
                          <Typography.Text type="secondary">未配置</Typography.Text>
                        )}
                      </div>
                    ))}
                  </Col>
                ))}
              </Row>
            )}
          </Card>
        </Col>

        <Col span={24}>
          <Card title="非模型密钥的默认绑定" size="small" style={{ marginBottom: 16 }}>
            {otherBindings.length === 0 ? (
              <Empty image={null} description="还没有非模型密钥的默认绑定" />
            ) : (
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={otherBindings}
                columns={bindingColumns}
              />
            )}
          </Card>
        </Col>

        <Col span={24}>
          <Card title="密钥库" size="small">
            <Table
              rowKey="id"
              loading={loading}
              dataSource={secrets}
              columns={columns}
              pagination={{ pageSize: 10 }}
            />
          </Card>
        </Col>
      </Row>

      {/* 新增密钥 */}
      <Modal
        title="新增密钥"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={async () => {
          const values = await createForm.validateFields();
          try {
            await putSecret(workspace!.id, values);
            message.success('已保存。明文不会再显示第二次——请确认已妥善保存。');
            setCreateOpen(false);
            createForm.resetFields();
            await refresh();
          } catch {
            /* 已提示 */
          }
        }}
      >
        <Form form={createForm} layout="vertical" requiredMark={false}>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入名称' }]}
            extra="Agent 的 spec 里用这个名字引用它，例如 mcp_github_token"
          >
            <Input placeholder="mcp_github_token" />
          </Form.Item>
          <Form.Item
            name="value"
            label="值"
            rules={[{ required: true, message: '请输入密钥值' }]}
            extra="加密后入库，任何接口都不会再返回明文"
          >
            <Input.Password placeholder="sk-..." autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input placeholder="用途备注（可选）" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 默认模型配置 */}
      <Modal
        title="配置工作区默认模型"
        open={modelOpen}
        width={560}
        onCancel={() => setModelOpen(false)}
        onOk={async () => {
          const values = await modelForm.validateFields();
          try {
            const result = await setModelConfig(workspace!.id, values);
            message.success(
              result.bound.length
                ? `已绑定 ${result.bound.length} 项（TEST 与 LIVE 各一份）`
                : '没有填写任何项，未做改动',
            );
            setModelOpen(false);
            modelForm.resetFields();
            await refresh();
          } catch {
            /* 已提示 */
          }
        }}
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
          这是**工作区级兜底**：所有 Agent 不声明也能拿到。TEST 与 LIVE 会各绑一份，
          所以两边可以指向不同的模型。填了的项才会被绑定，留空不动。
        </Typography.Paragraph>
        <Form form={modelForm} layout="vertical" requiredMark={false}>
          <Form.Item
            name="base_url"
            label="BASE_URL"
            extra="Anthropic 兼容端点，例如 http://216.167.7.16:8080"
          >
            <Input placeholder="http://216.167.7.16:8080" />
          </Form.Item>
          <Form.Item name="auth_token" label="AUTH_TOKEN" extra="加密存储，不再回显">
            <Input.Password placeholder="sk-..." autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="model_name" label="MODEL" extra="模型名，例如 grok-4.5">
            <Input placeholder="grok-4.5" />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}
