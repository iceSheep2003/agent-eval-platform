import {
  ApiOutlined,
  DeploymentUnitOutlined,
  ReadOutlined,
  RobotOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import XMarkdown from '@ant-design/x-markdown';
import '@ant-design/x-markdown/es/XMarkdown/index.css';
import '@ant-design/x-markdown/themes/light.css';
import { PageContainer } from '@ant-design/pro-components';
import { useNavigate, useParams } from '@umijs/max';
import { Anchor, Card, Menu, Tag } from 'antd';
import type { MenuProps } from 'antd';
import { useEffect, useMemo, useRef } from 'react';
import type { ReactNode } from 'react';
import agentDevelopmentGuide from '@root/docs/agent-development-guide.md';
import agentLifecycle from '@root/docs/agent-lifecycle.md';
import aiGeneration from '@root/docs/ai-generation.md';
import capabilityAssets from '@root/docs/capability-assets.md';
import gettingStarted from '@root/docs/getting-started.md';
import styles from './style.module.css';

type DocEntry = {
  slug: string;
  title: string;
  summary: string;
  group: '入门' | '开发规范' | '能力与运行';
  icon: ReactNode;
  content: string;
};

type TocItem = {
  key: string;
  href: string;
  title: string;
  children?: TocItem[];
};

export const DOCS: DocEntry[] = [
  {
    slug: 'getting-started',
    title: '快速开始',
    summary: '从任务定义到首次上传',
    group: '入门',
    icon: <ThunderboltOutlined />,
    content: gettingStarted,
  },
  {
    slug: 'ai-generation',
    title: '让 AI 生成 Agent',
    summary: '可复制的生成任务书与拒收条件',
    group: '入门',
    icon: <RobotOutlined />,
    content: aiGeneration,
  },
  {
    slug: 'agent-development',
    title: '完整开发规范',
    summary: '代码、配置、能力、测试和准入要求',
    group: '开发规范',
    icon: <ReadOutlined />,
    content: agentDevelopmentGuide,
  },
  {
    slug: 'capability-assets',
    title: '能力资产配置',
    summary: 'Skill、MCP 与知识库的装配方式',
    group: '能力与运行',
    icon: <ApiOutlined />,
    content: capabilityAssets,
  },
  {
    slug: 'agent-lifecycle',
    title: '运行与发布生命周期',
    summary: '单次调用、TEST、LIVESH 与 LIVE',
    group: '能力与运行',
    icon: <DeploymentUnitOutlined />,
    content: agentLifecycle,
  },
];

export const findDoc = (slug: string | undefined) =>
  DOCS.find((item) => item.slug === slug);

const plainHeading = (value: string) =>
  value
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)]\([^)]*\)/g, '$1')
    .replace(/[*_~]/g, '')
    .trim();

function createToc(markdown: string): TocItem[] {
  const roots: TocItem[] = [];
  const lists = new Map<number, TocItem[]>();
  lists.set(1, roots);
  let index = 0;

  for (const match of markdown.matchAll(/^(#{2,4})\s+(.+)$/gm)) {
    const level = match[1].length;
    const item: TocItem = {
      key: `doc-heading-${index}`,
      href: `#doc-heading-${index}`,
      title: plainHeading(match[2]),
      children: [],
    };
    index += 1;
    (lists.get(level - 1) ?? roots).push(item);
    lists.set(level, item.children as TocItem[]);
    for (let deeper = level + 1; deeper <= 4; deeper += 1) lists.delete(deeper);
  }

  const prune = (items: TocItem[]): TocItem[] =>
    items.map((item) => ({
      ...item,
      children: item.children?.length ? prune(item.children) : undefined,
    }));
  return prune(roots);
}

const menuItems: MenuProps['items'] = (
  ['入门', '开发规范', '能力与运行'] as const
).map((group) => ({
  key: group,
  type: 'group',
  label: group,
  children: DOCS.filter((doc) => doc.group === group).map((doc) => ({
    key: doc.slug,
    icon: doc.icon,
    label: (
      <div className={styles.docLabel}>
        <strong>{doc.title}</strong>
        <span>{doc.summary}</span>
      </div>
    ),
  })),
}));

export default function DocsPage() {
  const { slug } = useParams<{ slug?: string }>();
  const navigate = useNavigate();
  const contentRef = useRef<HTMLDivElement>(null);
  const doc = findDoc(slug) ?? DOCS[0];
  const toc = useMemo(() => createToc(doc.content), [doc.content]);

  useEffect(() => {
    contentRef.current
      ?.querySelectorAll('h2, h3, h4')
      .forEach((heading, index) => {
        heading.id = `doc-heading-${index}`;
        heading.classList.add(styles.headingAnchor);
      });
    window.scrollTo({ top: 0, behavior: 'auto' });
  }, [doc.slug]);

  return (
    <PageContainer
      title="开发文档"
      subTitle="从接入协议到生产发布的一站式 Agent 工程手册"
      header={{ breadcrumb: {} }}
    >
      <div className={styles.workspace}>
        <aside className={styles.library} aria-label="文档列表">
          <div className={styles.libraryHeader}>
            <span>DOCUMENT LIBRARY</span>
            <strong>Agent 工程手册</strong>
            <small>{DOCS.length} 篇文档 · 持续维护</small>
          </div>
          <Menu
            className={styles.docMenu}
            mode="inline"
            items={menuItems}
            selectedKeys={[doc.slug]}
            onClick={({ key }) => navigate(`/docs/${key}`)}
          />
        </aside>

        <main className={styles.main}>
          <nav className={styles.mobileLibrary} aria-label="文档列表">
            {DOCS.map((item) => (
              <button
                type="button"
                key={item.slug}
                className={item.slug === doc.slug ? styles.mobileActive : undefined}
                onClick={() => navigate(`/docs/${item.slug}`)}
              >
                {item.title}
              </button>
            ))}
          </nav>
          <Card className={styles.documentCard} variant="borderless">
            <div className={styles.documentMeta}>
              <Tag color="blue">{doc.group}</Tag>
              <span>{doc.summary}</span>
            </div>
            <article ref={contentRef} className={styles.markdown}>
              <XMarkdown openLinksInNewTab>{doc.content}</XMarkdown>
            </article>
          </Card>
        </main>

        <aside className={styles.toc} aria-label="本页目录">
          <div className={styles.tocInner}>
            <span className={styles.tocTitle}>本页目录</span>
            {toc.length ? (
              <Anchor items={toc} offsetTop={88} targetOffset={88} />
            ) : (
              <span className={styles.tocEmpty}>本页暂无章节</span>
            )}
          </div>
        </aside>
      </div>
    </PageContainer>
  );
}
