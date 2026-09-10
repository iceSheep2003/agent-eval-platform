import { LockOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons';
import { LoginForm, ProFormText } from '@ant-design/pro-components';
import { history, useModel } from '@umijs/max';
import { Alert, App, Typography } from 'antd';
import { useState } from 'react';
import { login } from '@/services/eval';
import styles from './style.module.css';

type LoginValues = { identifier: string; password: string };

export default function LoginPage() {
  const { message } = App.useApp();
  const { setInitialState } = useModel('@@initialState');
  const [error, setError] = useState('');

  const submit = async ({ identifier, password }: LoginValues) => {
    setError('');
    try {
      const session = await login(identifier, password);
      const preferred = localStorage.getItem('eval-workspace-id');
      const currentWorkspace = session.workspaces.find((item) => item.id === preferred) ?? session.workspaces[0];
      setInitialState((previous) => ({
        ...previous,
        currentUser: session.user,
        workspaces: session.workspaces,
        currentWorkspace,
      }));
      message.success('已进入评测工作区');
      const target = new URLSearchParams(window.location.search).get('redirect');
      history.replace(target?.startsWith('/') && !target.startsWith('//') ? target : '/overview');
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '账号或密码错误');
      return false;
    }
  };

  return (
    <main className={styles.page}>
      <section className={styles.story}>
        <div className={styles.brand}><span className={styles.mark}>EL</span><strong>EVAL LOOM</strong></div>
        <div className={styles.storyBody}>
          <span className={styles.kicker}>AGENT EVALUATION CONTROL PLANE</span>
          <h1>看见 Agent<br />每一次决策的代价。</h1>
          <p>在同一个工作区中固定版本、执行评测、追踪 Trace，并把失败样本变成下一轮回归测试。</p>
        </div>
        <div className={styles.signalGrid}>
          <div><span>运行轨迹</span><strong>Trace-first</strong></div>
          <div><span>租户边界</span><strong>Workspace</strong></div>
          <div><span>评测协议</span><strong>v0.1</strong></div>
        </div>
      </section>
      <section className={styles.formPanel}>
        <LoginForm<LoginValues>
          title="登录评测平台"
          subTitle="使用账号进入你有权限的工作区"
          onFinish={submit}
          submitter={{ searchConfig: { submitText: '进入工作区' }, submitButtonProps: { size: 'large', block: true } }}
        >
          {error && <Alert type="error" showIcon title={error} className={styles.alert} />}
          <ProFormText name="identifier" fieldProps={{ size: 'large', prefix: <UserOutlined />, autoComplete: 'username' }} placeholder="admin 或 admin@evalloom.local" rules={[{ required: true, message: '请输入账号' }]} />
          <ProFormText.Password name="password" fieldProps={{ size: 'large', prefix: <LockOutlined />, autoComplete: 'current-password' }} placeholder="输入密码" rules={[{ required: true, message: '请输入密码' }]} />
          <div className={styles.demo}>
            <SafetyCertificateOutlined />
            <Typography.Text type="secondary">演示账号：admin / admin123</Typography.Text>
          </div>
        </LoginForm>
      </section>
    </main>
  );
}
