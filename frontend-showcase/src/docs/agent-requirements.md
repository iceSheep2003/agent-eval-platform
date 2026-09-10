# Agent 代码实现与上传要求

这份文档列出**平台会强制检查**的规则。不是建议——不合规的版本**冻结不进去**，
或者会在验收接口上报错。

规则分两类：

- **静态规则**：冻结版本时就查，不合规直接拒绝；
- **运行时规则**：需要把代码真的加载进来看签名，通过验收接口
  `GET /api/agents/{id}/versions/{vid}/conformance` 查。

---

## 一、入口函数怎么写

平台按固定协议调用你的 Agent。入口必须是一个可导入的 callable：

```
entrypoint = "module.path:callable"
```

例：`examples.showcase_demo_agent:demo_support_agent`

### 必须接受的形参

| 形参 | 必须 | 说明 |
|---|---|---|
| `input` | ✅ | 公开输入。**名字必须叫 `input`**，改名字等于换协议 |
| `messages` | ✅（或 `**kwargs`） | 多轮对话上下文 |
| `secrets` | 可选 | 平台注入的密钥，见第四节 |
| `memory` | 可选 | 平台提供的记忆句柄，见第三节 |
| `capabilities` | 可选 | 引用的 Skill / MCP / 知识库配置 |

> 没声明某个形参，平台就不传它——**不会**因为多传参数把你的函数打挂。

### 最小可用示例

```python
def my_agent(input: str) -> str:
    return f"收到：{input}"
```

### 接多轮上下文

```python
async def my_agent(input: str, messages: list[dict] = None) -> str:
    history = messages or []
    # history 是完整历史（含本轮），最后一条就是 input
    return "..."
```

### 想要逐字输出？改成异步生成器

```python
async def my_agent(input: str):
    async for piece in model_stream(input):
        yield piece          # 每次 yield 一段，前端就会逐字显示
```

**普通函数也能用**——平台会把整段输出作为唯一一段发出去，不会报错。
只是没有逐字效果。

---

## 二、三条硬性禁止

### 1. 禁止把明文密钥写进配置

版本一旦冻结就**不可变**，明文密钥写进去就再也换不掉了。

```python
# ❌ 会被拒绝
{"mcp_servers": [{"authentication": {"api_key": "sk-live-xxx"}}]}
```

报错：`版本不可变，密钥必须写 secret_ref；明文一旦冻结就再也换不掉`

正确做法见第四节。

### 2. 禁止模块级可变状态

```python
# ❌ 会被拒绝
_cache = {}

def my_agent(input):
    global _cache
    _cache["last"] = input
    return input
```

报错：`模块级可变状态：_cache。编排会并发调用同一个 Agent，这种状态必然串味`

**为什么**：多 Agent 编排会**并发**调用同一个 Agent 的多个实例。这种隐式全局
状态会让不同会话互相看见——而且「单跑都对、一并发就错」，极难定位。

需要记忆请用 `memory` 形参；需要配置请用 `secrets`。

> 进程内缓存例外：如果你确实需要（如加载只读模型），把它改成
> 模块导入时就固定、之后只读的形式，避开 `global` + 赋值。

### 3. 禁止内联能力资产内容

Skill / MCP / 知识库的**内容**不能写死在 Agent 版本里，必须走引用。
`skills` / `mcp_servers` / `knowledge_bases` 必须是列表。

---

## 三、记忆（memory）

### 先声明作用域

平台托管的 Agent（`package` / `github` 接入）**必须**声明记忆作用域：

```python
source = {
    "artifact_id": "...",
    "entrypoint": "...",
    "memory": {"scope": "thread"},     # ← 必须
}
```

| scope | 含义 |
|---|---|
| `thread` | 按会话隔离（推荐）——一次对话一片记忆 |
| `tenant` | 按租户隔离，该租户下所有会话共享 |
| `agent_version` | 该版本全局共享 |
| `stateless` | **明确不要记忆**（不是「忘了写」） |

### 怎么用

声明了非 `stateless` 的 scope，平台就会注入 `memory` 形参：

```python
async def my_agent(input: str, memory=None) -> str:
    history = await memory.recent(limit=8)      # 最近几轮，时间正序
    await memory.remember("user", input)        # 记一轮
    await memory.remember("assistant", reply)

    facts = await memory.recall("用户偏好", top_k=5)   # 召回长期事实
    await memory.save_fact("order:status", "已发货")
    return reply
```

**分区键已绑好**，你拿不到也改不了——所以不存在「拼错 key 读到别人记忆」的可能。
平台按「Agent 版本 × 租户 × 会话」隔离。

> `sdk` 接入的 Agent 自己跑、自己管记忆，**不受这条约束**。

---

## 四、密钥（secrets）

### 声明需要哪些

```python
source = {
    "artifact_id": "...",
    "entrypoint": "...",
    "memory": {"scope": "thread"},
    "secrets": [
        {"name": "llm_api_key", "required": True},
        {"name": "mcp_github_token", "required": False},
    ],
}
```

只写**名字**，不写值。

### 怎么用

```python
async def my_agent(input: str, secrets: dict = None) -> str:
    client = call_model(api_key=(secrets or {}).get("llm_api_key"))
    ...
```

### 值在哪里配

在平台侧按 **Agent 版本 × 通道** 绑定：

1. `POST /api/secrets` 存一把（密文入库，只返回指纹）
2. `POST /api/agents/{id}/versions/{vid}/secrets/{channel}/bind` 绑到通道

**测试和生产可以绑不同的密钥**——这是通道分离的落点。

### 轮换与回滚

- **轮换**：再存一把新的 + 改指针。旧的不动。
- **回滚**：把指针改回旧的那把。

都不需要重新冻结版本。

> `required: true` 的密钥没绑就调用，会**直接失败**——不会给你一个空字符串
> 让 Agent 带着错误配置继续跑。

---

## 五、接入方式

| `connect_type` | 适用 | 必填字段 |
|---|---|---|
| `package` | 上传代码包 | `artifact_id`、`entrypoint` |
| `github` | GitHub 仓库 | `repository`、`ref`、`entrypoint` |
| `sdk` | SDK 已接好，平台只收 Trace | 无 |

选 `sdk` 时平台不托管执行，因此**不检查**入口签名与记忆声明。

---

## 六、上传前自查

```bash
# 冻结版本（静态规则在这里生效）
POST /api/agents/{id}/versions

# 运行时验收（需要真的加载代码）
GET /api/agents/{id}/versions/{vid}/conformance

# 绑 LIVE 前的更严口径：要求能流式
GET /api/agents/{id}/versions/{vid}/conformance?require_streaming=true
```

返回示例：

```json
{
  "passed": false,
  "issues": [
    {
      "field": "entrypoint.input",
      "code": "missing_param",
      "message": "入口必须接受 `input`——平台按这个形参传公开输入"
    }
  ]
}
```

**建议把这一步接进 CI**——不合规的版本绑不到 LIVE。

---

## 七、常见问题

**Q：我的入口叫 `query` 不是 `input`，能改吗？**
不能。平台按 `input` 传值。加一层适配入口即可：

```python
# platform_entry.py
from .agent import support_agent

async def platform_support_agent(input, messages=()):   # noqa: A002
    return await support_agent(input)
```

**Q：为什么不让我用模块级全局变量？**
单跑没事，**并发**就会串。编排会同时调你多个实例。用 `memory` 和 `secrets`。

**Q：密钥能直接读环境变量吗？**
本地开发可以；平台托管时用 `secrets` 形参——平台会把凭证注入到执行面，
你的代码不必也不该持有 Key。

**Q：返回结构化数据可以吗？**
可以。`input` 和输出都支持任意 JSON，编排时上游的对象会**原样**传给下游，
不会被序列化成文本。
