# Eval Loom 运行时与部署

> 配套：[backend-architecture.md](backend-architecture.md)（模块边界）、[backend-contracts.md](backend-contracts.md)（契约形状）。
> 本文只回答两件事：**这份代码怎么从本地单机迁到 k8s 而不用改业务代码**，
> 以及**命令/事件的消费队列到底怎么实现**。

---

## 1. 迁移契约：什么允许变，什么不允许

| 层 | 迁到 k8s 时 | 说明 |
| --- | --- | --- |
| `domain/` | **不变** | 纯 Python，本来就不碰 IO |
| `application/` | **不变** | 只依赖 `contracts/` 的 Port |
| `contracts/` | **不变** | 契约是跨模块边界，与部署形态无关 |
| `infrastructure/` | **换实现** | 本地 FS → S3、SQLite → PostgreSQL |
| `container.py` | **换绑定** | 按配置选 Adapter，唯一知道实现的地方 |
| `settings.py` | **换来源** | 全部走环境变量，不读配置文件 |

**验收方式**：迁移时如果 `domain/` 或 `application/` 需要改动，说明抽象漏了——那是 bug，不是部署问题。

---

## 2. 进程拓扑

同一份代码、四个入口，本地与 k8s 只是「怎么起」不同。

| 进程 | 本地 | k8s | 扩容依据 |
| --- | --- | --- | --- |
| `api_console` | uvicorn | Deployment + Service | CPU / RPS |
| `api_gateway` | uvicorn | Deployment + Service | QPS / P95 延迟 |
| `ingest` | uvicorn | Deployment + Service | 写入吞吐 |
| `worker` | `python -m backend.runtime.worker` | Deployment（**无 Service**） | 队列深度（KEDA） |
| `migrate` | `python -m backend.runtime.migrate` | Job / initContainer | 一次 |

**M0–M1 允许合并**：console 与 ingest 起在同一进程，worker 可以不起。四个入口的代码从第一天就分开，
所以拆分只是改 Deployment 数量，不改代码。

**无粘性会话需求**：会话是服务端状态（`identity_session` 表），任何 pod 都能处理任何请求，
不需要 Ingress 的 `sessionAffinity`。这是「会话存库」而非「会话存内存」换来的。

---

## 3. 配置面

全部来自环境变量（12-factor）。生产与开发的差异只有这张表：

| 变量 | 开发默认 | 生产 |
| --- | --- | --- |
| `EVAL_LOOM_ENV` | `development` | `production` |
| `EVAL_LOOM_DATABASE_URL` | `sqlite+aiosqlite:///.data/eval-loom/eval-loom.db` | `postgresql+asyncpg://...` |
| `EVAL_LOOM_MASTER_KEY` | 自动生成并落 `.data/eval-loom/.master-key` | **必须注入**，否则启动失败 |
| `EVAL_LOOM_DATA_DIR` | `.data/eval-loom` | 不依赖（对象存储接管） |
| `EVAL_LOOM_CORS_ORIGINS` | localhost 若干 | 控制台域名 |
| `RUNTIME_BACKEND` | `local` | `kubernetes` |

**禁止**：在代码里写死域名、路径、端口；从文件读密钥；依赖本地磁盘保存业务状态。

---

## 4. 启动与探针

| 探针 | 路径 | 检查什么 | 失败后果 |
| --- | --- | --- | --- |
| liveness | `GET /api/live` | 进程活着（不碰 DB） | 重启 pod |
| readiness | `GET /api/health` | **能连上 DB** | 摘掉流量，不重启 |

`/api/health` 同时返回 `contract_version`，方便灰度时确认新旧 pod 契约一致
（`CONTRACT_VERSION` 主版本不同时，消费者应拒绝启动）。

**迁移先于流量**：`migrate` Job 必须在 Deployment 滚动更新前成功。生产 `startup()` **不建表**
（`create_all()` 只在非生产调用），表结构只由 Alembic 负责。

---

## 5. 消费队列

### 5.1 为什么是事务性 Outbox，而不是直接上 MQ

核心写路径是「冻结快照 + 业务落库 + 入队」，**必须原子**：

```text
BEGIN
  INSERT run / trial / ...
  INSERT command_outbox        ← 同一个事务
COMMIT
```

外部 MQ 无法加入数据库事务，直接用它会出现两种不一致：
「消息发出去了但事务回滚」（下游处理了不存在的数据）、
「事务提交了但消息没发出去」（数据永远不被处理）。

所以：

```text
DB Outbox  = 唯一真相 + 状态机 + 去重源
外部 MQ    = 可选「派发优化」；DB 仍是真相
```

**什么时候才需要外部 MQ**：单表写入成为实测瓶颈（先看队列深度与 claim 延迟），
或需要跨系统扇出。届时加一个 dispatcher 把 outbox 行转发出去，
worker 从 MQ 消费但**仍以 DB 状态为准做去重**——业务代码不变。

### 5.2 两张表

```python
class CommandOutboxRow:          # platform_command_outbox —— 点对点、有状态
    id, workspace_id
    command_type                 # run.prepare / trial.execute / ...
    aggregate_type, aggregate_id
    idempotency_key  UNIQUE      # 重复投递不产生重复副作用
    payload  JSON
    status                       # pending | claimed | done | failed | dead
    attempts, max_attempts
    not_before                   # 退避：失败后推迟可见时间
    claimed_by, claimed_at, lease_expires_at
    last_error
    created_at, updated_at

class EventOutboxRow:            # platform_event_outbox —— 扇出、只追加
    id, workspace_id, tenant_id
    event_type, event_version
    aggregate_type, aggregate_id, sequence
    payload  JSON
    occurred_at, actor_kind, actor_id
    dispatched_at                # NULL = 待派发
```

命令与事件分开：命令是**有状态的**（谁领了、重试几次、成功了没），
事件是**事实**（写完就该被所有消费者看到，不需要租约）。

### 5.3 领取算法（跨 SQLite / PostgreSQL 可移植）

```sql
UPDATE platform_command_outbox
SET status = 'claimed', claimed_by = :worker, claimed_at = :now,
    lease_expires_at = :now + :lease, attempts = attempts + 1
WHERE id IN (
    SELECT id FROM platform_command_outbox
    WHERE status = 'pending' AND not_before <= :now
    ORDER BY created_at
    LIMIT :batch
    -- PostgreSQL 追加 FOR UPDATE SKIP LOCKED，避免多 worker 争抢
)
RETURNING *;
```

- SQLite：WAL 下 `UPDATE ... RETURNING`（SQLite ≥ 3.35）是原子的，够用。
- PostgreSQL：子查询加 `FOR UPDATE SKIP LOCKED`，多 worker 无锁等待。
- 两种方言共用同一段逻辑，只有子查询的一行不同——`SqliteCommandQueue` / `PostgresCommandQueue`。

### 5.4 投递语义（必须写进 handler 的约定）

| 语义 | 取值 | 含义 |
| --- | --- | --- |
| 投递 | **at-least-once** | 会重复，handler 必须幂等 |
| 幂等键 | `idempotency_key` | 同一键重复领取只产生一次副作用 |
| 顺序 | 单 `aggregate_id` 内按 `sequence` | 不保证全局有序 |
| 租约 | 默认 60s，需续期 | 到期未续期视为 worker 崩溃，命令回到可领取 |
| 重试 | 指数退避 `base * 2**attempts`，上限 `not_before` 封顶 | |
| 死信 | `attempts >= max_attempts` → `dead` | 不自动丢弃，需人工介入或显式重放 |
| 优雅停机 | 停止领取 → 跑完在途 → 释放租约 | 不丢命令 |

**幂等的两种实现**（按场景选）：
1. **聚合自身状态**：`trial.execute` 先查 `(run_id, sample_id, attempt_no)` 是否已有 Trial，有则直接返回。
2. **处理标记表**：`processed_command(idempotency_key, processed_at)`，适用于没有天然幂等键的副作用。

### 5.5 事件派发

`UnitOfWork.append(event)` 把事件写进 `platform_event_outbox`（同事务）。
派发器轮询 `dispatched_at IS NULL` 的行，交给订阅者，成功后打时间戳。

P0 用进程内订阅者即可；跨进程时同一张表由 worker 的派发循环处理。
若将来需要「每个消费者各自进度」，加一张 `platform_event_delivery(event_id, consumer, delivered_at)`，
而不是给事件表加列——事件的写入方不该知道有多少消费者。

---

## 6. 迁移检查单

迁到 k8s 时逐条打勾，**任何一条需要改 `domain/` 或 `application/` 都说明抽象漏了**：

- [ ] `EVAL_LOOM_DATABASE_URL` 指向 PostgreSQL（新增 `asyncpg` 依赖）
- [ ] `EVAL_LOOM_MASTER_KEY` 来自 Secret，生产启动时校验存在
- [ ] 对象存储从本地 FS 换成 S3 兼容实现（`ObjectStorePort`）
- [ ] `EVAL_LOOM_CORS_ORIGINS` 指向控制台域名
- [ ] `migrate` Job 在滚动更新前跑完 `alembic upgrade head`
- [ ] readiness 探针打 `/api/health`，liveness 打 `/api/live`
- [ ] 日志输出结构化 JSON 到 stdout（由 `EVAL_LOOM_LOG_FORMAT=json` 控制）
- [ ] worker 用队列深度扩容；确认租约时长 > 单条命令最长执行时间
