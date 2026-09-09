# Eval Loom 后端：进度与待办

> 设计见 [backend-architecture.md](backend-architecture.md)、[backend-contracts.md](backend-contracts.md)、[backend-runtime.md](backend-runtime.md)。
> 本文是**唯一**的进度与待办清单——新增待办写这里，不要散落在聊天记录里。

---

## 1. 里程碑状态

| 里程碑 | 内容 | 状态 |
| --- | --- | --- |
| **M0** | 骨架 + 认证 + 权限 + 队列基线 + Alembic | ✅ 完成（84 tests） |
| **M1** | SDK 上报闭环（asset + observability + ingest） | ✅ 完成 |
| **M2** | 数据集 + 评测策略 | ✅ 完成（模型见 [backend-dataset.md](backend-dataset.md)） |
| **M3** | 评测执行闭环（Run/Trial/Worker/评分/门禁） | ✅ 完成（82 tests） |
| **M4** | 证据回流 + 前端接真数据 | ✅ 完成（84 tests） |
| **M5** | 发布控制（P1） | ⬜ 未开始 |

**M1 拆分**：
- **M1a** — `asset` 模块 + 凭证签发 + 默认租户 + 控制台接口 ✅ **完成**
  （`register.py` 端到端跑通；`contracts/asset` 按 G2/G3 留到 M1b 再建）
- **M1b** — `observability` 模块 + `POST /v1/traces` + SDK 事件适配器 + Trace 查询 ✅ **完成**
  （`register.py` → 跑示例 Agent → 控制台查出 Span 树与指标，端到端跑通）

### M1 踩到的两个真坑（已在代码与测试里固化）

1. **SDK 对 `@observe` 的 Agent 不发 `trace_started`**——只有 `span_*` + `trace_finished`。
   适配器若拿它当起始时间来源，会退化成「平台接收时间」，出现 `ended_at < started_at`。
   现在起始时间取所有事件的最早值兜底。
2. **同一 trace 的事件可能被 `HttpSink.flush()` 分多批发出**——`span_started` 先到、
   `span_finished` 后到是常态。整条 trace 去重会让 span 永久缺失、根 span 卡在 `running`。
   现在上报是**事件级幂等 + 增量合并**（按 `external_span_id` 补新、更新旧）。

---

## 2. 待办

### P0（阻塞后续里程碑）

| # | 事项 | 为什么现在做 | 状态 |
| --- | --- | --- | --- |
| 1 | ~~**Alembic 迁移**~~ | — | ✅ 已完成 |
| 2 | `asyncpg` 依赖 | 切 PostgreSQL 时才需要，加进 `platform` extra | ⬜ |
| 3 | ~~`register.py` 改为 `json()["data"]["id"]`~~ | — | ✅ M1a 已改 |
| 4 | ~~前端 `dataField` + `errorCode` 改 `string`~~ | — | ✅ M4 已改（`dataField` 写在 `config/config.ts` 的插件配置里） |

### Alembic 的既定做法（已落地）

**单一 Alembic 环境 + 按模块 `branch_labels`**，而不是每个模块一套环境：

- 迁移目录 `backend/migrations/`，三个基线：`identity_0001` / `asset_0001` / `platform_0001`。
- 升级：`python -m backend.runtime.migrate`（k8s 的 Job / initContainer），
  或单模块 `alembic upgrade asset@head`。
- 生产 `Container.startup()` **不建表**，只校验 `alembic_version` 非空，否则拒绝启动。
- CI 检查 `tests/architecture/test_migration_ownership.py`：一个迁移只能操作自己模块前缀的表。

**新增迁移的做法**（务必照做，否则并行开发会撞车）：

```bash
# 1. 只让 autogenerate 看到本模块的表
ALEMBIC_MODULE=asset .venv/bin/python -m alembic -c backend/alembic.ini \
  revision --autogenerate -m "add xxx" --branch-label asset
# 2. 检查生成的文件只碰 asset_* 表，然后
.venv/bin/python -m backend.runtime.migrate asset@head
```

### P1 / 后续

| # | 事项 | 触发条件 |
| --- | --- | --- |
| 5 | `ObjectStorePort` + S3 适配器 | 迁 k8s 时（本地 FS 不共享） |
| 6 | OIDC 登录（`AuthProviderPort`） | 自建 IdP 就绪后 |
| 7 | 租户管理 UI 与同步接口 | M4 |
| 8 | 外部 MQ 派发器 | 队列深度成为实测瓶颈时 |

---

## 3. 已做出的决策（不要重新讨论）

| 决策 | 取值 | 理由 |
| --- | --- | --- |
| 契约层类型 | `dataclass(frozen=True, slots=True)`，不用 pydantic | 契约不依赖 pydantic；frozen 才是真不可变 |
| P0 模块数 | 目录 8 个，**只有 6 个有代码** | `improvement` 的回归样本并入 `dataset`；`delivery` 只留目录 |
| 契约生长 | 随消费方生长 + `test_no_unused_contracts` 强制 | 反对预冻结，见 `docs/backend-contracts.md` §14 |
| SDK 兼容 | 平台侧写适配器，**不改 SDK 事件形状** | SDK 已在跑；且 `asset_id`/`tenant_id` 只能从 `evk_` 反查，不信 body |
| 响应封装 | `{success, data}` + 前端 `dataField: 'data'` | 前端页面直接读 `result.items` |
| 数据集维度 | **四个正交维度**：origin / purpose / task_shape / stages | 需求说明 §12.3 指出「来源」与「任务形态」不能混在一个枚举里 |
| 数据集样本 | 三段式 `raw` / `task` / `private` | `private`（expected_output / hidden_state / verifier）永不进 Agent 输入 |
| 回流 | 草稿样本 → 复核 → **固化新版本**，带血缘与去重 | 已固化版本不可变（需求说明 §9.3） |
| 回流自动化 | **机器挖 + 人把关**（**P0 不实现**，设计见 backend-dataset.md §7） | 权限在 `Authorizer.MACHINE_FORBIDDEN` 里硬性收窄 |
| 回流标注 | LLM 起草 + 人工确认（**P0 不实现**） | 门禁判据必须有人背书 |
| 数据集 stages | **硬约束**：策略绑定时校验 `template.stage ∈ dataset.stages` | 防止宽松样本污染发布门禁 |
| 数据集混合 | 一个版本**允许**混合 `task_shape` / `protocol`，比较时分组下钻 | 强求同质会逼出「一个数据集拆成好几个」的伪需求 |
| 跨租户样本 | **可以直接共用** | 复用率高；代价是评测时注意样本来源 |
| 前端 | **`frontend-pro` 是唯一前端**，已并入本仓库（不再是嵌套 git 仓库）；旧 `frontend/` 已移除，其 6 份设计文档移至 `docs/legacy-frontend/` | 后端、SDK、控制台同一处，不再跨仓库同步 |
| 路径前缀 | `/api/*` 兼容面 + `/api/v1/*` 别名；`/v1/*` 机器面 | 前端与 `register.py` 已在用 `/api/*` |
| 队列 | 事务性 Outbox 先行，MQ 只作派发优化 | 业务写入与入队必须原子 |
| 探针 | `/api/live`（liveness，不碰 DB）+ `/api/health`（readiness，查 DB） | DB 抖动不该重启 pod |
| **Score 归属** | **execution**（表 `run_score`），不是 observability | Score 是 Trial 的产物，与 Run/Trial 同生命周期；拆开会造成写读两端来回穿模块边界 |

---

## 4. 已知偏离

| 项 | 文档写的 | 实际 | 处理 |
| --- | --- | --- | --- |
| 依赖 | 未列 | 新装 `sqlalchemy` / `aiosqlite` / `alembic` / `greenlet` / `argon2-cffi` | 已写入 `pyproject.toml` 的 `platform` extra |

---

## 5. 未决产品问题

见 [backend-architecture.md](backend-architecture.md) §18。其中影响架构的：
租户下线的数据处置、门禁是否要求「每个租户单独达标」、认证是否强制 SSO。
