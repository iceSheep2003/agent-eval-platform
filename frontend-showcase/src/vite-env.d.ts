/// <reference types="vite/client" />

/** 文档正文用 `?raw` 在构建时内联，不打接口也不依赖后端。 */
declare module '*.md?raw' {
  const content: string;
  export default content;
}
