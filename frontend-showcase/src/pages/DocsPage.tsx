import { FileTextOutlined, ReadOutlined } from '@ant-design/icons';
import XMarkdown from '@ant-design/x-markdown';
import { Card, Empty, Typography } from 'antd';
import { Link, useParams } from 'react-router-dom';
import { DOCS, findDoc, groupDocs } from '../docs';

function DocList() {
  const groups = groupDocs();
  return (
    <div className="page">
      <Typography.Title level={4} style={{ marginBottom: 4 }}>
        使用文档
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        Agent 接入前先看这里。列出的规则都是**平台会强制检查**的，不是建议。
      </Typography.Paragraph>

      {groups.map((group) => (
        <section key={group.group} className="doc-group">
          <div className="doc-group-title">{group.group}</div>
          <div className="doc-list">
            {group.items.map((doc) => (
              <Link key={doc.slug} to={`/docs/${doc.slug}`} className="doc-link">
                <FileTextOutlined className="doc-icon" />
                <div className="doc-body">
                  <div className="doc-title">{doc.title}</div>
                  <div className="doc-summary">{doc.summary}</div>
                </div>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function DocDetail({ slug }: { slug: string }) {
  const doc = findDoc(slug);
  if (!doc) {
    return (
      <div className="page">
        <Empty description="文档不存在" />
        <Typography.Paragraph style={{ textAlign: 'center' }}>
          <Link to="/docs">返回文档目录</Link>
        </Typography.Paragraph>
      </div>
    );
  }

  // 同组内还有别的文档时，底部给出下一篇——比让人回目录再点一次顺手。
  const index = DOCS.findIndex((item) => item.slug === doc.slug);
  const next = DOCS[index + 1];

  return (
    <div className="page doc-page">
      <Link to="/docs" className="back-link">
        <ReadOutlined /> 使用文档
      </Link>
      <Card className="doc-card" variant="borderless">
        {/* `x-markdown-light` 是组件自带的浅色主题类，配色走它自己的 CSS 变量 */}
        <XMarkdown className="doc-markdown x-markdown-light">{doc.content}</XMarkdown>
      </Card>
      {next && (
        <div className="doc-next">
          <span>下一篇</span>
          <Link to={`/docs/${next.slug}`}>{next.title} →</Link>
        </div>
      )}
    </div>
  );
}

export default function DocsPage() {
  const { slug } = useParams();
  return slug ? <DocDetail slug={slug} /> : <DocList />;
}
