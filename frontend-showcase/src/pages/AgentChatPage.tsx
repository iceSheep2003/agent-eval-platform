import { RobotOutlined, UserOutlined } from '@ant-design/icons';
import { Bubble, Sender, XProvider } from '@ant-design/x';
import type { BubbleItemType, BubbleListProps } from '@ant-design/x/es/bubble/interface';
import XMarkdown from '@ant-design/x-markdown';
import { OpenAIChatProvider, useXChat, XRequest } from '@ant-design/x-sdk';
import { Alert, Avatar, Breadcrumb, Segmented, Space, Spin, Tag, Typography } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  chatUrl,
  getAgent,
  getHub,
  type ChannelValue,
  type PortalAgent,
  type PortalHub,
} from '../api/portal';
import { CHANNEL_COLOR } from '../theme';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

const roleConfig: BubbleListProps['role'] = {
  user: { placement: 'end', avatar: <Avatar icon={<UserOutlined />} /> },
  assistant: {
    placement: 'start',
    avatar: <Avatar style={{ background: '#4f7cff' }} icon={<RobotOutlined />} />,
    contentRender: (content: unknown) => (
      <XMarkdown>{typeof content === 'string' ? content : ''}</XMarkdown>
    ),
  },
};

export default function AgentChatPage() {
  const { hubId = '', agentId = '' } = useParams();
  const [hub, setHub] = useState<PortalHub | null>(null);
  const [agent, setAgent] = useState<PortalAgent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [channel, setChannel] = useState<ChannelValue>('live');
  const [input, setInput] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([getHub(hubId), getAgent(hubId, agentId)])
      .then(([nextHub, nextAgent]) => {
        if (cancelled) return;
        setHub(nextHub);
        setAgent(nextAgent);
        // 默认落在第一个已绑定的通道上，避免一进来就是「未绑定」的空态
        const firstBound = nextAgent.channels.find((item) => item.bound);
        setChannel(firstBound?.channel ?? nextAgent.channels[0]?.channel ?? 'live');
        setError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hubId, agentId]);

  const activeChannel = agent?.channels.find((item) => item.channel === channel);
  const bound = Boolean(activeChannel?.bound);

  const provider = useMemo(
    () =>
      new OpenAIChatProvider({
        request: XRequest(chatUrl(hubId, agentId, channel), {
          manual: true,
          credentials: 'include',
          params: { model: agentId, stream: true },
        }),
      }) as never,
    // 通道变了就换一个 provider——否则会把上一通道的上下文带过去
    [hubId, agentId, channel],
  );

  // Input 用 any：`OpenAIChatProvider` 要求把用户消息包在 `messages` 里传，
  // 而不是直接传一条 ChatMessage。
  const { onRequest, abort, isRequesting, messages } = useXChat<any, ChatMessage>({
    provider,
    conversationKey: `${agentId}:${channel}`,
    requestPlaceholder: { role: 'assistant', content: '' },
    requestFallback: (_params: unknown, info: { error: Error }) => ({
      role: 'assistant' as const,
      content: `调用失败：${info.error.message}`,
    }),
  });

  const bubbleItems = useMemo<BubbleItemType[]>(
    () =>
      messages.map((item) => ({
        key: item.id,
        role: item.message.role === 'user' ? 'user' : 'assistant',
        content: item.message.content,
        loading: item.status === 'loading',
      })),
    [messages],
  );

  if (loading) {
    return (
      <div className="center-screen">
        <Spin />
      </div>
    );
  }

  return (
    <div className="chat-page">
      <div className="chat-head">
        <div className="chat-head-left">
          <Breadcrumb
            items={[{ title: <Link to="/">{hub?.name ?? '门户'}</Link> }, { title: hub?.slug }]}
          />
          <Space align="center" size={10} style={{ marginTop: 6 }} wrap>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {agent?.display_name ?? 'Agent'}
            </Typography.Title>
            <Tag color={CHANNEL_COLOR[channel]}>{channel.toUpperCase()}</Tag>
            {activeChannel?.version_label && (
              <Typography.Text type="secondary">
                版本 {activeChannel.version_label}
              </Typography.Text>
            )}
          </Space>
        </div>
        <Segmented<ChannelValue>
          value={channel}
          onChange={setChannel}
          options={(agent?.channels ?? []).map((item) => ({
            label: (
              <span>
                {item.channel.toUpperCase()} · {item.label}
                {!item.bound && ' （未绑定）'}
              </span>
            ),
            value: item.channel,
          }))}
        />
      </div>

      {error && <Alert type="error" showIcon message={error} style={{ margin: '12px 0' }} />}
      {!bound && !error && (
        <Alert
          type="info"
          showIcon
          style={{ margin: '12px 0' }}
          message="该通道还没有绑定版本，暂时无法对话"
        />
      )}

      <XProvider>
        <div className="chat-body">
          <div className="chat-messages">
            {bubbleItems.length === 0 ? (
              <div className="chat-empty">
                <Typography.Text type="secondary">
                  向 {agent?.display_name} 发第一条消息试试
                </Typography.Text>
              </div>
            ) : (
              <Bubble.List items={bubbleItems} role={roleConfig} autoScroll />
            )}
          </div>
          <Sender
            value={input}
            onChange={setInput}
            loading={isRequesting}
            disabled={!bound}
            onSubmit={(text) => {
              if (!text.trim()) return;
              setInput('');
              onRequest({ messages: [{ role: 'user', content: text }] });
            }}
            onCancel={abort}
            placeholder={bound ? '输入消息，按 Enter 发送' : '该通道未绑定版本'}
            autoSize={{ minRows: 2, maxRows: 6 }}
          />
        </div>
      </XProvider>
    </div>
  );
}
