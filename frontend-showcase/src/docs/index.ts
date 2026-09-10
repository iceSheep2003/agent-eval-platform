import agentRequirements from './agent-requirements.md?raw';

/**
 * 文档清单。**新增文档只需在这里加一行**——路由、导航、目录页都自动带上。
 *
 * 正文用 `?raw` 在构建时内联，不打接口也不依赖后端——文档是产品的一部分，
 * 不该因为后端挂了就看不到。
 */
export interface DocEntry {
  slug: string;
  title: string;
  summary: string;
  /** 分组标题。后续文档变多时按组折叠。 */
  group: string;
  content: string;
}

export const DOCS: DocEntry[] = [
  {
    slug: 'agent-requirements',
    title: 'Agent 代码实现与上传要求',
    summary: '入口签名、记忆、密钥、三条硬性禁止，以及上传前自查',
    group: '接入指南',
    content: agentRequirements,
  },
];

export function findDoc(slug: string | undefined): DocEntry | undefined {
  return DOCS.find((item) => item.slug === slug);
}

/** 按 `group` 归拢，保持清单里的先后顺序。 */
export function groupDocs(): Array<{ group: string; items: DocEntry[] }> {
  const groups: Array<{ group: string; items: DocEntry[] }> = [];
  for (const doc of DOCS) {
    const last = groups[groups.length - 1];
    if (last && last.group === doc.group) {
      last.items.push(doc);
    } else {
      groups.push({ group: doc.group, items: [doc] });
    }
  }
  return groups;
}
