# Agent 评测平台

面向个人研发与企业内部使用的智能体评测平台设计文档。

当前阶段先完成设计，不直接进入 Demo 编码。平台目标不是只给 Agent 一个最终答案打分，而是把一次 Agent 评测拆成可配置、可追踪、可审计、可复现的完整运行过程。

## 文档导航

- [产品与技术设计](docs/01-产品与技术设计.md)：产品定位、用户流程、模块边界与总体架构。
- [评测协议与 Agent 接入规范](docs/02-评测协议与Agent接入规范.md)：统一任务、动作、观测、评分、轨迹和 Agent 接入协议。
- [MVP 开发计划](docs/03-MVP开发计划.md)：第一版 Demo 的范围、页面、接口和验收标准。
- [生产级与企业级演进](docs/04-生产级与企业级演进.md)：高可用、安全、审计、权限、隔离、成本与部署路线。

## 核心判断

平台采用“控制面 + 执行面”的结构：

```text
控制面：Agent、Benchmark、评测维度、数据集、任务、权限、报告、审计
执行面：Agent Adapter、Benchmark Adapter、沙箱、Runner、Scorer、Trace
```

第一版不要求 Agent 修改内部实现。平台通过 Adapter 在 Agent 与 Benchmark 之间建立统一边界，统一表达：

```text
Task      要完成什么
Context   Agent 可以知道什么
Actions   Agent 可以做什么
Observation 环境返回什么
Score     任务最终如何判定
```

## 当前状态

- 设计阶段。
- 只使用 Markdown 文档，不生成 Word 文档。
- 文档评审通过后，再在本目录实现可运行 Demo。
