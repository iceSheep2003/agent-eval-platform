# 数据集模型设计

> 配套：[backend-architecture.md](backend-architecture.md)（模块边界）、[backend-contracts.md](backend-contracts.md)（契约形状）。
> 本文回答：**数据集的选型、划分与回流到底怎么建模**，以及为什么不能只有 `{input, expected_output}`。

---

## 1. 为什么 `{input, expected_output}` 不够

需求说明 §5.7 把数据集分成四类业务形态，§12.3 又指出这个分类**混合了不同维度**
（benchmark / 回归 / 生产 Trace 描述的是来源或用途，agentic 描述的是任务结构）。
如果只用一层 `kind` 表达，会出现三种立刻卡住的情况：

| 场景 | 只有一层 kind 时的问题 |
| --- | --- |
| tau-bench 的一批样本 | 它是 benchmark，也是 agentic，也可能是回归集——一个字段装不下 |
| 生产失败 Trace 沉淀成回归样本 | 来源是 production_trace，用途是 regression，任务形态可能是 single_turn |
| 同一个回归集同时用于「持续回归」和「发布门禁」 | 生命周期阶段无法表达 |

所以数据集需要**四个正交维度**，而不是一个枚举。

---

## 2. 四个正交维度

```python
class DatasetOrigin(StrEnum):
    """样本从哪来 —— 决定校验方式、血缘与合规要求。"""
    BENCHMARK = "benchmark"                # 外部标准评测集，需要适配
    MANUAL = "manual"                      # 人工编写
    PRODUCTION_TRACE = "production_trace"  # 生产流量筛选沉淀
    AGENT_FEEDBACK = "agent_feedback"      # Agent 执行中发现缺口后上报
    DEFECT = "defect"                      # 历史缺陷复现


class DatasetPurpose(StrEnum):
    """拿来回答什么质量问题 —— 决定能绑哪些策略、门禁怎么解读。"""
    CAPABILITY = "capability"   # 能力验证：这个能力行不行
    REGRESSION = "regression"   # 回归防退化：以前修好的还坏没坏
    GATE = "gate"               # 发布门禁：能不能上生产
    MONITORING = "monitoring"   # 生产监控：线上有没有变差


class TaskShape(StrEnum):
    SINGLE_TURN = "single_turn"
    MULTI_TURN = "multi_turn"
    AGENTIC = "agentic"
```

第四个维度是**适用阶段**（`EvaluationStage`，已在 `contracts/common.py`）——
一个数据集可以在多个阶段被引用，所以是集合而不是单值：

```python
class Dataset:
    id: Id
    workspace_id: Id
    name: str
    origin: DatasetOrigin
    purpose: DatasetPurpose
    task_shape: TaskShape
    stages: tuple[EvaluationStage, ...]   # 允许在哪些生命周期阶段被引用
    protocol: str                          # 见 §3
    source: DatasetSource | None           # 见 §4，benchmark 时必填
    description: str
    owner_id: Id
```

**用途 ↔ 阶段的默认映射**（可在创建时覆盖，不是硬约束）：

| purpose | 默认 stages | 说明 |
| --- | --- | --- |
| `capability` | development | 快速试验，样本可少、门槛可松 |
| `regression` | regression、release | 持续回归跑，发布门禁也跑 |
| `gate` | release | 只服务发布门禁，样本必须带明确判定依据 |
| `monitoring` | production | 生产抽样，用于发现退化 |

> 策略绑定时校验：`EvaluationTemplate.stage ∈ dataset.stages`。不匹配就拒绝绑定——
> 避免把「只用于开发验证的宽松样本」绑到发布门禁上。

---

## 3. 评测协议：样本怎么被执行

不同 benchmark 的执行方式完全不同，样本必须**声明自己需要哪种执行协议**：

```python
class TaskProtocol(StrEnum):
    QA = "qa/v1"                      # 单轮：给输入，要输出
    TOOL_LOOP = "tool-loop/v1"        # 多轮工具循环：Agent 反复调工具直到收敛
    AGENTIC = "agentic-bench/v1"      # 环境型：observation / action 循环 + 隐藏 verifier
```

- `QA` / `TOOL_LOOP` 由 `execution` 的通用循环执行（M3）。
- `AGENTIC` 需要环境生命周期（setup / reset / step / finish），属于 Harness 的范畴
  （架构文档 §9）。P0 只**建模**、不实现，M3 先用 `QA` 打通闭环。

`protocol` 是样本的固有属性，不是策略的属性——同一个数据集里的样本可以混合协议，
但按当前设计建议一个数据集版本内保持一致，便于比较。

---

## 4. Benchmark 适配

**不要重新实现 benchmark**。已有的适配工作（各 benchmark 的 dataset / environment / verifier）
应该被**引用**，而不是被平台重写。数据集只负责回答「这批样本是哪来的、怎么转成平台能跑的」。

```python
class DatasetSource:
    """来源与适配信息。benchmark 数据集必须能回答「原始是哪一版、用哪个适配器」。"""
    origin: DatasetOrigin
    benchmark_id: str | None        # "tau2"
    benchmark_version: str | None   # "3.0.0"
    adapter: str | None             # "agent_eval_benchmarks.tau2:Adapter"
    adapter_version: str | None     # "0.1.0"
    split: str | None               # "validation"
    upstream_uri: str | None        # 原始数据出处，便于审计与再导入
    license: str | None
```

**三条规则**

1. **保真**：导入时把原始样本原样存进 `item.raw`。适配器升级后可以重新 materialize，
   不需要重新下载数据，也不会因为上游变更丢失历史。
2. **可追溯**：`DatasetSource` 记录 benchmark 版本 + 适配器版本。
   同一批数据换了适配器 = 新的数据集版本，不是原地修改。
3. **不隐藏**：适配器把原始样本转成平台格式，但**不参与判分**。
   判分逻辑属于 verifier，其实现可以隐藏在 private 段（§5）。

---

## 5. 样本三段式

```python
class DatasetItem:
    id: Id
    dataset_version_id: Id
    tenant_id: Id | None      # 生产 Trace 回流时继承来源租户
    index: int

    # 1) 保真原始样本 —— 用于重放、再适配、审计
    raw: JsonObject

    # 2) 公开部分 —— 唯一允许进入 Agent 输入的内容
    task: TaskSpec

    # 3) 私有部分 —— 只给评估器 / verifier，永不进入 Agent 输入
    private: PrivateTaskContext | None

    lineage: SampleLineage     # 见 §6
    review: ReviewState        # 见 §6
```

```python
class TaskSpec:
    protocol: TaskProtocol
    instruction: str
    context: Mapping[str, JsonValue] = {}     # 公开上下文
    tools: tuple[ToolSpec, ...] = ()          # 允许调用的工具与 schema
    limits: TaskLimits | None = None          # max_steps / timeout / budget


class PrivateTaskContext:
    expected_output: JsonValue | None
    expected_actions: tuple[ExpectedAction, ...] = ()
    hidden_state: Mapping[str, JsonValue] = {}   # 环境型任务的隐藏状态
    verifier: str | None                          # "module:callable"
```

**核心不变量**（M3 要用契约测试断言）：

> `expected_output`、`hidden_state`、`verifier` **永远不出现在发给 Agent 的 payload 里**。
> 类型系统区分不了这件事，只能靠执行路径保证——所以它必须是一条被测试覆盖的硬约束。

单轮问答就是退化情形：`task.instruction` 是输入，`private.expected_output` 是期望。
生产 Trace 回流的样本通常**没有** `expected_output`，必须人工补（§6）。

---

## 6. 回流设计

回流不是「复制一条 Trace」，而是**把生产/评测中发现的问题沉淀成可复跑的回归资产**。
四类来源（需求说明 §5.14）：Agent 自报、监控告警、人工反馈、失败 Trial。

### 6.1 血缘

```python
class SampleLineage:
    origin: DatasetOrigin
    source_trace_id: Id | None            # 生产或评测 Trace
    source_run_id: Id | None              # 评测 Trial 所属 Run
    source_proposal_id: Id | None         # 改进提案
    source_dataset_version_id: Id | None  # 从哪个版本派生
    reason: str | None                    # 为什么加进来（人话，用于复盘）
    added_by: str
    added_at: datetime
```

每条回流样本都要能回答「**它为什么在这里**」。没有 `reason` 的样本，
三个月后没人敢删也没人知道它测什么。

### 6.2 复核

```python
class ReviewState:
    status: Literal["pending", "approved", "rejected"]
    reviewer_id: Id | None
    reviewed_at: datetime | None
    note: str | None
```

流程固定为：

```text
生产 Trace / 失败 Trial / 提案
  → 脱敏
  → 追加为「数据集草稿样本」（review.status = pending）
  → 人工补 expected_output 或标注判分依据
  → 复核（approved / rejected）
  → 固化为新的数据集版本
```

**绝不允许原地修改已固化的版本**（需求说明 §9.3）。回流永远产生新版本。

### 6.3 去重与幂等

同一来源反复回流必须去重，否则回归集会迅速膨胀且失去意义：

- 按 `(dataset_id, source_trace_id)` 唯一——同一条 Trace 只沉淀一次
- 按 `(dataset_id, content_digest)` 唯一——内容相同但来源不同的样本合并

### 6.4 回流闭环的度量

回流本身要能被衡量，否则「持续改进」只是口号：

| 指标 | 含义 |
| --- | --- |
| `regression_samples_added` | 某个数据集版本新增了多少回归样本 |
| `trace_to_sample_rate` | 生产失败 Trace 中被沉淀为样本的比例 |
| `sample_recurrence_rate` | 已沉淀样本在后续评测中再次失败的比例（说明修复无效） |
| `proposal_acceptance_rate` | 提案被接受的比例 |

前三个是「问题有没有真正闭环」的直接证据。

### 6.5 租户边界

生产 Trace 带 `tenant_id`，回流样本**继承该租户**。跨租户使用需要显式确认——
否则 A 租户的失败案例会被拿去评测服务 B 租户的 Agent，既是数据泄露也是错配。

---

## 7. 与策略、门禁、版本比较的关系

```text
DatasetVersion  ──被引用──→  EvaluationTemplate  ──冻结快照──→  Run
     │                            │                              │
  不可变                         stage ∈ dataset.stages          Trial → Trace → Score
     │                                                            │
     └────────── 回流：失败 Trial → 新样本 → 新 DatasetVersion ────┘
```

- **策略绑定**：`EvaluationTemplate` 引用 `dataset_version_id`（明确版本，不是「当前数据集」）。
- **门禁**：`GateRule` 的阈值作用在**某个数据集版本**的结果上；换版本就是换了一把尺子，
  不能拿新版本的分数和旧版本比较。
- **版本比较**：需求说明 §16.6 要求「相同数据集版本、相同策略、相同评分口径」。
  数据集版本是三个锚点之一，缺了它分数变化无法归因。

---

## 8. P0 落地范围

**做**：
- 四个维度的建模与校验（origin / purpose / task_shape / stages）
- `TaskSpec` / `PrivateTaskContext` 三段式，含「private 不进 Agent 输入」的契约测试
- 导入预检：识别 `input` / `expected_output` / 重复项 / 无效样本
- 回流：从 Trace 或失败 Trial 追加草稿样本 → 复核 → 固化新版本，含血缘与去重
- `QA` 协议

**不做（M3 之后）**：
- `AGENTIC` 协议的完整环境生命周期（属 Harness）
- 自动适配器执行（P0 只记录 `DatasetSource`，导入走文件）
- 自动回流（Agent 自报 / 监控触发）——P0 走人工确认

---

## 9. 待确认的产品口径

1. **一个数据集能否混合 `task_shape`？** 当前设计建议一个版本内保持一致，便于比较。
2. **`stages` 是硬约束还是建议？** 当前按硬约束实现（策略绑定校验），
   如果希望宽松，改成只告警即可。
3. **回流样本的 `expected_output` 由谁补？** 当前默认人工；
   是否允许 LLM 起草 + 人工确认，需要产品定。
4. **跨租户样本能否共用？** 当前默认不能，需要显式确认。
