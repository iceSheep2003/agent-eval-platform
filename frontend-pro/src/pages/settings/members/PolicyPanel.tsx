/**
 * 治理策略编辑器。
 *
 * 通道是**状态**，晋级是**迁移**。这里编辑的是一份数据：
 * 每条迁移要过哪些检查、各自的阈值、需要什么权限、是否要二次确认。
 *
 * 表单由后端返回的检查 schema 驱动——新增检查项只改后端，这里自动多出对应输入框。
 */

import { ReloadOutlined, SaveOutlined } from '@ant-design/icons';
import {
  App,
  Button,
  Card,
  Checkbox,
  Empty,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Tag,
  Tooltip,
} from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { useWorkspace } from '@/hooks/useWorkspace';
import type {
  CheckSchema,
  LifecycleCheck,
  LifecyclePolicy,
  LifecycleTransition,
} from '@/services/eval/lifecycle';
import {
  getLifecycleChecks,
  getLifecyclePolicy,
  resetLifecyclePolicy,
  saveLifecyclePolicy,
} from '@/services/eval/lifecycle';

/** 可赋给迁移的权限点。新增权限点在这里补一行即可。 */
const PERMISSION_OPTIONS = [
  {
    value: 'version:promote:livesh',
    label: '晋级到影子（version:promote:livesh）',
  },
  {
    value: 'version:promote:live',
    label: '发布到生产（version:promote:live）',
  },
  { value: 'version:rollback', label: '生产回退（version:rollback）' },
  { value: 'gate:configure', label: '配置门禁（gate:configure）' },
];

const CHANNEL_LABEL: Record<string, string> = {
  test: 'TEST',
  liversh: 'LIVESH',
  live: 'LIVE',
};

export default function PolicyPanel() {
  const workspace = useWorkspace();
  const { message, modal } = App.useApp();
  const [policy, setPolicy] = useState<LifecyclePolicy>();
  const [schemas, setSchemas] = useState<CheckSchema[]>([]);
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [current, checks] = await Promise.all([
        getLifecyclePolicy(),
        getLifecycleChecks(),
      ]);
      setPolicy(current);
      setSchemas(checks.items);
      setDirty(false);
    } catch {
      setPolicy(undefined);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [workspace?.id]);

  const schemaOf = (name: string) => schemas.find((item) => item.name === name);

  /** 改一份深拷贝，`dirty` 时才好判断要不要保存。 */
  const mutate = (fn: (draft: LifecyclePolicy) => void) => {
    if (!policy) return;
    const draft: LifecyclePolicy = JSON.parse(JSON.stringify(policy));
    fn(draft);
    setPolicy(draft);
    setDirty(true);
  };

  const updateTransition = (
    index: number,
    patch: Partial<LifecycleTransition>,
  ) => mutate((draft) => Object.assign(draft.transitions[index], patch));

  const updateCheck = (
    transitionIndex: number,
    checkIndex: number,
    patch: Partial<LifecycleCheck>,
  ) =>
    mutate((draft) =>
      Object.assign(
        draft.transitions[transitionIndex].checks[checkIndex],
        patch,
      ),
    );

  const updateParam = (
    transitionIndex: number,
    checkIndex: number,
    key: string,
    value: unknown,
  ) =>
    mutate((draft) => {
      const params =
        draft.transitions[transitionIndex].checks[checkIndex].params;
      params[key] = value;
    });

  const submit = async () => {
    if (!policy) return;
    setSaving(true);
    try {
      const saved = await saveLifecyclePolicy(policy.transitions);
      setPolicy(saved);
      setDirty(false);
      message.success('治理策略已更新');
    } catch {
      // 失败提示由 requestErrorConfig 统一弹出
    } finally {
      setSaving(false);
    }
  };

  const reset = () => {
    modal.confirm({
      title: '恢复平台默认策略？',
      content: '本工作区的自定义配置会被清除，立即回到平台默认规则。',
      okText: '恢复默认',
      cancelText: '取消',
      onOk: async () => {
        const restored = await resetLifecyclePolicy();
        setPolicy(restored);
        setDirty(false);
        message.success('已恢复平台默认策略');
      },
    });
  };

  if (!policy) {
    return <Empty description={loading ? '加载中…' : '拿不到治理策略'} />;
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card size="small">
        <Space>
          <span style={{ color: '#64748b' }}>
            通道是状态，晋级是迁移。每条迁移声明要过哪些检查、阈值多少、谁能操作——
            改了立即生效，不用发版。
          </span>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => void refresh()}
            loading={loading}
          >
            重新加载
          </Button>
          <Button icon={<ReloadOutlined />} onClick={reset}>
            恢复平台默认
          </Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            disabled={!dirty}
            loading={saving}
            onClick={() => void submit()}
          >
            {dirty ? '保存修改' : '已保存'}
          </Button>
        </Space>
      </Card>

      {policy.transitions.map((transition, transitionIndex) => (
        <Card
          key={`${transition.from_channel}-${transition.to_channel}`}
          size="small"
          title={
            <Space>
              <Tag>
                {CHANNEL_LABEL[transition.from_channel] ??
                  transition.from_channel}
              </Tag>
              <span>→</span>
              <Tag color="blue">
                {CHANNEL_LABEL[transition.to_channel] ?? transition.to_channel}
              </Tag>
            </Space>
          }
        >
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Space size={24} wrap>
              <Space>
                <span>所需权限</span>
                <Select
                  style={{ width: 320 }}
                  value={transition.permission}
                  options={PERMISSION_OPTIONS}
                  onChange={(value) =>
                    updateTransition(transitionIndex, { permission: value })
                  }
                />
              </Space>
              <Space>
                <span>需要二次确认</span>
                <Switch
                  checked={transition.requires_reauth}
                  onChange={(checked) =>
                    updateTransition(transitionIndex, {
                      requires_reauth: checked,
                    })
                  }
                />
                <Tooltip title="高风险动作提交时会再校验一次；真正的 re-auth ticket 待 IdP 接入">
                  <span style={{ color: '#94a3b8' }}>?</span>
                </Tooltip>
              </Space>
            </Space>

            <div>
              <strong>检查项（按顺序执行，第一个不通过就停）</strong>
              <div style={{ marginTop: 8 }}>
                {transition.checks.map((check, checkIndex) => {
                  const schema = schemaOf(check.name);
                  return (
                    <div
                      key={check.name}
                      style={{
                        border: '1px solid #f0f0f0',
                        borderRadius: 8,
                        padding: '10px 12px',
                        marginBottom: 8,
                        opacity: check.enabled ? 1 : 0.5,
                      }}
                    >
                      <Space align="start" size={12} style={{ width: '100%' }}>
                        <Checkbox
                          checked={check.enabled}
                          onChange={(event) =>
                            updateCheck(transitionIndex, checkIndex, {
                              enabled: event.target.checked,
                            })
                          }
                        />
                        <div style={{ flex: 1 }}>
                          <div>
                            <strong>{check.name}</strong>
                            <span style={{ marginLeft: 8, color: '#64748b' }}>
                              {schema?.description}
                            </span>
                          </div>
                          {(schema?.params ?? []).length > 0 && (
                            <Space size={16} wrap style={{ marginTop: 8 }}>
                              {(schema?.params ?? []).map((param) => (
                                <Space key={param.key}>
                                  <span>{param.label}</span>
                                  {param.type === 'select' ? (
                                    <Select
                                      size="small"
                                      style={{ width: 140 }}
                                      value={
                                        (check.params[param.key] ??
                                          param.default) as string
                                      }
                                      options={param.options.map((option) => ({
                                        label: option,
                                        value: option,
                                      }))}
                                      onChange={(value) =>
                                        updateParam(
                                          transitionIndex,
                                          checkIndex,
                                          param.key,
                                          value,
                                        )
                                      }
                                    />
                                  ) : param.type === 'number' ? (
                                    <InputNumber
                                      size="small"
                                      style={{ width: 120 }}
                                      step={param.step ?? 1}
                                      value={
                                        (check.params[param.key] ??
                                          param.default) as number | null
                                      }
                                      onChange={(value) =>
                                        updateParam(
                                          transitionIndex,
                                          checkIndex,
                                          param.key,
                                          value,
                                        )
                                      }
                                    />
                                  ) : (
                                    <Input
                                      size="small"
                                      value={String(
                                        check.params[param.key] ??
                                          param.default ??
                                          '',
                                      )}
                                      onChange={(event) =>
                                        updateParam(
                                          transitionIndex,
                                          checkIndex,
                                          param.key,
                                          event.target.value,
                                        )
                                      }
                                    />
                                  )}
                                  {param.help && (
                                    <Tooltip title={param.help}>
                                      <span style={{ color: '#94a3b8' }}>
                                        ?
                                      </span>
                                    </Tooltip>
                                  )}
                                </Space>
                              ))}
                            </Space>
                          )}
                        </div>
                      </Space>
                    </div>
                  );
                })}
              </div>
            </div>
          </Space>
        </Card>
      ))}
    </Space>
  );
}
