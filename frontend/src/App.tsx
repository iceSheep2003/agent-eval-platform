import { useEffect, useMemo, useState } from 'react'
import type { ComponentProps, ComponentType, FormEvent, ReactNode } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { ProLayout } from '@ant-design/pro-components'
import {
  Alert,
  App as AntApp,
  Avatar,
  Button as AntButton,
  ConfigProvider,
  Drawer,
  Dropdown,
  Empty,
  Input,
  Modal as AntModal,
  Progress,
  Select as AntSelect,
  Segmented,
  Space,
  Steps,
  Table,
  Tag,
  Tooltip as AntTooltip,
  Upload,
} from 'antd'
import type { TableProps } from 'antd'
import 'antd/dist/reset.css'
import {
  Activity,
  AlertTriangle,
  Archive,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Bot,
  Box,
  BrainCircuit,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CirclePause,
  CirclePlay,
  Clock3,
  Code2,
  Copy,
  Cpu,
  Database,
  ExternalLink,
  FileArchive,
  Gauge,
  GitBranch,
  Globe2,
  LayoutDashboard,
  Link2,
  MoreHorizontal,
  MessageSquare as MessageSquareIcon,
  Network,
  Play,
  Plus,
  RefreshCw,
  Search,
  Server,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Square,
  TerminalSquare,
  Timer,
  UploadCloud,
  Users,
  X,
  Zap,
  Layers3,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from './api'
import type { ApiAgent, ApiAgentDetail, ApiCapability, ApiDataset, ApiDeploymentToken, ApiPolicy, ApiRun, ApiSdkKey } from './api'

type Page = 'overview' | 'runs' | 'capabilities' | 'datasets' | 'agents'
type RunStatus = 'running' | 'completed' | 'failed' | 'paused'
type RunPhase = 'queued' | 'provisioning' | 'executing' | 'scoring' | 'completed' | 'failed'
type AgentStatus = 'online' | 'paused' | 'offline'
type DatasetKind = 'agentic' | 'single-turn' | 'badcase' | 'trace'

type Run = {
  id: string
  name: string
  agent: string
  dataset: string
  status: RunStatus
  phase?: RunPhase
  progress: number
  passed: number
  total: number
  score: number
  cost: number
  duration: string
  updated: string
  traceEvents?: TraceEvent[]
}

type Agent = {
  id: string
  name: string
  description: string
  mode: string
  version: string
  status: AgentStatus
  lastRun: string
  success: string
  accent: string
  endpoint: string
  environment: string
  owner: string
  evals: number
  latency: string
  versionId?: string
  instanceCount?: number
}

type User = {
  id: string
  username: string
  email: string
  displayName: string
  role: string
}

type Workspace = {
  id: string
  name: string
  description: string
  role: string
  memberCount: number
}

type AuthPayload = {
  user: User
  workspaces: Workspace[]
}

type DatasetItem = {
  id?: string
  name: string
  type: string
  desc: string
  count: string
  version: string
  status: string
  color: string
  icon: ComponentType<{ size?: number }>
  kind: DatasetKind
  protocol: string
  evaluation: string
  uploadFile?: File
}

const navItems: Array<{ id: Page; label: string; group: string; icon: ComponentType<{ size?: number }> }> = [
  { id: 'overview', label: '总览', group: '工作台', icon: LayoutDashboard },
  { id: 'agents', label: 'Agent 管理', group: 'Agent 工作区', icon: Bot },
  { id: 'capabilities', label: '评测策略', group: '评测中心', icon: BrainCircuit },
  { id: 'datasets', label: '数据集', group: '评测中心', icon: Database },
  { id: 'runs', label: '实验运行', group: '评测中心', icon: Activity },
]

const emptyRun: Run = { id: '—', name: '暂无运行', agent: '—', dataset: '—', status: 'completed', progress: 0, passed: 0, total: 0, score: 0, cost: 0, duration: '00m 00s', updated: '—' }

const recentTrace = [
  { time: '10:14:08.402', type: 'agent', title: 'Agent 选择了工具', detail: 'search_order(order_id="A-21903")', color: 'teal' },
  { time: '10:14:08.728', type: 'tool', title: '工具返回结果', detail: '订单可退款，原路退回 ¥249.00', color: 'blue' },
  { time: '10:14:10.091', type: 'agent', title: 'Agent 读取策略上下文', detail: 'policy.lookup("refund_window")', color: 'amber' },
  { time: '10:14:11.307', type: 'score', title: '维度评分完成', detail: '规则遵循 · 1.00 / 1.00', color: 'purple' },
]

type TraceEvent = (typeof recentTrace)[number]

const uiTheme = {
  token: {
    colorPrimary: '#0f62fe',
    colorInfo: '#0f62fe',
    colorSuccess: '#198038',
    colorWarning: '#b28600',
    colorError: '#da1e28',
    colorText: '#161616',
    colorTextSecondary: '#525252',
    colorBorder: '#c6c6c6',
    borderRadius: 2,
    fontFamily: 'IBM Plex Sans, "PingFang SC", "Microsoft YaHei", sans-serif',
    colorBgLayout: '#f4f4f4',
  },
  components: {
    Button: { controlHeight: 36, fontWeight: 600, borderRadius: 2 },
    Input: { controlHeight: 38 },
    Select: { controlHeight: 38 },
    Table: { headerBg: '#f4f4f4', rowHoverBg: '#edf5ff' },
    Modal: { borderRadiusLG: 2 },
    Card: { borderRadiusLG: 2 },
  },
}

function phaseForRun(run: Run): RunPhase {
  if (run.phase) return run.phase
  if (run.status === 'failed') return 'failed'
  if (run.status === 'completed') return 'completed'
  if (run.status === 'paused') return 'executing'
  if (run.progress < 10) return 'provisioning'
  if (run.progress < 84) return 'executing'
  return 'scoring'
}

function phaseLabel(phase: RunPhase) {
  return { queued: '排队中', provisioning: '准备执行环境', executing: '执行任务', scoring: '计算评分', completed: '已完成', failed: '已停止' }[phase]
}

function traceForRun(run: Run): TraceEvent[] {
  if (run.traceEvents?.length) return run.traceEvents
  const phase = phaseForRun(run)
  if (phase === 'queued') return [{ time: '刚刚', type: 'agent', title: '运行已创建', detail: '等待执行器分配环境', color: 'blue' }]
  if (phase === 'provisioning') return [
    { time: '刚刚', type: 'agent', title: '执行环境正在准备', detail: '固定 Agent 版本与数据集快照', color: 'blue' },
    { time: '刚刚', type: 'tool', title: '接入协议预检', detail: '等待 Agent 返回 ready 信号', color: 'amber' },
  ]
  if (phase === 'executing') return recentTrace.slice(0, 3)
  if (phase === 'scoring') return [
    ...recentTrace.slice(0, 3),
    { time: '刚刚', type: 'score', title: '正在汇总评分', detail: `${run.passed} / ${run.total} 个任务已完成，正在计算发布条件`, color: 'purple' },
  ]
  if (phase === 'failed') return [{ time: '刚刚', type: 'score', title: 'Run 已停止', detail: '已保留当前轨迹，可从失败任务创建回归样本', color: 'amber' }]
  return [
    ...recentTrace.slice(0, 3),
    { time: '刚刚', type: 'score', title: '评测已完成', detail: `${run.passed} / ${run.total} 个任务通过 · 结果已写入报告`, color: 'purple' },
  ]
}

function App() {
  return <ConfigProvider theme={uiTheme}><AntApp><AppContent /></AntApp></ConfigProvider>
}

function AppContent() {
  const [user, setUser] = useState<User | null>(null)
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [activeWorkspace, setActiveWorkspace] = useState<Workspace | null>(null)
  const [authStatus, setAuthStatus] = useState<'checking' | 'authenticated' | 'unauthenticated'>('checking')
  const [authError, setAuthError] = useState('')
  const [isLoginLoading, setIsLoginLoading] = useState(false)
  const [isWorkspaceOpen, setIsWorkspaceOpen] = useState(false)
  const [page, setPage] = useState<Page>('overview')
  const [runs, setRuns] = useState<Run[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [datasets, setDatasets] = useState<DatasetItem[]>([])
  const [policies, setPolicies] = useState<ApiPolicy[]>([])
  const [capabilities, setCapabilities] = useState<ApiCapability[]>([])
  const [selectedRun, setSelectedRun] = useState<Run>(emptyRun)
  const [isNewRunOpen, setIsNewRunOpen] = useState(false)
  const [runAgent, setRunAgent] = useState<string | undefined>()
  const [isAgentOpen, setIsAgentOpen] = useState(false)
  const [isPolicyOpen, setIsPolicyOpen] = useState(false)
  const [isSystemOpen, setIsSystemOpen] = useState(false)
  const [toast, setToast] = useState('')
  const reduceMotion = useReducedMotion()

  const mapAgent = (item: ApiAgent): Agent => ({
    id: item.id, name: item.name, description: item.description, mode: ({ package: '代码包', git: 'Git 仓库', sdk: 'SDK 接入', http: 'Agent 服务', mcp: 'MCP 服务', cli: 'CLI', python: 'Python 插件' } as Record<string, string>)[item.connect_type] || item.connect_type,
    version: item.version || '待创建版本', versionId: item.version_id,
    status: item.status === 'active' ? 'online' : item.status === 'paused' ? 'paused' : 'offline',
    lastRun: item.run_count ? '已有运行记录' : '尚未运行', success: item.success_rate == null ? '—' : `${Math.round(item.success_rate * 100)}%`, accent: '#0f62fe', endpoint: item.source_uri || '—',
    environment: item.environment, owner: item.owner, evals: item.binding_count || 0, latency: item.latency_ms == null ? '—' : `${item.latency_ms}ms`, instanceCount: item.instance_count,
  })

  const mapRun = (item: ApiRun): Run => ({
    id: item.id, name: item.name, agent: `${item.agent_name} / ${item.agent_version}`,
    dataset: item.dataset_name, status: item.status === 'queued' ? 'running' : item.status === 'cancelled' ? 'failed' : item.status,
    phase: item.phase, progress: item.progress, passed: item.passed, total: item.total,
    score: item.score, cost: item.cost,
    duration: `${Math.floor(item.duration_seconds / 60).toString().padStart(2, '0')}m ${(item.duration_seconds % 60).toString().padStart(2, '0')}s`, updated: '刚刚',
  })

  const mapDataset = (item: ApiDataset): DatasetItem => {
    const presentation = item.kind === 'agentic' ? { type: 'Agent 任务集', color: 'teal', icon: Network }
      : item.kind === 'badcase' ? { type: '人工标注样本', color: 'coral', icon: AlertTriangle }
      : item.kind === 'trace' ? { type: '失败轨迹样本', color: 'purple', icon: Activity }
      : { type: '单轮对话数据集', color: 'blue', icon: MessageSquareIcon }
    return { id: item.id, name: item.name, type: presentation.type, desc: item.description, count: `${item.item_count} 个任务`, version: item.version, status: item.status === 'ready' ? 'Ready' : 'Needs review', color: presentation.color, icon: presentation.icon, kind: item.kind, protocol: item.protocol, evaluation: item.evaluation }
  }

  const refreshPlatformData = async (workspace = activeWorkspace?.id || 'eval-dev') => {
    const [agentPayload, runPayload, datasetPayload, policyPayload, capabilityPayload] = await Promise.all([
      api<{ items: ApiAgent[] }>('/api/agents', {}, workspace),
      api<{ items: ApiRun[] }>('/api/runs', {}, workspace),
      api<{ items: ApiDataset[] }>('/api/datasets', {}, workspace),
      api<{ items: ApiPolicy[] }>('/api/policies', {}, workspace),
      api<{ items: ApiCapability[] }>('/api/capabilities', {}, workspace),
    ])
    const nextAgents = agentPayload.items.map(mapAgent)
    const nextRuns = runPayload.items.map(mapRun)
    setAgents(nextAgents)
    setRuns(nextRuns)
    setDatasets(datasetPayload.items.map(mapDataset))
    setPolicies(policyPayload.items)
    setCapabilities(capabilityPayload.items)
    if (nextRuns.length) setSelectedRun((current) => nextRuns.find((item) => item.id === current.id) || nextRuns[0])
  }

  useEffect(() => {
    fetch('/api/auth/me', { credentials: 'include' })
      .then(async (response) => {
        if (!response.ok) throw new Error(response.status === 401 ? 'unauthenticated' : 'api_unavailable')
        return response.json() as Promise<AuthPayload>
      })
      .then(async ({ user: currentUser, workspaces: availableWorkspaces }) => {
        setUser(currentUser)
        setWorkspaces(availableWorkspaces)
        setActiveWorkspace(availableWorkspaces[0] ?? null)
        await refreshPlatformData(availableWorkspaces[0]?.id)
        setAuthStatus('authenticated')
      })
      .catch((error: Error) => {
        setAuthStatus('unauthenticated')
        setAuthError(error.message === 'api_unavailable' ? '登录服务未启动，请先运行 npm run dev:api' : '')
      })
  }, [])

  useEffect(() => {
    if (!toast) return
    const timeout = window.setTimeout(() => setToast(''), 2600)
    return () => window.clearTimeout(timeout)
  }, [toast])

  useEffect(() => {
    if (!user || !activeWorkspace) return
    const interval = window.setInterval(() => void refreshPlatformData(activeWorkspace.id).catch(() => undefined), 1500)
    return () => window.clearInterval(interval)
  }, [user, activeWorkspace?.id])

  useEffect(() => {
    const fresh = runs.find((run) => run.id === selectedRun.id)
    if (fresh) setSelectedRun((current) => ({ ...fresh, traceEvents: current.traceEvents }))
  }, [runs, selectedRun.id])

  useEffect(() => {
    if (!user || selectedRun.id === '—') return
    void api<ApiRun & { traces: Array<{ id: string; event_type: string; name: string; input?: string; output?: string; status: string; started_at: string }> }>(`/api/runs/${selectedRun.id}`, {}, activeWorkspace?.id).then((detail) => {
      const colors: Record<string, string> = { agent: 'teal', tool: 'blue', llm: 'amber', score: 'purple' }
      const traceEvents = detail.traces.slice(-8).map((event) => ({
        time: new Date(event.started_at).toLocaleTimeString('zh-CN', { hour12: false }),
        type: event.event_type,
        title: event.name,
        detail: event.output || event.input || event.status,
        color: colors[event.event_type] || 'blue',
      }))
      setSelectedRun((current) => current.id === detail.id ? { ...current, traceEvents } : current)
    }).catch(() => undefined)
  }, [selectedRun.id, user, activeWorkspace?.id])

  const handleLogin = async (identifier: string, password: string) => {
    setIsLoginLoading(true)
    setAuthError('')
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        credentials: 'include',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ identifier, password }),
      })
      const payload = await response.json() as AuthPayload & { error?: string }
      if (!response.ok) throw new Error(payload.error || '登录失败')
      setUser(payload.user)
      setWorkspaces(payload.workspaces)
      setActiveWorkspace(payload.workspaces[0] ?? null)
      await refreshPlatformData(payload.workspaces[0]?.id)
      setAuthStatus('authenticated')
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : '登录失败，请稍后重试')
    } finally {
      setIsLoginLoading(false)
    }
  }

  const handleLogout = async () => {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }).catch(() => undefined)
    setUser(null)
    setWorkspaces([])
    setActiveWorkspace(null)
    setAuthStatus('unauthenticated')
    setAuthError('')
  }

  if (authStatus === 'checking') return <AuthLoading />
  if (!user) return <LoginPage error={authError} isLoading={isLoginLoading} onSubmit={handleLogin} />

  const notify = (message: string) => setToast(message)
  const activeNavItem = navItems.find((item) => item.id === page)

  const toggleAgent = async (id: string) => {
    const agent = agents.find((item) => item.id === id)
    if (!agent) return
    await api(`/api/agents/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status: agent.status === 'paused' ? 'active' : 'paused' }) }, activeWorkspace?.id)
    await refreshPlatformData()
    notify(`${agent.name} 已${agent.status === 'paused' ? '恢复' : '暂停'}`)
  }

  const deleteAgent = async (id: string) => {
    const agent = agents.find((item) => item.id === id)
    if (!agent || !window.confirm(`确认删除 ${agent.name}？运行中的实例必须先停止。`)) return
    await api(`/api/agents/${id}`, { method: 'DELETE' }, activeWorkspace?.id)
    await refreshPlatformData()
    notify(`${agent.name} 已从服务目录删除`)
  }

  const stopRun = async (id: string) => {
    await api(`/api/runs/${id}/stop`, { method: 'POST' }, activeWorkspace?.id)
    await refreshPlatformData()
    notify('运行实例已停止，已保留当前轨迹')
  }

  const pauseRun = async (id: string) => {
    const run = runs.find((item) => item.id === id)
    await api(`/api/runs/${id}/${run?.status === 'paused' ? 'resume' : 'pause'}`, { method: 'POST' }, activeWorkspace?.id)
    await refreshPlatformData()
    notify('运行状态已更新，Trace 会继续保留')
  }

  const createRun = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const agent = String(data.get('agent'))
    const dataset = String(data.get('dataset'))
    const registeredAgent = agents.find((item) => agent.startsWith(`${item.name} /`))
    if (!registeredAgent || registeredAgent.status === 'offline') {
      notify('当前 Agent 尚未通过健康检查，不能启动评测')
      return
    }
    if (!registeredAgent.versionId) return notify('当前 Agent 尚未创建可运行版本')
    const policy = policies.find((item) => item.dataset_name === dataset) ?? policies[0]
    if (!policy?.template_id) return notify('所选数据集尚未绑定已发布评测策略')
    const created = await api<ApiRun>('/api/runs', { method: 'POST', body: JSON.stringify({ name: `${dataset} · 新建评测`, agent_version_id: registeredAgent.versionId, template_id: policy.template_id, limits: { max_steps: Number(data.get('steps')), max_cost_usd: Number(String(data.get('budget')).replace('$', '')) } }) }, activeWorkspace?.id)
    const newRun = mapRun(created)
    setSelectedRun(newRun)
    await refreshPlatformData()
    setIsNewRunOpen(false)
    setRunAgent(undefined)
    setPage('runs')
    notify('评测运行已创建：Runner 正在准备环境')
  }

  const registerAgent = async ({ name, mode, endpoint, environment, packageFile, branch, entrypoint, timeout }: { name: string; mode: string; endpoint: string; environment: string; packageFile?: File; branch: string; entrypoint: string; timeout: string }) => {
    const typeMap: Record<string, string> = { 'Code Package': 'package', 'Git Repository': 'git', 'SDK Access': 'sdk' }
    const sourceType = typeMap[mode] || 'package'
    const created = await api<ApiAgent>('/api/agents', { method: 'POST', body: JSON.stringify({ name, description: mode === 'Git Repository' ? `从 Git 仓库导入 · ${branch}` : mode === 'Code Package' ? '从代码包导入并由平台托管' : '通过 SDK 上报运行轨迹与评测事件', connect_type: sourceType, environment, owner: user.displayName }) }, activeWorkspace?.id)
    const form = new FormData()
    form.set('version', '0.1.0')
    form.set('source_type', sourceType)
    if (endpoint) form.set('source_uri', endpoint)
    form.set('runtime_manifest', JSON.stringify({
      schema_version: 'agent.eval-loom/v1',
      entrypoint: sourceType === 'sdk' ? 'external-sdk' : entrypoint,
      source_ref: branch,
      timeout_seconds: Number(timeout),
      healthcheck: '/health',
      invoke_path: '/invoke',
      observability: { provider: 'deepeval', traces_required: true },
      benchmark_adapter: { protocol: 'agentic-bench/v1', action_observation_loop: true },
    }))
    if (packageFile) form.set('package', packageFile)
    await api(`/api/agents/${created.id}/versions`, { method: 'POST', body: form }, activeWorkspace?.id)
    const sdkAccess = sourceType === 'sdk' ? await api<ApiSdkKey>(`/api/agents/${created.id}/sdk-keys`, { method: 'POST', body: JSON.stringify({ name: '默认 SDK 密钥' }) }, activeWorkspace?.id) : undefined
    if (sourceType !== 'sdk') await api(`/api/agents/${created.id}/health-check`, { method: 'POST' }, activeWorkspace?.id)
    await refreshPlatformData()
    setPage('agents')
    if (sourceType !== 'sdk') setIsAgentOpen(false)
    notify(sourceType === 'sdk' ? `${name} 已添加，SDK 接入密钥已生成` : `${name} 已添加，接入契约检查已提交；通过后可一键部署`)
    return { agent: created, sdkAccess }
  }

  const updateAgent = async (id: string, updates: Partial<Pick<Agent, 'endpoint' | 'environment' | 'owner'>>) => {
    const current = agents.find((agent) => agent.id === id)
    if (!current) return
    await api(`/api/agents/${id}/config-changes`, { method: 'POST', body: JSON.stringify({ endpoint: updates.endpoint ?? current.endpoint, environment: updates.environment ?? current.environment, owner: updates.owner ?? current.owner }) }, activeWorkspace?.id)
    notify('配置变更已持久化，等待健康检查')
  }

  const healthCheckAgent = async (id: string) => {
    await api(`/api/agents/${id}/health-check`, { method: 'POST' }, activeWorkspace?.id)
    window.setTimeout(() => void refreshPlatformData(), 400)
  }

  const createPolicy = async (payload?: { name: string; datasetName: string; evaluators: string[]; trigger: string; gates: Record<string, unknown> }) => {
    payload ??= { name: '客服助手 · Regression v2', datasetName: datasets[0]?.name || '', evaluators: ['deterministic_match', 'policy_compliance'], trigger: '发布后自动触发', gates: { success_rate: 0.85, safety_violation_rate: 0 } }
    const dataset = datasets.find((item) => payload.datasetName.startsWith(item.name)) ?? datasets[0]
    if (!dataset?.id) return notify('请先导入一个可用数据集')
    await api('/api/policies', { method: 'POST', body: JSON.stringify({ name: payload.name, dataset_id: dataset.id, lifecycle: 'regression', evaluators: payload.evaluators, trigger_type: payload.trigger, gates: payload.gates }) }, activeWorkspace?.id)
    await refreshPlatformData()
    setIsPolicyOpen(false)
    notify('评测策略已创建，可绑定到 Agent Revision')
  }

  const importDataset = async (dataset: DatasetItem, file?: File) => {
    const upload = file ?? new File([dataset.kind === 'agentic' ? '{"task":{"instruction":"example"}}\n' : '{"input":"example","expected_output":"ok"}\n'], `${dataset.name}.jsonl`, { type: 'application/x-ndjson' })
    const form = new FormData()
    form.set('name', dataset.name)
    form.set('kind', dataset.kind)
    form.set('version', dataset.version.replace(/^v/, ''))
    form.set('file', upload)
    await api('/api/datasets/import', { method: 'POST', body: form }, activeWorkspace?.id)
    await refreshPlatformData()
    notify(`${dataset.name} 已导入并完成 Schema 校验`)
  }

  const registerBenchmarkAdapter = async () => {
    await api('/api/benchmark-adapters', { method: 'POST', body: JSON.stringify({ name: `benchmark-adapter-${Date.now()}`, version: '1.0.0', protocol: 'http', endpoint: 'http://benchmark-adapter.local' }) }, activeWorkspace?.id)
    notify('Benchmark Adapter 已登记，可绑定 Agentic 数据集')
  }

  const releaseAgent = async (agentId: string, version: string, channel: string, changelog = '') => {
    await api(`/api/agents/${agentId}/releases`, { method: 'POST', body: JSON.stringify({ version, channel, changelog }) }, activeWorkspace?.id)
    await refreshPlatformData()
  }

  const bindAgent = async (agentId: string, policyId?: string, schedule = 'manual', failureThreshold = 0.8, autoRegression = true, notifyOwner = true) => {
    const selected = policyId || policies[0]?.id
    if (!selected) return notify('请先创建评测策略')
    await api(`/api/agents/${agentId}/bindings`, { method: 'POST', body: JSON.stringify({ policy_id: selected, schedule, failure_threshold: failureThreshold, auto_regression: autoRegression, notify_owner: notifyOwner }) }, activeWorkspace?.id)
    await refreshPlatformData()
  }

  const rollbackAgent = async (agentId: string, versionName: string) => {
    const detail = await api<{ versions: Array<{ id: string; version: string }> }>(`/api/agents/${agentId}`, {}, activeWorkspace?.id)
    const target = detail.versions.find((item) => item.version === versionName)
    if (!target) return notify(`版本 ${versionName} 不存在，无法回滚`)
    await api(`/api/agents/${agentId}/rollback`, { method: 'POST', body: JSON.stringify({ target_version_id: target.id }) }, activeWorkspace?.id)
    await refreshPlatformData()
  }

  const setContinuousEvaluation = async (agentId: string, enabled: boolean) => {
    await api(`/api/agents/${agentId}/continuous-evaluation`, { method: 'PATCH', body: JSON.stringify({ enabled }) }, activeWorkspace?.id)
  }

  const saveWorkspaceSettings = async (payload: { refresh_interval_seconds: number; trace_retention_days: number; confirm_destructive: boolean }) => {
    await api('/api/workspace-settings', { method: 'PUT', body: JSON.stringify(payload) }, activeWorkspace?.id)
    notify('工作区设置已保存')
  }

  const loadAgentDetail = (agentId: string) => api<ApiAgentDetail>(`/api/agents/${agentId}`, {}, activeWorkspace?.id)

  const createAgentInstance = async (agentId: string, versionId: string) => {
    await api(`/api/agents/${agentId}/instances`, { method: 'POST', body: JSON.stringify({ agent_version_id: versionId }) }, activeWorkspace?.id)
    await refreshPlatformData()
  }

  const controlAgentInstance = async (instanceId: string, action: 'start' | 'stop' | 'delete') => {
    await api(`/api/instances/${instanceId}/${action}`, { method: 'POST' }, activeWorkspace?.id)
    await refreshPlatformData()
  }

  const saveAgentCredential = async (agentId: string, provider: string, value: string) => {
    await api('/api/credentials', { method: 'POST', body: JSON.stringify({ agent_id: agentId, provider, name: `${provider} primary`, value }) }, activeWorkspace?.id)
    notify('API Key 已加密保存，明文不会返回前端')
  }

  const deleteAgentCredential = async (credentialId: string) => {
    await api(`/api/credentials/${credentialId}`, { method: 'DELETE' }, activeWorkspace?.id)
    notify('密钥已撤销，后续新实例将无法再使用它')
  }


  const createDeploymentToken = (agentId: string, name: string) => api<ApiDeploymentToken>(`/api/agents/${agentId}/access-tokens`, { method: 'POST', body: JSON.stringify({ name }) }, activeWorkspace?.id)

  const createAgentSdkKey = (agentId: string, name: string) => api<ApiSdkKey>(`/api/agents/${agentId}/sdk-keys`, { method: 'POST', body: JSON.stringify({ name }) }, activeWorkspace?.id)

  const deployAgent = (agentId: string) => api<{ access: ApiDeploymentToken; invoke_url: string }>(`/api/agents/${agentId}/deploy`, { method: 'POST', body: JSON.stringify({ name: '默认业务 Token' }) }, activeWorkspace?.id)

  const revokeDeploymentToken = async (tokenId: string) => {
    await api(`/api/access-tokens/${tokenId}`, { method: 'DELETE' }, activeWorkspace?.id)
    notify('调用 Token 已撤销')
  }

  const revokeAgentSdkKey = async (keyId: string) => {
    await api(`/api/sdk-keys/${keyId}`, { method: 'DELETE' }, activeWorkspace?.id)
    notify('SDK 接入密钥已撤销')
  }

  const invokeAgent = (agentId: string, payload: Record<string, unknown>) => api<{ output: unknown; latency_ms: number; version: string }>(`/api/agents/${agentId}/invoke`, { method: 'POST', body: JSON.stringify(payload) }, activeWorkspace?.id)

  const openAgentTrace = (agentName: string) => {
    const matchingRun = runs.find((run) => run.agent.startsWith(`${agentName} /`))
    if (!matchingRun) {
      notify(`${agentName} 暂无可用 Trace`)
      return
    }
    setSelectedRun(matchingRun)
    setPage('runs')
  }

  const proRoutes = navItems.map(({ id, label, group, icon: Icon }) => ({ path: `/${id}`, name: label, group, icon: <Icon size={17} /> }))
  const workspaceMenu = {
    className: 'workspace-dropdown-menu',
    items: workspaces.map((workspace) => ({
      key: workspace.id,
      label: <span><strong>{workspace.name}</strong><small>{workspace.role} · {workspace.memberCount} 人</small></span>,
      icon: <Avatar size={24}>{workspace.name.slice(0, 1)}</Avatar>,
      extra: workspace.id === activeWorkspace?.id ? <Check size={14} /> : undefined,
      onClick: () => { setActiveWorkspace(workspace); setIsWorkspaceOpen(false); notify(`已切换到 ${workspace.name}`) },
    })),
  }

  return (
    <div className="app-shell pro-app-shell">
      <ProLayout
        className="eval-pro-layout"
        title="Eval Loom"
        logo={<div className="brand-mark pro-brand-mark"><span /></div>}
        layout="mix"
        splitMenus={false}
        fixedHeader
        fixSiderbar
        siderWidth={224}
        route={{ routes: proRoutes }}
        location={{ pathname: `/${page}` }}
        selectedKeys={[`/${page}`]}
        menuItemRender={(item, dom) => <button className="pro-menu-link" onClick={() => setPage(String(item.path).slice(1) as Page)}>{dom}{item.path === '/runs' && <span className="nav-count">{runs.filter((run) => run.status === 'running').length}</span>}</button>}
        menuHeaderRender={(_, title) => <div className="pro-brand">{title}<span>Agent 评测控制台</span></div>}
        actionsRender={() => [
          <div className="command-hint" key="search"><Search size={15} /><span>快速查找</span><kbd>⌘ K</kbd></div>,
          <Dropdown key="workspace" trigger={['click']} open={isWorkspaceOpen} onOpenChange={setIsWorkspaceOpen} menu={workspaceMenu}>
            <button className="pro-workspace-switcher" aria-label={`切换工作区：${activeWorkspace?.name ?? '未选择'}`}><Avatar size={26}>{activeWorkspace?.name.slice(0, 1) ?? 'W'}</Avatar><span><strong>{activeWorkspace?.name ?? '选择工作区'}</strong><small>{activeWorkspace?.role ?? 'No workspace'}</small></span><ChevronDown size={14} /></button>
          </Dropdown>,
          <AntTooltip key="settings" title="工作区设置"><AntButton type="text" aria-label="全局设置" onClick={() => setIsSystemOpen(true)} icon={<SlidersHorizontal size={18} />} /></AntTooltip>,
        ]}
        avatarProps={{
          src: undefined,
          title: user.displayName,
          render: (_, avatar) => <Dropdown menu={{ items: [{ key: 'role', label: user.role, disabled: true }, { type: 'divider' }, { key: 'logout', label: '退出登录', onClick: handleLogout }] }}>{avatar}</Dropdown>,
        }}
        contentStyle={{ padding: 0 }}
        token={{ header: { colorBgHeader: '#ffffff' }, sider: { colorMenuBackground: '#111827', colorTextMenu: '#aab3c2', colorTextMenuSelected: '#ffffff', colorBgMenuItemSelected: '#2457e6' } }}
      >
        <main className="main-content pro-main-content">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={page}
            className="page-stage"
            initial={reduceMotion ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduceMotion ? undefined : { opacity: 0, y: -4 }}
            transition={{ duration: reduceMotion ? 0 : 0.24, ease: 'easeOut' }}
          >
            {page === 'overview' && <Overview runs={runs} capabilities={capabilities} selectedRun={selectedRun} onNewRun={() => setIsNewRunOpen(true)} onOpenRuns={() => setPage('runs')} onOpenCapabilities={() => setPage('capabilities')} onSelectRun={(run) => { setSelectedRun(run); setPage('runs') }} onNotify={notify} />}
            {page === 'runs' && <RunsPage runs={runs} selectedRun={selectedRun} onSelect={setSelectedRun} onNewRun={() => setIsNewRunOpen(true)} onPause={pauseRun} onStop={stopRun} />}
            {page === 'capabilities' && <CapabilitiesPage policies={policies} capabilities={capabilities} onNewPolicy={() => setIsPolicyOpen(true)} />}
            {page === 'datasets' && <DatasetsPage datasets={datasets} onImport={importDataset} onBenchmark={registerBenchmarkAdapter} onNewRun={() => setIsNewRunOpen(true)} onNotify={notify} />}
            {page === 'agents' && <AgentsPage agents={agents} policies={policies} onToggle={toggleAgent} onDelete={deleteAgent} onAdd={() => setIsAgentOpen(true)} onUpdate={updateAgent} onHealthCheck={healthCheckAgent} onRelease={releaseAgent} onBind={bindAgent} onRollback={rollbackAgent} onContinuous={setContinuousEvaluation} onLoadDetail={loadAgentDetail} onCreateInstance={createAgentInstance} onInstanceAction={controlAgentInstance} onSaveCredential={saveAgentCredential} onDeleteCredential={deleteAgentCredential} onDeploy={deployAgent} onCreateAccessToken={createDeploymentToken} onRevokeAccessToken={revokeDeploymentToken} onCreateSdkKey={createAgentSdkKey} onRevokeSdkKey={revokeAgentSdkKey} onInvoke={invokeAgent} onTrace={openAgentTrace} onRun={(agentName) => { setRunAgent(agentName); setIsNewRunOpen(true) }} onOpenRuns={() => setPage('runs')} onNotify={notify} />}
          </motion.div>
        </AnimatePresence>

        <footer className="content-footer"><span>Eval Loom · {activeWorkspace?.name ?? '本地工作区'}</span><span>协议 v0.1 · 轨迹保留：本地</span></footer>
        </main>
      </ProLayout>

      {isNewRunOpen && <NewRunModal agents={agents} datasets={datasets} defaultAgent={runAgent} onClose={() => { setIsNewRunOpen(false); setRunAgent(undefined) }} onSubmit={createRun} />}
      {isAgentOpen && <AgentModal onClose={() => setIsAgentOpen(false)} onSuccess={registerAgent} />}
      {isPolicyOpen && <EvaluationPolicyModal datasets={datasets} onClose={() => setIsPolicyOpen(false)} onCreate={createPolicy} />}
      {isSystemOpen && <SystemSettingsModal onClose={() => setIsSystemOpen(false)} onSave={saveWorkspaceSettings} />}
      {toast && <div className="toast" role="status" aria-live="polite"><CheckCircle2 size={17} />{toast}</div>}
    </div>
  )
}

function AuthLoading() {
  return <div className="auth-loading"><div className="brand-mark"><span /></div><span>正在连接评测工作区…</span></div>
}

function LoginPage({ error, isLoading, onSubmit }: { error: string; isLoading: boolean; onSubmit: (identifier: string, password: string) => void }) {
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    onSubmit(String(data.get('identifier') || ''), String(data.get('password') || ''))
  }

  return <div className="auth-shell">
    <div className="auth-grid">
      <section className="auth-copy">
        <div className="brand-lockup auth-brand"><div className="brand-mark"><span /></div><div><div className="brand-name">EVAL LOOM</div><div className="brand-caption">Agent 评测控制台</div></div></div>
        <div className="auth-copy-body"><span className="eyebrow"><span className="eyebrow-line" />工作区登录</span><h1>让 Agent 的每一步，<em>都可以被复盘。</em></h1><p>统一管理评测任务、数据集、能力评分和运行轨迹。登录后进入你有权限访问的工作区。</p></div>
        <div className="auth-signal"><div><small>轨迹事件</small><strong>12,480</strong></div><div><small>运行中的任务</small><strong>03</strong></div><div><small>协议版本</small><strong>v0.1</strong></div></div>
      </section>
      <section className="auth-panel">
        <div className="auth-panel-kicker">安全工作区登录</div>
        <h2>登录评测平台</h2>
        <p className="auth-panel-copy">使用你的账号进入对应工作区。</p>
        <form className="auth-form" onSubmit={submit}>
          <label>账号或邮箱<Input name="identifier" autoComplete="username" placeholder="admin 或 admin@evalloom.local" required /></label>
          <label>密码<Input.Password name="password" autoComplete="current-password" placeholder="输入密码" required /></label>
          {error && <Alert className="auth-error" type="error" showIcon message={error} />}
          <AntButton className="primary-btn auth-submit" htmlType="submit" type="primary" loading={isLoading} icon={<ArrowDownRight size={16} />} iconPosition="end">进入工作区</AntButton>
        </form>
        <div className="demo-accounts"><div><span className="status-pulse" />演示账号</div><p><code>admin</code> / <code>admin123</code><br /><code>demo</code> / <code>demo123</code></p></div>
        <div className="auth-footnote"><ShieldCheck size={14} />本地演示使用会话 Cookie；生产环境建议接入企业身份认证。</div>
      </section>
    </div>
  </div>
}

function PageHeading({ kicker, title, description, actions }: { kicker: string; title: string; description: string; actions?: ReactNode }) {
  return <section className="page-heading"><div><div className="page-kicker"><span className="page-kicker-line" />{kicker}</div><h1>{title}</h1><p>{description}</p></div>{actions && <div className="heading-actions">{actions}</div>}</section>
}

function Overview({ runs, capabilities, onNewRun, onOpenRuns, onOpenCapabilities, onSelectRun, selectedRun, onNotify }: { runs: Run[]; capabilities: ApiCapability[]; onNewRun: () => void; onOpenRuns: () => void; onOpenCapabilities: () => void; onSelectRun: (run: Run) => void; selectedRun: Run; onNotify: (message: string) => void }) {
  const completed = runs.filter((run) => run.status === 'completed')
  const successRate = completed.length ? completed.reduce((sum, run) => sum + run.score, 0) / completed.length : 0
  const averageCost = runs.length ? runs.reduce((sum, run) => sum + run.cost, 0) / runs.length : 0
  const averageDurationSeconds = completed.length ? completed.reduce((sum, run) => { const match = run.duration.match(/(\d+)m\s+(\d+)s/); return sum + (match ? Number(match[1]) * 60 + Number(match[2]) : 0) }, 0) / completed.length : 0
  const runTrend = runs.slice(0, 7).reverse().map((run, index) => ({ day: run.updated === '刚刚' ? `Run ${index + 1}` : run.updated, success: Math.round(run.score * 100), cost: run.cost }))
  const failed = runs.filter((run) => run.status === 'failed').length
  const liveDimensionBars = capabilities.flatMap((capability) => capability.dimensions.map((dimension, index) => ({ name: dimension.name, score: dimension.score, fill: ['#0f62fe', '#4589ff', '#78a9ff', '#a6c8ff', '#d0e2ff'][index % 5] }))).slice(0, 5)
  return (
    <div className="page-wrap">
      <PageHeading kicker="工作台 / 评测总览" title="评测总览" description="查看运行状态、评测质量和失败轨迹。" actions={<AntButton className="primary-btn hero-action" type="primary" icon={<Plus size={18} />} onClick={onNewRun}>新建评测运行</AntButton>} />

      <section className="signal-strip">
        <div className="signal-node"><span className="node-dot green" /><div><small>执行器状态</small><strong>正常</strong></div></div>
        <div className="signal-divider" />
        <div className="signal-node"><span className="node-dot blue" /><div><small>运行中任务</small><strong>{String(runs.filter((run) => run.status === 'running').length).padStart(2, '0')} <span>当前</span></strong></div></div>
        <div className="signal-divider" />
        <div className="signal-node"><span className="node-dot orange" /><div><small>已完成任务</small><strong>{runs.reduce((sum, run) => sum + run.total, 0)} <span>Trials</span></strong></div></div>
        <div className="signal-divider" />
        <div className="signal-node signal-tail"><span className="node-dot purple" /><div><small>接入协议</small><strong>任务 / 上下文 / 动作</strong></div></div>
      </section>

      <section className="metrics-grid">
        <MetricCard icon={Gauge} label="任务成功率" value={`${Math.round(successRate * 100)}%`} delta={`${completed.length} runs`} detail="已完成运行均值" tone="teal" />
        <MetricCard icon={Zap} label="平均每任务成本" value={`$${averageCost.toFixed(2)}`} delta={`${runs.length} runs`} detail="当前工作区均值" tone="blue" down />
        <MetricCard icon={Timer} label="平均完成时间" value={`${Math.floor(averageDurationSeconds / 60).toString().padStart(2, '0')}m ${Math.round(averageDurationSeconds % 60).toString().padStart(2, '0')}s`} delta={`${completed.length} runs`} detail="已完成运行均值" tone="amber" down />
        <MetricCard icon={AlertTriangle} label="待处理失败" value={String(failed).padStart(2, '0')} delta={`${failed} 个失败`} detail="需要查看轨迹" tone="coral" />
      </section>

      <section className="dashboard-grid">
        <div className="panel chart-panel">
          <PanelHeader title="质量信号" subtitle="最近 7 天的运行表现" action={<button className="select-pill" onClick={() => onNotify('当前趋势指标：任务成功率')}>成功率 <ChevronDown size={14} /></button>} />
          <div className="chart-legend"><span><i className="legend-teal" />成功率</span><span><i className="legend-muted" />成本水平</span></div>
          <div className="chart-box"><ResponsiveContainer width="100%" height="100%"><AreaChart data={runTrend} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
            <defs><linearGradient id="successGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#2f67f6" stopOpacity={0.18} /><stop offset="100%" stopColor="#2f67f6" stopOpacity={0} /></linearGradient></defs>
            <CartesianGrid vertical={false} stroke="#d9e1ea" strokeDasharray="3 5" />
            <XAxis dataKey="day" tickLine={false} axisLine={false} tick={{ fill: '#80908e', fontSize: 11 }} dy={10} />
            <YAxis domain={[40, 100]} tickLine={false} axisLine={false} tick={{ fill: '#80908e', fontSize: 11 }} tickFormatter={(value) => `${value}%`} />
            <Tooltip content={<ChartTooltip />} />
            <Area type="monotone" dataKey="success" stroke="#2f67f6" strokeWidth={2.5} fill="url(#successGradient)" activeDot={{ r: 5, fill: '#2f67f6', stroke: '#ffffff', strokeWidth: 3 }} />
          </AreaChart></ResponsiveContainer></div>
          <div className="chart-footnote"><span><span className="foot-dot" />本周期均值 <strong>{Math.round(successRate * 100)}%</strong></span><span>目标线 <strong>80%</strong></span></div>
        </div>
        <div className="panel dimension-panel">
          <PanelHeader title="能力雷达" subtitle="当前工作区维度得分" action={<AntButton size="small" className="text-btn" type="text" onClick={onOpenCapabilities}>查看全部 <ExternalLink size={13} /></AntButton>} />
          <div className="dimension-list">{liveDimensionBars.map((item) => <div key={item.name} className="dimension-row"><div className="dimension-label"><span>{item.name}</span><strong>{item.score}<small>/100</small></strong></div><div className="meter"><span style={{ width: `${item.score}%`, background: item.fill }} /></div></div>)}</div>
          <div className="dimension-note"><Sparkles size={15} /><span>错误恢复得分最低，建议先查看相关失败轨迹</span><ArrowUpRight size={14} /></div>
        </div>
      </section>

      <section className="lower-grid">
        <div className="panel runs-panel">
          <PanelHeader title="最近运行" subtitle="按更新时间排序" action={<AntButton size="small" className="text-btn" type="text" onClick={onOpenRuns}>全部运行 <ArrowUpRight size={13} /></AntButton>} />
          <RunTable runs={runs.slice(0, 3)} onSelect={onSelectRun} />
        </div>
        <div className="panel trace-panel">
          <PanelHeader title="实时轨迹" subtitle={selectedRun.id} action={<span className="streaming"><span />实时</span>} />
          <div className="trace-summary"><div className="trace-agent"><div className="agent-mini-avatar">C</div><div><strong>{selectedRun.agent}</strong><span>{selectedRun.dataset}</span></div></div><div className="trace-score"><strong>{Math.round(selectedRun.score * 100)}<small>/100</small></strong><span>当前分数</span></div></div>
          <TraceTimeline compact events={traceForRun(selectedRun)} />
          <div className="trace-footer"><span><Clock3 size={14} />最后事件 10:14:11</span><button className="trace-link" onClick={onOpenRuns}>打开完整轨迹 <ArrowUpRight size={14} /></button></div>
        </div>
      </section>
    </div>
  )
}

function MetricCard({ icon: Icon, label, value, delta, detail, tone, down = false }: { icon: ComponentType<{ size?: number }>; label: string; value: string; delta: string; detail: string; tone: string; down?: boolean }) {
  return <div className={`metric-card tone-${tone}`}><div className="metric-top"><span className="metric-icon"><Icon size={17} /></span><span className={`metric-delta ${down ? 'positive' : ''}`}>{down ? <ArrowDownRight size={13} /> : <ArrowUpRight size={13} />}{delta}</span></div><div className="metric-label">{label}</div><div className="metric-value">{value}</div><div className="metric-detail">{detail}</div></div>
}

function PanelHeader({ title, subtitle, action }: { title: string; subtitle: string; action?: ReactNode }) {
  return <div className="panel-header"><div><h2>{title}</h2><p>{subtitle}</p></div>{action}</div>
}

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ value: number }>; label?: string }) {
  if (!active || !payload?.length) return null
  return <div className="chart-tooltip"><span>{label}</span><strong>{payload[0].value}%</strong><small>任务成功率</small></div>
}

function RunTable({ runs, selectedId, onSelect }: { runs: Run[]; selectedId?: string; onSelect: (run: Run) => void }) {
  const columns: TableProps<Run>['columns'] = [
    {
      title: '运行实例',
      key: 'name',
      render: (_, run) => <Space className="run-name-cell" size={10}><span className={`run-status-icon ${run.status}`}><StatusIcon status={run.status} /></span><span><strong>{run.name}</strong><small>{run.agent}</small></span></Space>,
    },
    { title: '数据集', dataIndex: 'dataset', key: 'dataset', width: 178, render: (value: string) => <span className="run-dataset">{value}</span> },
    { title: '状态', key: 'status', width: 96, render: (_, run) => <StatusBadge status={run.status} /> },
    { title: '进度', key: 'progress', width: 128, render: (_, run) => <div className="run-table-progress"><span><i style={{ width: `${run.progress}%` }} /></span><small>{run.progress}%</small></div> },
    { title: '得分', key: 'score', width: 70, render: (_, run) => <strong className="run-score">{run.status === 'completed' ? Math.round(run.score * 100) : '—'}</strong> },
    { title: '成本', key: 'cost', width: 70, render: (_, run) => <span className="run-cost">${run.cost.toFixed(2)}</span> },
    { title: '更新时间', dataIndex: 'updated', key: 'updated', width: 96, render: (value: string) => <span className="run-updated">{value}</span> },
    { key: 'action', width: 32, render: () => <ChevronRight className="row-arrow" size={15} /> },
  ]
  return <div className="run-table mature-run-table"><Table<Run> rowKey="id" size="middle" pagination={false} showHeader columns={columns} dataSource={runs} rowClassName={(run) => run.id === selectedId ? 'is-selected' : ''} onRow={(run) => ({ onClick: () => onSelect(run), onKeyDown: (event) => { if (event.key === 'Enter') onSelect(run) }, tabIndex: 0 })} /></div>
}

function StatusIcon({ status }: { status: RunStatus }) {
  if (status === 'running') return <CirclePlay size={14} />
  if (status === 'paused') return <CirclePause size={14} />
  if (status === 'failed') return <AlertTriangle size={14} />
  return <Check size={14} />
}

function StatusBadge({ status }: { status: RunStatus }) {
  const labels: Record<RunStatus, string> = { running: '运行中', completed: '已完成', failed: '失败', paused: '已暂停' }
  return <Tag className={`status-badge ${status}`}>{labels[status]}</Tag>
}

function TraceTimeline({ compact = false, events = recentTrace }: { compact?: boolean; events?: TraceEvent[] }) {
  return <div className={`trace-timeline ${compact ? 'compact' : ''}`}><AnimatePresence initial={false}>{events.map((event, index) => <motion.div className="trace-event" key={`${event.time}-${event.title}`} layout initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 8 }} transition={{ delay: index * 0.045, duration: 0.22, ease: 'easeOut' }}><div className={`trace-node ${event.color}`}><TraceEventIcon type={event.type} /></div><div className="trace-line" /><div className="trace-event-copy"><div><span>{event.time}</span><strong>{event.title}</strong></div><p>{event.detail}</p></div>{index === events.length - 1 && <span className="trace-now">实时</span>}</motion.div>)}</AnimatePresence></div>
}

function TraceEventIcon({ type }: { type: string }) {
  if (type === 'tool') return <Network size={13} />
  if (type === 'score') return <ShieldCheck size={13} />
  return <Bot size={13} />
}


function RunsPage({ runs, selectedRun, onSelect, onNewRun, onPause, onStop }: { runs: Run[]; selectedRun: Run; onSelect: (run: Run) => void; onNewRun: () => void; onPause: (id: string) => void; onStop: (id: string) => void }) {
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | RunStatus>('all')
  const visibleRuns = runs.filter((run) => `${run.name} ${run.agent} ${run.dataset}`.toLowerCase().includes(query.toLowerCase()) && (statusFilter === 'all' || run.status === statusFilter))
  const selectedPhase = phaseForRun(selectedRun)
  const phases: RunPhase[] = ['provisioning', 'executing', 'scoring', 'completed']
  const phaseIndex = selectedPhase === 'failed' ? 2 : Math.max(0, phases.indexOf(selectedPhase))
  const statuses: Array<{ id: 'all' | RunStatus; label: string }> = [
    { id: 'all', label: '全部' },
    { id: 'running', label: '运行中' },
    { id: 'completed', label: '已完成' },
    { id: 'failed', label: '失败' },
    { id: 'paused', label: '已暂停' },
  ]

  return <div className="page-wrap page-runs">
    <PageHeading kicker="评测中心" title="实验运行" description="对比版本质量、定位失败任务，并查看每次执行的完整轨迹。" actions={<AntButton className="primary-btn" type="primary" icon={<Plus size={16} />} onClick={onNewRun}>新建运行</AntButton>} />
    <section className="run-workbench">
      <div className="run-signal-bar">
        <div><span>运行总数</span><strong>{runs.length}</strong></div>
        <div><span className="status-dot running" />运行中<strong>{runs.filter((run) => run.status === 'running').length}</strong></div>
        <div><span className="status-dot failed" />失败<strong>{runs.filter((run) => run.status === 'failed').length}</strong></div>
        <div><span>平均得分</span><strong>{Math.round((runs.reduce((sum, run) => sum + run.score, 0) / Math.max(runs.length, 1)) * 100)}</strong><small>/100</small></div>
        <div className="signal-updated"><RefreshCw size={13} />自动刷新 · 1.5s</div>
      </div>
      <div className="run-toolbar">
        <div className="run-status-tabs" role="tablist" aria-label="运行状态">
          {statuses.map((status) => <button key={status.id} className={statusFilter === status.id ? 'active' : ''} onClick={() => setStatusFilter(status.id)}>{status.label}<span>{status.id === 'all' ? runs.length : runs.filter((run) => run.status === status.id).length}</span></button>)}
        </div>
        <Input className="run-search" prefix={<Search size={15} />} aria-label="搜索运行实例" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索运行、Agent 或数据集" allowClear />
      </div>
      <div className={`run-workspace ${runs.length ? '' : 'is-empty'}`}>
        <section className="run-list-pane" aria-label="运行列表">
          {visibleRuns.length ? <RunTable runs={visibleRuns} selectedId={selectedRun.id} onSelect={onSelect} /> : <Empty className="empty-state" image={Empty.PRESENTED_IMAGE_SIMPLE} description={<span>没有匹配的运行<br /><small>调整搜索词或切换状态</small></span>} />}
        </section>
        {runs.length > 0 && <aside className="run-inspector" aria-label="运行详情">
          <div className="inspector-header">
            <div className="inspector-title-row"><StatusBadge status={selectedRun.status} /><span>{selectedRun.id}</span></div>
            <h2>{selectedRun.name}</h2>
            <p>{selectedRun.agent}<span>·</span>{selectedRun.dataset}</p>
          </div>
          <div className="inspector-actions">
            {selectedRun.status === 'running' || selectedRun.status === 'paused' ? <>
              <AntButton className="small-action" icon={selectedRun.status === 'paused' ? <CirclePlay size={14} /> : <CirclePause size={14} />} onClick={() => onPause(selectedRun.id)}>{selectedRun.status === 'paused' ? '恢复运行' : '暂停运行'}</AntButton>
              <AntButton className="small-action danger" danger icon={<Square size={13} />} onClick={() => onStop(selectedRun.id)}>停止</AntButton>
            </> : <span className="detail-action-note">结果已固化，可用于版本对比与失败回灌</span>}
          </div>
          <div className="inspector-metrics">
            <div><span>质量得分</span><strong>{selectedPhase === 'completed' ? Math.round(selectedRun.score * 100) : '—'}<small>/100</small></strong></div>
            <div><span>任务通过</span><strong>{selectedRun.passed}<small>/{selectedRun.total}</small></strong></div>
            <div><span>成本</span><strong>${selectedRun.cost.toFixed(2)}</strong></div>
            <div><span>耗时</span><strong>{selectedRun.duration}</strong></div>
          </div>
          <div className="inspector-section">
            <div className="inspector-section-title"><span>执行进度</span><strong>{selectedRun.progress}%</strong></div>
            <Progress className="mature-linear-progress" percent={selectedRun.progress} strokeColor="#315efb" trailColor="#e6e8ec" showInfo={false} />
            <Steps className="mature-stepper" current={phaseIndex} size="small" items={(['provisioning', 'executing', 'scoring', 'completed'] as RunPhase[]).map((phase) => ({ title: phaseLabel(phase) }))} status={selectedPhase === 'failed' ? 'error' : undefined} />
          </div>
          <div className="inspector-section trace-section">
            <div className="inspector-section-title"><span>最近事件</span><small>{selectedPhase === 'completed' || selectedPhase === 'failed' ? '已固化' : '实时更新'}</small></div>
            <TraceTimeline events={traceForRun(selectedRun)} />
          </div>
        </aside>}
      </div>
    </section>
  </div>
}

function CapabilitiesPage({ policies, capabilities, onNewPolicy }: { policies: ApiPolicy[]; capabilities: ApiCapability[]; onNewPolicy: () => void }) {
  const [lifecycle, setLifecycle] = useState<'all' | 'onboarding' | 'smoke' | 'regression' | 'release' | 'continuous' | 'online'>('all')
  const [view, setView] = useState<'lifecycle' | 'dimension'>('lifecycle')
  const lifecycleStages = [
    { id: 'onboarding', label: '接入校验', short: '接入检查', detail: '确认连接可用、权限正确、响应格式完整', color: 'slate', gate: '未通过不可运行' },
    { id: 'smoke', label: '冒烟测试', short: '快速检查', detail: '用少量任务确认 Agent 能完成基本流程', color: 'teal', gate: '接入或发布时触发' },
    { id: 'regression', label: '回归测试', short: '版本对比', detail: '固定同一批任务，比较新旧版本的结果变化', color: 'blue', gate: '发布前必跑' },
    { id: 'release', label: '发布门禁', short: '发布条件', detail: '根据成功率、安全和成本决定版本能否发布', color: 'amber', gate: '阻止不合格版本' },
    { id: 'continuous', label: '持续评测', short: '定时检查', detail: '定期重跑任务，及时发现质量和成本变化', color: 'purple', gate: '每 6 小时 / 每日' },
    { id: 'online', label: '线上抽样', short: '线上观察', detail: '从真实运行中抽样，检查质量、成本和安全', color: 'coral', gate: '告警与复盘' },
  ] as const
  const dimensions = capabilities.flatMap((capability, index) => capability.dimensions.map((dimension) => ({ icon: [CheckCircle2, Network, ShieldCheck, Activity, Gauge, BrainCircuit][index % 6], name: dimension.name, desc: capability.description, applies: dimension.deterministic ? '确定性评分' : '语义评分 / 人工复核', score: String(dimension.score), tone: ['teal', 'blue', 'amber', 'coral', 'purple', 'slate'][index % 6] })))
  const strategies = policies.map((policy) => ({ stage: policy.lifecycle, name: policy.name, dataset: `${policy.dataset_name} · ${policy.dataset_version}`, protocol: '模板 / Runner', dimensions: policy.evaluators, score: policy.enabled ? '已启用' : '已暂停', trigger: policy.trigger_type, tone: ({ onboarding: 'slate', smoke: 'teal', regression: 'blue', release: 'amber', continuous: 'purple', online: 'coral' } as Record<string, string>)[policy.lifecycle] || 'blue' }))
  const visibleStrategies = lifecycle === 'all' ? strategies : strategies.filter((strategy) => strategy.stage === lifecycle)
  const activeStage = lifecycleStages.find((stage) => stage.id === lifecycle)

  return <div className="page-wrap page-strategies"><section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line" />EVALUATION CONTROL PLANE</div><h1>评测策略</h1><p>策略目录统一管理生命周期、数据集协议、评分维度和发布门禁。</p></div><button className="primary-btn" onClick={onNewPolicy}><Plus size={18} />创建评测策略</button></section><section className="strategy-principle"><div className="principle-mark"><GitBranch size={18} /></div><div><strong>策略运行边界</strong><p>Agentic 任务通过 Benchmark Adapter 驱动环境和动作循环；单轮与 Badcase 通过固定输入、输出和标签直接评分。</p></div><span className="protocol-chip">Task → Action → Observation</span></section><div className="strategy-switcher"><button className={view === 'lifecycle' ? 'active' : ''} onClick={() => setView('lifecycle')}><GitBranch size={14} />按生命周期</button><button className={view === 'dimension' ? 'active' : ''} onClick={() => setView('dimension')}><SlidersHorizontal size={14} />按评测维度</button></div>{view === 'lifecycle' ? <div className="strategy-layout"><aside className="lifecycle-nav panel"><div className="subpanel-heading"><div><span className="detail-kicker">AGENT LIFECYCLE</span><h3>生命周期</h3></div><span className="directory-count">6 stages</span></div><button className={lifecycle === 'all' ? 'selected' : ''} onClick={() => setLifecycle('all')}><span className="lifecycle-dot all" /><span><strong>全部策略</strong><small>当前工作区全景</small></span><ChevronRight size={14} /></button>{lifecycleStages.map((stage) => <button key={stage.id} className={lifecycle === stage.id ? 'selected' : ''} onClick={() => setLifecycle(stage.id)}><span className={`lifecycle-dot ${stage.color}`} /><span><strong>{stage.label}</strong><small>{stage.short}</small></span><ChevronRight size={14} /></button>)}</aside><section className="strategy-catalog"><div className="catalog-heading"><div><span className="detail-kicker">{activeStage?.short ?? 'FULL LIFECYCLE'}</span><h2>{activeStage?.label ?? '全生命周期策略'}</h2><p>{activeStage?.detail ?? '从接入到线上运行，策略按门禁顺序串成一条可复用的评测链路。'}</p></div><span className="catalog-count">{visibleStrategies.length} 个策略</span></div><div className="strategy-table" role="table" aria-label="评测策略目录"><div className="strategy-table-head" role="row"><span>策略 / 数据集</span><span>执行协议</span><span>评测维度</span><span>触发方式</span><span>结果</span><span aria-hidden="true" /></div>{visibleStrategies.map((strategy) => <div className="strategy-table-row" role="row" key={strategy.name}><div className="strategy-table-name"><span className={`lifecycle-dot ${strategy.tone}`} /><div><strong>{strategy.name}</strong><small>{strategy.dataset}</small></div></div><span className="strategy-table-protocol"><Network size={13} />{strategy.protocol}</span><div className="strategy-table-dimensions">{strategy.dimensions.map((dimension) => <span key={dimension}>{dimension}</span>)}</div><span className="strategy-table-trigger"><Clock3 size={12} />{strategy.trigger}</span><span className={`strategy-result result-${strategy.tone}`}>{strategy.score}</span><button className="table-action" onClick={onNewPolicy} aria-label={`配置${strategy.name}`}><ArrowUpRight size={14} /></button></div>)}</div></section></div> : <div className="dimension-matrix">{dimensions.map((dimension) => <article className={`dimension-card dimension-${dimension.tone}`} key={dimension.name}><div className="dimension-card-icon"><dimension.icon size={17} /></div><div><h3>{dimension.name}</h3><p>{dimension.desc}</p><span>{dimension.applies}</span></div><strong>{dimension.score}<small>/100</small></strong></article>)}</div>}</div>
}

function DatasetsPage({ datasets, onImport, onBenchmark, onNewRun, onNotify: notifyParent }: { datasets: DatasetItem[]; onImport: (dataset: DatasetItem, file?: File) => Promise<void>; onBenchmark: () => Promise<void>; onNewRun: () => void; onNotify: (message: string) => void }) {
  const onNotify = (message: string) => {
    if (message.startsWith('Agentic 数据集需要')) void onBenchmark()
    else notifyParent(message)
  }
  const setDatasets = (updater: (current: DatasetItem[]) => DatasetItem[]) => {
    const imported = updater(datasets)[0]
    if (imported) void onImport(imported, imported.uploadFile)
  }
  const [kind, setKind] = useState<'all' | DatasetKind>('all')
  const [query, setQuery] = useState('')
  const [isImportOpen, setIsImportOpen] = useState(false)
  const [selectedDataset, setSelectedDataset] = useState<DatasetItem | null>(null)
  const visibleDatasets = datasets.filter((dataset) => (kind === 'all' || dataset.kind === kind) && `${dataset.name} ${dataset.desc} ${dataset.type}`.toLowerCase().includes(query.toLowerCase()))
  const kindCards = [
    { id: 'agentic' as const, icon: Network, title: 'Agent 任务集', detail: '多步骤任务 / 工具调用', count: datasets.filter((dataset) => dataset.kind === 'agentic').length, tone: 'teal' },
    { id: 'single-turn' as const, icon: MessageSquareIcon, title: '单轮对话', detail: 'Prompt / Response / Label', count: datasets.filter((dataset) => dataset.kind === 'single-turn').length, tone: 'blue' },
    { id: 'badcase' as const, icon: AlertTriangle, title: '人工失败样本', detail: '线上失败对话 / 人工标注', count: datasets.filter((dataset) => dataset.kind === 'badcase').length, tone: 'coral' },
    { id: 'trace' as const, icon: Activity, title: '失败轨迹样本', detail: '从真实运行中抽取', count: datasets.filter((dataset) => dataset.kind === 'trace').length, tone: 'purple' },
  ]
  return <div className="page-wrap page-datasets"><section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line" />DATASET CATALOG</div><h1>数据集</h1><p>统一管理数据来源、执行协议、schema 版本和评测绑定关系。</p></div><div className="heading-actions"><button className="secondary-btn" onClick={() => onNotify('Agentic 数据集需要通过 Benchmark Adapter 接入，不能按普通对话 JSONL 直接运行')}><Network size={16} />接入 Benchmark</button><button className="primary-btn" onClick={() => setIsImportOpen(true)}><UploadCloud size={16} />上传数据集</button></div></section><section className="dataset-routing"><div className="routing-heading"><div><span className="detail-kicker">DATASET ROUTING</span><h2>数据集类型</h2></div><span>按协议进入不同评测链路</span></div><div className="dataset-kind-grid"><button className={`dataset-kind-card all ${kind === 'all' ? 'selected' : ''}`} onClick={() => setKind('all')}><span className="dataset-kind-icon"><Layers3 size={17} /></span><div><strong>全部数据集</strong><small>工作区数据集总览</small></div><b>{datasets.length}</b></button>{kindCards.map((card) => <button key={card.id} className={`dataset-kind-card ${card.tone} ${kind === card.id ? 'selected' : ''}`} onClick={() => setKind(card.id)}><span className="dataset-kind-icon"><card.icon size={17} /></span><div><strong>{card.title}</strong><small>{card.detail}</small></div><b>{card.count}</b></button>)}</div></section><div className="dataset-toolbar"><div className="dataset-toolbar-copy"><span className="detail-kicker">{kind === 'all' ? 'ALL DATASETS' : kindCards.find((card) => card.id === kind)?.title.toUpperCase()}</span><strong>{visibleDatasets.length} 个数据集</strong></div><div className="dataset-search"><Search size={16} /><input aria-label="搜索数据集" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称、来源或协议…" /></div><button className="text-btn" onClick={() => { setQuery(''); setKind('all') }}>清除筛选</button></div><div className="dataset-list panel">{visibleDatasets.length ? <><div className="dataset-table-head" role="row"><span>数据集</span><span>协议 / 类型</span><span>规模</span><span>版本</span><span>状态</span><span aria-hidden="true" /></div>{visibleDatasets.map((dataset) => <div className="dataset-row" key={dataset.name}><div className={`dataset-icon ${dataset.color}`}><dataset.icon size={19} /></div><div className="dataset-main"><strong>{dataset.name}</strong><span>{dataset.desc}</span></div><div className="dataset-contract"><span>{dataset.type}</span><small>{dataset.protocol}</small></div><span className="dataset-count">{dataset.count}</span><span className="dataset-version">{dataset.version}</span><span className={`dataset-status ${dataset.status === 'Ready' ? 'ready' : 'review'}`}><i />{dataset.status}</span><div className="dataset-row-actions"><button className="table-action" onClick={() => setSelectedDataset(dataset)} aria-label={`查看${dataset.name}详情`}><ArrowUpRight size={14} /></button><button className="table-action" onClick={onNewRun} aria-label={`运行${dataset.name}`}><Play size={13} /></button></div></div>)}</> : <div className="empty-state"><Search size={20} /><strong>没有匹配的数据集</strong><span>尝试切换数据集形态或清除搜索条件</span></div>}</div><div className="dataset-protocol-note"><div className="callout-icon"><ShieldCheck size={19} /></div><div><strong>协议边界</strong><p><b>Agentic Benchmark</b> 要提供任务环境和动作接口，由 Runner 通过 Adapter 驱动；<b>单轮 / Badcase</b> 只需要输入、期望输出和标签，可直接走批量评分器。</p></div><button className="text-btn" onClick={() => onNotify('协议字段：Task / Context / Actions / Observation / Score')}>查看字段 <ArrowUpRight size={14} /></button></div>{selectedDataset && <DatasetInspector dataset={selectedDataset} onClose={() => setSelectedDataset(null)} onRun={onNewRun} />}{isImportOpen && <DatasetImportModal onClose={() => setIsImportOpen(false)} onImported={(dataset) => { setDatasets((current) => [dataset, ...current]); setIsImportOpen(false); onNotify(`${dataset.name} 已导入并通过后端 Schema 校验`) }} />}</div>
}

function DatasetInspector({ dataset, onClose, onRun }: { dataset: DatasetItem; onClose: () => void; onRun: () => void }) {
  const isAgentic = dataset.kind === 'agentic'
  return <Drawer className="mature-dataset-drawer" open onClose={onClose} width={440} title={<span><span className="detail-kicker">DATASET INSPECTOR · {dataset.version}</span><h2 id="dataset-inspector-title">{dataset.name}</h2></span>} footer={<Space><AntButton onClick={onClose}>关闭</AntButton><AntButton type="primary" icon={<Play size={14} />} onClick={onRun}>运行评测</AntButton></Space>}>
    <p className="drawer-description">{dataset.desc}</p>
    <Space className="inspector-status-row" wrap><Tag color={dataset.status === 'Ready' ? 'success' : 'warning'}>{dataset.status}</Tag><Tag>{dataset.type}</Tag><span className="inspector-updated">最近更新 · 2 小时前</span></Space>
    <section className="inspector-section"><span className="detail-kicker">EXECUTION CONTRACT</span><div className="inspector-fields"><div><span>执行协议</span><strong>{dataset.protocol}</strong></div><div><span>评测入口</span><strong>{isAgentic ? 'Runner / Benchmark Adapter' : 'Batch Scorer'}</strong></div><div><span>数据规模</span><strong>{dataset.count}</strong></div><div><span>绑定策略</span><strong>{dataset.evaluation}</strong></div></div></section>
    <section className="inspector-section"><div className="inspector-section-heading"><span className="detail-kicker">SCHEMA CONTRACT</span><span className="schema-version">schema v1.2</span></div><div className="inspector-schema">{(isAgentic ? ['task', 'context', 'expected_actions', 'initial_state'] : ['input', 'actual_output', 'expected_output', 'label', 'notes']).map((field) => <span key={field}><code>{field}</code><small>{isAgentic && field === 'expected_actions' ? 'required · action list' : 'required · string / object'}</small></span>)}</div></section>
    <Alert className="mature-alert" type={isAgentic ? 'warning' : 'info'} showIcon message={isAgentic ? '该数据集不能直接按普通 JSONL 批量评分，需先配置 Benchmark Adapter。' : '该数据集可直接进入单轮评分器，人工标注结果会保留在原始样本旁。'} />
  </Drawer>
}

function DatasetImportModal({ onClose, onImported }: { onClose: () => void; onImported: (dataset: DatasetItem) => void }) {
  const [kind, setKind] = useState<'agentic' | 'badcase'>('badcase')
  const [step, setStep] = useState<1 | 2 | 3>(1)
  const [fileName, setFileName] = useState('')
  const [datasetName, setDatasetName] = useState('')
  const [validationState, setValidationState] = useState<'idle' | 'checking' | 'ready'>('idle')
  const [uploadFile, setUploadFile] = useState<File>()
  const [sampleCount, setSampleCount] = useState(0)

  useEffect(() => {
    const input = document.getElementById('dataset-upload-file') as HTMLInputElement | null
    const captureFile = () => setUploadFile(input?.files?.[0])
    input?.addEventListener('change', captureFile)
    return () => input?.removeEventListener('change', captureFile)
  }, [step])

  const useExample = () => {
    setFileName(kind === 'badcase' ? 'support-badcases.example.jsonl' : 'agentic-tasks.example.jsonl')
    setDatasetName(kind === 'badcase' ? 'support-badcases-new' : 'agentic-benchmark-new')
    setSampleCount(1)
  }
  const nextStep = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (step === 1) {
      if (!fileName) return
      setStep(2)
      setValidationState('checking')
      window.setTimeout(() => setValidationState('ready'), 800)
      return
    }
    if (step === 2) {
      setStep(3)
      return
    }
    const imported: DatasetItem = {
      name: datasetName || (kind === 'badcase' ? 'new-badcases' : 'new-agentic-dataset'),
      type: kind === 'badcase' ? 'Human-curated JSONL' : 'Agentic JSONL',
      desc: kind === 'badcase' ? '人工上传的线上失败样本' : '待接入 Benchmark Adapter 的 Agentic 任务',
      count: kind === 'badcase' ? '0 cases' : '0 tasks',
      version: 'v0.1',
      status: 'Needs review',
      color: kind === 'badcase' ? 'coral' : 'teal',
      icon: kind === 'badcase' ? AlertTriangle : Network,
      kind,
      protocol: kind === 'badcase' ? '单轮 / 对话评测 schema' : 'Benchmark Adapter · 待配置',
      evaluation: kind === 'badcase' ? '持续评测' : '冒烟测试',
      uploadFile,
    }
    onImported(imported)
  }

  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><div className="modal dataset-import-modal" role="dialog" aria-modal="true" aria-labelledby="dataset-import-title"><div className="modal-header"><div><span className="detail-kicker">DATASET INGESTION · STEP 0{step} / 03</span><h2 id="dataset-import-title">上传数据集</h2><p>{step === 1 ? '先选择数据集形态，平台会使用不同的 schema 和执行链路。' : step === 2 ? '确认字段映射，避免把单轮 Badcase 错当成 Agentic 任务执行。' : '确认数据集信息后，将它加入当前工作区目录。'}</p></div><button className="icon-btn" onClick={onClose} aria-label="关闭数据集上传弹窗"><X size={18} /></button></div><div className="registration-progress"><span className={step >= 1 ? 'active' : ''}><b>01</b>选择来源</span><i /><span className={step >= 2 ? 'active' : ''}><b>02</b>校验字段</span><i /><span className={step === 3 ? 'active' : ''}><b>03</b>确认导入</span></div><form onSubmit={nextStep}>{step === 1 && <><div className="import-kind-grid"><button type="button" className={kind === 'agentic' ? 'selected' : ''} onClick={() => { setKind('agentic'); setFileName(''); setDatasetName('') }}><span className="import-kind-icon teal"><Network size={18} /></span><strong>Agentic 数据集</strong><small>tau-bench / 工具调用 / 多步任务</small><b>需要 Adapter</b></button><button type="button" className={kind === 'badcase' ? 'selected' : ''} onClick={() => { setKind('badcase'); setFileName(''); setDatasetName('') }}><span className="import-kind-icon coral"><AlertTriangle size={18} /></span><strong>人工 Badcase / 单轮</strong><small>Prompt / Response / Label</small><b>直接批量评分</b></button></div><div className="upload-dropzone"><UploadCloud size={21} /><strong>{fileName || '选择 .jsonl / .json 文件'}</strong><span>{kind === 'agentic' ? '字段：task、context、expected_actions、initial_state' : '字段：input、actual_output、expected_output、label、notes'}</span><input id="dataset-upload-file" className="visually-hidden" type="file" accept=".jsonl,.json" onChange={(event) => { const file = event.target.files?.[0]; if (file) { setFileName(file.name); setDatasetName(file.name.replace(/\.(jsonl|json)$/i, '')); setUploadFile(file); void file.text().then((text) => setSampleCount(file.name.endsWith('.json') ? (Array.isArray(JSON.parse(text)) ? JSON.parse(text).length : 1) : text.split(/\r?\n/).filter(Boolean).length)).catch(() => setSampleCount(0)) } }} /><label htmlFor="dataset-upload-file" className="secondary-btn">选择文件</label><button type="button" className="text-btn" onClick={useExample}>使用示例文件</button></div><div className="modal-info"><ShieldCheck size={16} /><span>{kind === 'agentic' ? 'Agentic 数据集只登记元数据，真正运行前还需要绑定 Benchmark Adapter。' : 'Badcase 数据集不需要启动环境，直接将输入交给 Agent 并交给评分器 / 人工复核。'}</span></div></>}{step === 2 && <><div className="import-file-summary"><div className="validation-summary-icon"><FileArchive size={18} /></div><div><span className="detail-kicker">SOURCE FILE</span><strong>{fileName}</strong><p>{kind === 'agentic' ? 'Agentic task schema' : 'Single-turn badcase schema'}</p></div><button type="button" className="text-btn" onClick={() => setStep(1)}>返回修改</button></div><div className="import-validation-list"><div className={validationState === 'checking' ? 'checking' : 'passed'}><CheckCircle2 size={15} /><span><strong>文件格式</strong><small>{validationState === 'checking' ? '正在读取 JSONL 行…' : 'JSONL 编码和行结构正常'}</small></span><b>{validationState === 'checking' ? '检查中' : '通过'}</b></div><div className={validationState === 'checking' ? 'checking' : 'passed'}><ShieldCheck size={15} /><span><strong>{kind === 'agentic' ? '协议字段' : '标注字段'}</strong><small>{validationState === 'checking' ? '正在匹配字段 schema…' : kind === 'agentic' ? '识别 task / context / actions 字段' : '识别 input / output / label 字段'}</small></span><b>{validationState === 'checking' ? '检查中' : '通过'}</b></div><div className={validationState === 'checking' ? 'checking' : 'passed'}><Database size={15} /><span><strong>样本统计</strong><small>{validationState === 'checking' ? '正在统计样本数量…' : kind === 'agentic' ? `${sampleCount} 条 Agentic 任务` : `${sampleCount} 条人工样本`}</small></span><b>{validationState === 'checking' ? '检查中' : '待确认'}</b></div></div><div className="schema-boundary"><span className={`schema-boundary-icon ${kind}`}><Network size={15} /></span><div><strong>{kind === 'agentic' ? '将进入 Agentic Runner 链路' : '将进入单轮批量评分链路'}</strong><p>{kind === 'agentic' ? 'Benchmark Adapter → Task → Agent Action → Observation → Score' : 'Input → Agent Response → Evaluator / Human Label → Score'}</p></div></div></>}{step === 3 && <><label>数据集名称<input autoComplete="off" value={datasetName} onChange={(event) => setDatasetName(event.target.value)} placeholder="例如：support-badcases-2026-09…" required /></label><div className="import-review-card"><div><span className="detail-kicker">IMPORT REVIEW</span><strong>{kind === 'agentic' ? 'Agentic 数据集' : '人工 Badcase / 单轮数据集'}</strong><small>{fileName} · {kind === 'agentic' ? `${sampleCount} tasks` : `${sampleCount} cases`} · v0.1</small></div><span className={`release-pill ${kind === 'agentic' ? 'stable' : 'candidate'}`}>{kind === 'agentic' ? '需绑定 Adapter' : '可直接评分'}</span></div><div className="modal-info"><ShieldCheck size={16} /><span>导入后默认为 Needs review。完成字段检查并绑定到生命周期策略后，才会出现在可运行列表。</span></div></>}{step > 1 && validationState === 'checking' && <div className="import-loading" role="status" aria-live="polite"><RefreshCw size={14} className="spin-icon" />正在校验数据集字段…</div>}<div className="modal-footer"><button type="button" className="secondary-btn" onClick={step === 1 ? onClose : () => setStep((current) => (current === 3 ? 2 : 1))}>{step === 1 ? '取消' : '上一步'}</button><button type="submit" className="primary-btn" disabled={(step === 1 && !fileName) || (step === 2 && validationState !== 'ready')}>{step === 1 ? '继续校验' : step === 2 ? '确认字段映射' : '完成导入'}</button></div></form></div></div>
}

function AgentsPage({ agents, policies, onToggle, onDelete, onAdd, onUpdate, onHealthCheck, onRelease, onBind, onRollback, onContinuous, onLoadDetail, onCreateInstance, onInstanceAction, onSaveCredential, onDeleteCredential, onDeploy, onCreateAccessToken, onRevokeAccessToken, onCreateSdkKey, onRevokeSdkKey, onInvoke, onTrace, onRun, onOpenRuns, onNotify }: { agents: Agent[]; policies: ApiPolicy[]; onToggle: (id: string) => void; onDelete: (id: string) => void; onAdd: () => void; onUpdate: (id: string, updates: Partial<Pick<Agent, 'endpoint' | 'environment' | 'owner'>>) => void; onHealthCheck: (id: string) => Promise<void>; onRelease: (id: string, version: string, channel: string, changelog?: string) => Promise<void>; onBind: (id: string, policyId?: string, schedule?: string, failureThreshold?: number, autoRegression?: boolean, notifyOwner?: boolean) => Promise<void>; onRollback: (id: string, version: string) => Promise<void>; onContinuous: (id: string, enabled: boolean) => Promise<void>; onLoadDetail: (id: string) => Promise<ApiAgentDetail>; onCreateInstance: (agentId: string, versionId: string) => Promise<void>; onInstanceAction: (instanceId: string, action: 'start' | 'stop' | 'delete') => Promise<void>; onSaveCredential: (agentId: string, provider: string, value: string) => Promise<void>; onDeleteCredential: (credentialId: string) => Promise<void>; onDeploy: (agentId: string) => Promise<{ access: ApiDeploymentToken; invoke_url: string }>; onCreateAccessToken: (agentId: string, name: string) => Promise<ApiDeploymentToken>; onRevokeAccessToken: (tokenId: string) => Promise<void>; onCreateSdkKey: (agentId: string, name: string) => Promise<ApiSdkKey>; onRevokeSdkKey: (keyId: string) => Promise<void>; onInvoke: (agentId: string, payload: Record<string, unknown>) => Promise<{ output: unknown; latency_ms: number; version: string }>; onTrace: (agentName: string) => void; onRun: (agentName?: string) => void; onOpenRuns: () => void; onNotify: (message: string) => void }) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'all' | AgentStatus>('all')
  const [environmentFilter, setEnvironmentFilter] = useState<'all' | 'production' | 'staging' | 'sandbox'>('all')
  const [showFilters, setShowFilters] = useState(false)
  const [selectedId, setSelectedId] = useState(agents[0]?.id ?? '')
  const [activeTab, setActiveTab] = useState<'overview' | 'versions' | 'evals' | 'runtime' | 'config'>('overview')
  const [agentDetail, setAgentDetail] = useState<ApiAgentDetail>()
  const [continuousEnabled, setContinuousEnabled] = useState(true)
  const [isChecking, setIsChecking] = useState(false)
  const [isConfigOpen, setIsConfigOpen] = useState(false)
  const [activityExpanded, setActivityExpanded] = useState(false)
  const [isReleaseOpen, setIsReleaseOpen] = useState(false)
  const [isBindingOpen, setIsBindingOpen] = useState(false)
  const [rollbackVersion, setRollbackVersion] = useState('')
  const [pipelineStage, setPipelineStage] = useState('production')
  const [configNeedsCheck, setConfigNeedsCheck] = useState(false)
  const [releaseQueued, setReleaseQueued] = useState(false)
  const [candidateVersion, setCandidateVersion] = useState('')
  const [lastRefreshed, setLastRefreshed] = useState('刚刚')
  const [isRefreshing, setIsRefreshing] = useState(false)

  useEffect(() => {
    if (!agents.some((agent) => agent.id === selectedId)) setSelectedId(agents[0]?.id ?? '')
  }, [agents, selectedId])

  useEffect(() => {
    if (!selectedId) return
    void onLoadDetail(selectedId).then(setAgentDetail)
    const interval = window.setInterval(() => void onLoadDetail(selectedId).then(setAgentDetail), 1500)
    return () => window.clearInterval(interval)
  }, [selectedId])

  const filteredAgents = useMemo(() => agents.filter((agent) => {
    const matchesQuery = `${agent.name} ${agent.description} ${agent.mode}`.toLowerCase().includes(query.toLowerCase())
    const matchesEnvironment = environmentFilter === 'all' || agent.environment === environmentFilter
    return matchesQuery && matchesEnvironment && (filter === 'all' || agent.status === filter)
  }), [agents, environmentFilter, filter, query])

  const selectedAgent = filteredAgents.find((agent) => agent.id === selectedId) ?? filteredAgents[0]
  const onlineCount = agents.filter((agent) => agent.status === 'online').length
  const pausedCount = agents.filter((agent) => agent.status === 'paused').length
  const needsReviewCount = agents.filter((agent) => agent.status === 'offline').length
  const isFiltered = Boolean(query) || filter !== 'all' || environmentFilter !== 'all'

  useEffect(() => {
    if (!selectedAgent) return
    setIsConfigOpen(false)
    setIsChecking(false)
    setActivityExpanded(false)
    setRollbackVersion('')
    setIsBindingOpen(false)
    setPipelineStage('production')
    setConfigNeedsCheck(false)
    setReleaseQueued(false)
    setCandidateVersion('')
  }, [selectedAgent?.id])

  const statusLabel = (status: AgentStatus) => status === 'online' ? '在线' : status === 'paused' ? '已暂停' : '待检查'

  const copyEndpoint = async () => {
    if (!selectedAgent) return
    await navigator.clipboard?.writeText(selectedAgent.endpoint).catch(() => undefined)
    onNotify('接入地址已复制')
  }

  const triggerHealthCheck = async () => {
    if (!selectedAgent || isChecking) return
    setIsChecking(true)
    onNotify(`${selectedAgent.name} 正在执行健康检查`)
    await onHealthCheck(selectedAgent.id)
    window.setTimeout(() => {
      setIsChecking(false)
      setConfigNeedsCheck(false)
      onNotify(`${selectedAgent.name} 健康检查通过`)
    }, 1100)
  }

  const refreshStatus = () => {
    if (isRefreshing) return
    setIsRefreshing(true)
    window.setTimeout(() => {
      setIsRefreshing(false)
      setLastRefreshed('刚刚')
      onNotify('Agent 状态已刷新')
    }, 700)
  }

  const selectedNeedsAttention = selectedAgent?.status !== 'online'
  const operationTone = configNeedsCheck || selectedNeedsAttention ? 'warning' : releaseQueued ? 'pending' : 'healthy'
  const operationTitle = configNeedsCheck ? '有一项配置变更待校验' : releaseQueued ? `${candidateVersion} 正在等待快速检查门禁` : selectedAgent?.status === 'paused' ? '当前 Agent 已暂停' : selectedAgent?.status === 'offline' ? '接入点需要首次健康检查' : '当前 Agent 运行正常'
  const operationDetail = configNeedsCheck ? '完成健康检查后，配置才会进入下一个候选版本。' : releaseQueued ? 'Runner 已接收发布任务，评测结果会决定是否继续晋级。' : selectedAgent?.status === 'paused' ? '恢复服务后会重新执行健康检查，持续评测也会保持暂停。' : selectedAgent?.status === 'offline' ? '先完成健康检查，再允许绑定策略或创建发布任务。' : '最近一次状态快照没有发现异常，可以继续查看 Trace 或运行评测。'

  const tabItems = [
    { id: 'overview' as const, label: '概览' },
    { id: 'versions' as const, label: '发布流水线' },
    { id: 'evals' as const, label: '评测策略' },
    { id: 'runtime' as const, label: '实例与密钥' },
    { id: 'config' as const, label: '接入配置' },
  ]

  return <div className="page-wrap page-agents">
    <PageHeading kicker="Agent 工作区" title="管理、部署与评测 Agent" description="从代码包、Git 仓库或 SDK 添加 Agent，在同一个工作区完成部署、运行观测和质量评测。" actions={<button className="primary-btn" onClick={onAdd}><Plus size={18} />添加 Agent</button>} />

    <section className="agent-summary agent-summary-v2">
      <div className="agent-stat"><span className="summary-orb teal"><Bot size={17} /></span><div><small>已添加 Agent</small><strong>{agents.length}</strong></div></div>
      <div className="agent-stat"><span className="summary-orb blue"><CirclePlay size={17} /></span><div><small>在线 Agent</small><strong>{String(onlineCount).padStart(2, '0')}</strong></div></div>
      <div className="agent-stat"><span className="summary-orb amber"><FileArchive size={17} /></span><div><small>待健康检查</small><strong>{String(needsReviewCount).padStart(2, '0')}</strong></div></div>
      <div className="agent-stat agent-stat-last"><span className="summary-orb purple"><Activity size={17} /></span><div><small>已绑定策略</small><strong>{agents.reduce((total, agent) => total + agent.evals, 0)}</strong></div></div>
      <div className="agent-health"><span className="status-pulse" />{pausedCount ? `${pausedCount} 个 Agent 已暂停` : '所有接入点健康检查正常'}</div>
    </section>

    <section className="agent-toolbar">
      <div className="search-field"><Search size={16} /><input aria-label="搜索 Agent" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称、接入方式或描述" /></div>
      <div className="agent-filter-group">
        {([['all', '全部'], ['online', '在线'], ['paused', '已暂停'], ['offline', '待检查']] as const).map(([value, label]) => <button key={value} className={`agent-filter ${filter === value ? 'selected' : ''}`} onClick={() => setFilter(value)}>{label}<span>{value === 'all' ? agents.length : agents.filter((agent) => agent.status === value).length}</span></button>)}
      </div>
      <div className="agent-more-filter-wrap">
        <button className={`filter-btn ${showFilters ? 'active' : ''}`} onClick={() => setShowFilters((current) => !current)}><SlidersHorizontal size={15} />更多筛选</button>
        {showFilters && <div className="agent-filter-popover"><span className="detail-kicker">RUNTIME ENVIRONMENT</span><strong>运行环境</strong><div>{([['all', '全部环境'], ['production', '生产环境'], ['staging', '预发布环境'], ['sandbox', '沙箱环境']] as const).map(([value, label]) => <button key={value} className={environmentFilter === value ? 'selected' : ''} onClick={() => { setEnvironmentFilter(value); setShowFilters(false) }}>{label}{environmentFilter === value && <Check size={13} />}</button>)}</div></div>}
      </div>
      {isFiltered && <button className="text-btn clear-agent-filters" onClick={() => { setQuery(''); setFilter('all'); setEnvironmentFilter('all') }}>清除筛选</button>}
      <div className="agent-toolbar-meta"><span>状态快照 · {lastRefreshed}</span><button className="text-btn" onClick={refreshStatus} disabled={isRefreshing}><RefreshCw size={12} className={isRefreshing ? 'spin-icon' : ''} />{isRefreshing ? '刷新中…' : '刷新状态'}</button></div>
    </section>

    <section className={`agent-operations-strip ${operationTone}`}><span className="operations-strip-icon">{operationTone === 'healthy' ? <CheckCircle2 size={16} /> : operationTone === 'pending' ? <Activity size={16} /> : <AlertTriangle size={16} />}</span><div><span className="detail-kicker">OPERATIONS SIGNAL</span><strong>{operationTitle}</strong><p>{operationDetail}</p></div>{configNeedsCheck ? <button className="text-btn" onClick={() => setActiveTab('config')}>打开配置 <ArrowUpRight size={13} /></button> : releaseQueued ? <button className="text-btn" onClick={() => setActiveTab('versions')}>查看发布 <ArrowUpRight size={13} /></button> : selectedNeedsAttention ? <button className="text-btn" onClick={selectedAgent?.status === 'paused' ? () => onToggle(selectedAgent.id) : triggerHealthCheck} disabled={isChecking}>{selectedAgent?.status === 'paused' ? '恢复 Agent' : '立即检查'} <ArrowUpRight size={13} /></button> : <button className="text-btn" onClick={onOpenRuns}>查看运行 <ArrowUpRight size={13} /></button>}<span className="operations-strip-time">{lastRefreshed}</span></section>

    <section className="agent-workspace">
      <div className="agent-directory panel">
        <div className="directory-heading"><div><span className="detail-kicker">AGENT LIBRARY</span><h2>全部 Agent</h2></div><span className="directory-count">{filteredAgents.length} / {agents.length}</span></div>
        <div className="agent-directory-list">
          {filteredAgents.length ? filteredAgents.map((agent) => <button className={`agent-directory-item ${agent.id === selectedAgent?.id ? 'selected' : ''}`} key={agent.id} onClick={() => { setSelectedId(agent.id); setActiveTab('overview') }}>
            <div className="agent-avatar-large" style={{ background: agent.accent }}>{agent.name.slice(0, 1)}</div>
            <div className="directory-item-copy"><div><strong>{agent.name}</strong><span className={`agent-status ${agent.status}`}><i />{statusLabel(agent.status)}</span></div><p>{agent.mode} · {agent.version}</p><small><span className={`environment-chip ${agent.environment}`}>{agent.environment}</span><Clock3 size={11} />{agent.lastRun}</small></div>
            <ChevronRight size={16} className="directory-chevron" />
          </button>) : <div className="agent-empty"><Search size={20} /><strong>没有匹配的 Agent</strong><span>试试其他关键词或状态筛选</span></div>}
        </div>
        <button className="directory-add" onClick={onAdd}><Plus size={15} />添加新 Agent</button>
      </div>

      {selectedAgent && <div className="agent-detail panel">
        <div className="agent-detail-hero">
          <div className="agent-detail-identity"><div className="agent-avatar-xl" style={{ background: selectedAgent.accent }}>{selectedAgent.name.slice(0, 1)}</div><div><div className="detail-kicker">{selectedAgent.mode} · {selectedAgent.id}</div><div className="agent-detail-title"><h2>{selectedAgent.name}</h2><span className={`agent-status ${selectedAgent.status}`}><i />{statusLabel(selectedAgent.status)}</span></div><p>{selectedAgent.description}</p><div className="agent-identity-meta"><span className={`environment-chip ${selectedAgent.environment}`}>{selectedAgent.environment}</span><span><Users size={13} />{selectedAgent.owner}</span><span><Clock3 size={13} />最近运行 {selectedAgent.lastRun}</span></div><div className="agent-desired-state"><div><span>当前版本</span><strong>{selectedAgent.version}</strong></div><ArrowRight size={15} /><div><span>目标版本</span><strong>{releaseQueued ? candidateVersion : selectedAgent.version}</strong></div><b className={releaseQueued || configNeedsCheck ? 'drift' : ''}>{configNeedsCheck ? '配置待校验' : releaseQueued ? '待晋级' : '已同步'}</b></div></div></div>
          <div className="agent-detail-actions"><button className="small-action" onClick={() => onToggle(selectedAgent.id)}>{selectedAgent.status === 'paused' ? <CirclePlay size={14} /> : <CirclePause size={14} />}{selectedAgent.status === 'paused' ? '恢复' : '暂停'}</button><button className="small-action" onClick={() => onTrace(selectedAgent.name)}><ExternalLink size={14} />查看 Trace</button><button className="small-action danger" onClick={() => onDelete(selectedAgent.id)}><Archive size={14} />删除</button><button className="primary-btn compact-btn" onClick={() => onRun(`${selectedAgent.name} / ${selectedAgent.version}`)}><Play size={14} />运行评测</button></div>
        </div>
        <div className="agent-tabs">{tabItems.map((tab) => <button key={tab.id} className={activeTab === tab.id ? 'active' : ''} onClick={() => setActiveTab(tab.id)}>{tab.label}{tab.id === 'evals' && <span>{selectedAgent.evals}</span>}</button>)}</div>

        {activeTab === 'overview' && <div className="agent-tab-content">
          <AgentReleasePipeline agent={selectedAgent} selectedStage={pipelineStage} releaseQueued={releaseQueued} candidateVersion={candidateVersion} onSelectStage={setPipelineStage} onRelease={() => setIsReleaseOpen(true)} onOpenEvals={() => setActiveTab('evals')} onOpenRuns={onOpenRuns} onTrace={() => onTrace(selectedAgent.name)} />
          <div className="agent-detail-metrics"><div><span>近 30 天成功率</span><strong>{selectedAgent.success}<small> +6.2%</small></strong><em>较上周期</em></div><div><span>P95 响应延迟</span><strong>{selectedAgent.latency}</strong><em>过去 24 小时</em></div><div><span>已绑定策略</span><strong>{selectedAgent.evals}<small> 个</small></strong><em>包含 3 个持续任务</em></div><div><span>当前版本</span><strong>{selectedAgent.version}</strong><em>stable channel</em></div></div>
          <div className="agent-detail-grid">
            <div className="agent-health-card"><div className="subpanel-heading"><div><span className="detail-kicker">HEALTH CHECK</span><h3>运行健康度</h3></div><div className="health-card-actions"><button className="text-btn health-check-trigger" onClick={triggerHealthCheck} disabled={isChecking}><RefreshCw size={12} className={isChecking ? 'spin-icon' : ''} />{isChecking ? '检查中…' : '立即检查'}</button><span className={`health-chip ${isChecking ? 'checking' : ''}`}><i />{isChecking ? 'Checking' : selectedAgent.status === 'paused' ? '已暂停' : selectedAgent.status === 'offline' ? '待检查' : 'Healthy'}</span></div></div><div className="health-score-row"><div className="health-score-ring"><strong>{isChecking ? '…' : selectedAgent.status === 'online' ? '98' : selectedAgent.status === 'paused' ? '—' : '0'}</strong><span>/100</span></div><div><strong className="health-summary">{isChecking ? '正在探测接入点' : selectedAgent.status === 'online' ? '接入点运行稳定' : selectedAgent.status === 'paused' ? '恢复后将重新检查' : '等待首次检查'}</strong><p>最近一次探测：{isChecking ? '正在执行' : selectedAgent.status === 'online' ? '2 分钟前' : '尚未执行'}</p></div></div><div className="health-check-list"><div><CheckCircle2 size={14} /><span>Endpoint 可达性</span><strong>{isChecking ? '检查中' : selectedAgent.status === 'online' ? '通过' : '待检查'}</strong></div><div><ShieldCheck size={14} /><span>权限与密钥校验</span><strong>{isChecking ? '检查中' : selectedAgent.status === 'online' ? '通过' : '待检查'}</strong></div><div><Timer size={14} /><span>响应时间预算</span><strong>{isChecking ? '—' : selectedAgent.status === 'online' ? '1.8s / 5s' : '—'}</strong></div></div></div>
            <div className="agent-eval-card"><div className="subpanel-heading"><div><span className="detail-kicker">EVALUATION SIGNAL</span><h3>质量趋势</h3></div><button className="text-btn" onClick={() => setActiveTab('evals')}>查看评测 <ArrowUpRight size={13} /></button></div><div className="quality-chart"><div className="quality-y-axis"><span>100</span><span>80</span><span>60</span></div><div className="quality-chart-area"><div className="chart-grid-line line-top" /><div className="chart-grid-line line-mid" /><div className="chart-grid-line line-bottom" /><svg viewBox="0 0 360 108" preserveAspectRatio="none" role="img" aria-label="Agent 质量趋势"><defs><linearGradient id="agentQualityFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#49bfa0" stopOpacity=".28" /><stop offset="100%" stopColor="#49bfa0" stopOpacity="0" /></linearGradient></defs><path d="M0 78 C34 75 39 61 72 66 S110 76 142 51 S183 58 211 44 S254 51 282 25 S328 36 360 18 L360 108 L0 108 Z" fill="url(#agentQualityFill)" /><path d="M0 78 C34 75 39 61 72 66 S110 76 142 51 S183 58 211 44 S254 51 282 25 S328 36 360 18" fill="none" stroke="#0f766e" strokeWidth="3" strokeLinecap="round" /></svg><div className="quality-x-axis"><span>08/29</span><span>09/01</span><span>09/04</span></div></div></div><div className="quality-foot"><span><i />任务成功率</span><strong>{selectedAgent.success} <small>当前</small></strong></div></div>
          </div>
          <div className="agent-endpoint-card"><div><span className="detail-kicker">ACTIVE REVISION</span><h3>{selectedAgent.version} · stable</h3><p><Server size={13} />{selectedAgent.endpoint}</p></div><div className="endpoint-actions"><button className="small-action" onClick={copyEndpoint}><Copy size={13} />复制地址</button><button className="small-action" onClick={() => setActiveTab('config')}>配置详情 <ChevronRight size={13} /></button></div></div>
          <div className={`continuous-card ${continuousEnabled ? 'enabled' : ''}`}><div className="continuous-icon"><Activity size={17} /></div><div className="continuous-copy"><div><span className="detail-kicker">CONTINUOUS EVALUATION</span><h3>持续评测策略</h3></div><p>每次发布或每日定时运行回归集，质量低于阈值时提醒负责人。</p><div className="continuous-meta"><span><Clock3 size={12} />每 6 小时</span><span><Database size={12} />3 个数据集</span><span><AlertTriangle size={12} />阈值 80%</span></div></div><button className={`toggle-switch ${continuousEnabled ? 'on' : ''}`} onClick={() => { const enabled = !continuousEnabled; setContinuousEnabled(enabled); void onContinuous(selectedAgent.id, enabled); onNotify(`持续评测已${enabled ? '开启' : '暂停'}`) }} aria-label={continuousEnabled ? '暂停持续评测' : '开启持续评测'} aria-pressed={continuousEnabled}><span /></button></div>
          <div className="agent-activity-card"><div className="subpanel-heading"><div><span className="detail-kicker">OPERATIONAL ACTIVITY</span><h3>最近活动</h3></div><span className="activity-period">最近 7 天</span></div><div className="activity-list"><div className="activity-row"><span className="activity-icon teal"><GitBranch size={13} /></span><div><strong>{selectedAgent.version} 已发布到 stable</strong><small>由 {selectedAgent.owner} 发布 · 经过 12 项检查</small></div><time>2 小时前</time></div><div className="activity-row"><span className="activity-icon blue"><CirclePlay size={13} /></span><div><strong>持续评测运行完成</strong><small>tau2-retail-smoke · 30 tasks · 84% 通过</small></div><time>昨天 18:20</time></div><div className="activity-row"><span className="activity-icon amber"><ShieldCheck size={13} /></span><div><strong>权限策略已更新</strong><small>新增 order.search 与 policy.lookup 工具</small></div><time>09/02 14:06</time></div>{activityExpanded && <div className="activity-row"><span className="activity-icon purple"><Activity size={13} /></span><div><strong>健康检查完成</strong><small>Endpoint 响应 182ms · 3 项检查全部通过</small></div><time>09/01 09:32</time></div>}</div><button className="activity-footer" onClick={() => setActivityExpanded((current) => !current)}>{activityExpanded ? '收起活动' : '查看完整活动'} <ArrowUpRight size={13} /></button></div>
        </div>}



        {activeTab === 'versions' && <AgentVersionsPanel agent={selectedAgent} detail={agentDetail} onRelease={() => setIsReleaseOpen(true)} onRollback={setRollbackVersion} />}

        {activeTab === 'evals' && <AgentBindingsPanel agent={selectedAgent} detail={agentDetail} onBind={() => setIsBindingOpen(true)} onRun={() => onRun(`${selectedAgent.name} / ${selectedAgent.version}`)} />}

        {activeTab === 'runtime' && <AgentRuntimeLivePanel agent={selectedAgent} detail={agentDetail} onRefresh={() => void onLoadDetail(selectedAgent.id).then(setAgentDetail)} onCreateInstance={onCreateInstance} onInstanceAction={onInstanceAction} onSaveCredential={onSaveCredential} onDeleteCredential={onDeleteCredential} onDeploy={onDeploy} onCreateAccessToken={onCreateAccessToken} onRevokeAccessToken={onRevokeAccessToken} onCreateSdkKey={onCreateSdkKey} onRevokeSdkKey={onRevokeSdkKey} onInvoke={onInvoke} onNotify={onNotify} />}

        {activeTab === 'config' && <div className="agent-tab-content"><div className="tab-title-row"><div><span className="detail-kicker">CONNECTION CONFIG</span><h3>接入配置</h3><p>详情页只展示当前生效配置；修改会创建一条待校验的配置变更。</p></div><button className="secondary-btn" onClick={() => setIsConfigOpen(true)}><Settings2 size={14} />编辑接入配置</button></div>{configNeedsCheck && <div className="config-pending-banner"><RefreshCw size={15} /><div><strong>配置变更待校验</strong><span>运行健康检查后，才可用于下一个候选版本。</span></div><button className="text-btn" onClick={triggerHealthCheck} disabled={isChecking}>{isChecking ? '检查中…' : '立即校验'}</button></div>}<div className="config-grid"><div className="config-field"><span>接入方式</span><strong><Layers3 size={14} />{selectedAgent.mode}</strong></div><div className="config-field"><span>运行环境</span><strong><Cpu size={14} />{selectedAgent.environment}</strong></div><div className="config-field wide"><span>Endpoint / 镜像地址</span><strong className="mono-value">{selectedAgent.endpoint}<button onClick={copyEndpoint} aria-label="复制接入地址"><Copy size={13} /></button></strong></div><div className="config-field"><span>负责人</span><strong><Users size={14} />{selectedAgent.owner}</strong></div><div className="config-field"><span>超时预算</span><strong><Timer size={14} />30s / task</strong></div><div className="config-field"><span>最近配置校验</span><strong className={configNeedsCheck ? 'config-check-pending' : ''}>{configNeedsCheck ? <RefreshCw size={14} /> : <CheckCircle2 size={14} />}{configNeedsCheck ? '待校验 · 刚刚' : '已通过 · 2 分钟前'}</strong></div><div className="config-note"><ShieldCheck size={15} /><span>正式运行前会执行密钥脱敏、镜像扫描、网络策略和健康检查。配置修改不会直接改变生产流量。</span></div></div></div>}
      </div>}
    </section>
    {isReleaseOpen && <AgentReleaseModal agent={selectedAgent} onClose={() => setIsReleaseOpen(false)} onRelease={(version, channel, changelog) => { void onRelease(selectedAgent.id, version, channel, changelog); setCandidateVersion(version); setReleaseQueued(true); setPipelineStage('smoke'); setIsReleaseOpen(false); onNotify(`${version} 发布任务已创建，已进入 Smoke 门禁${channel === 'stable' ? '，正式版本已切换' : ''}`) }} />}
    {isBindingOpen && <AgentEvaluationBindingModal agent={selectedAgent} policies={policies} onClose={() => setIsBindingOpen(false)} onBind={(payload) => { void onBind(selectedAgent.id, payload.policyId, payload.schedule, payload.failureThreshold, payload.autoRegression, payload.notifyOwner); setIsBindingOpen(false); onNotify(`${selectedAgent?.name ?? 'Agent'} 评测策略绑定已创建`) }} />}
    {rollbackVersion && <AgentRollbackModal agent={selectedAgent} version={rollbackVersion} onClose={() => setRollbackVersion('')} onConfirm={() => { void onRollback(selectedAgent.id, rollbackVersion); setRollbackVersion(''); onNotify(`${rollbackVersion} 回滚任务已创建`) }} />}
    {isConfigOpen && <AgentConfigModal agent={selectedAgent} onClose={() => setIsConfigOpen(false)} onSave={(updates) => { onUpdate(selectedAgent.id, updates); setConfigNeedsCheck(true); setIsConfigOpen(false); onNotify('配置已保存，等待健康检查') }} />}
  </div>
}

function AgentVersionsPanel({ agent, detail, onRelease, onRollback }: { agent: Agent; detail?: ApiAgentDetail; onRelease: () => void; onRollback: (version: string) => void }) {
  return <div className="agent-tab-content"><div className="tab-title-row"><div><span className="detail-kicker">VERSIONS</span><h3>版本记录</h3><p>版本、来源和发布状态统一在这里审计。</p></div><button className="primary-btn compact-btn" onClick={onRelease}><Plus size={14} />发布新版本</button></div><div className="version-table"><div className="version-table-head"><span>版本</span><span>来源</span><span>状态</span><span>创建时间</span><span>操作</span></div>{detail?.versions.length ? detail.versions.map((version) => <div className="version-row" key={version.id}><div><strong>{version.version}</strong><small>{version.source_digest || version.id}</small></div><span>{version.source_type}</span><span className={`release-pill ${version.id === agent.versionId ? 'stable' : ''}`}>{version.id === agent.versionId ? '当前' : version.status}</span><span>{version.created_at}</span><button className="text-btn" disabled={version.id === agent.versionId} onClick={() => onRollback(version.version)}>回滚到此版本</button></div>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无版本记录" />}</div></div>
}

function AgentBindingsPanel({ agent, detail, onBind, onRun }: { agent: Agent; detail?: ApiAgentDetail; onBind: () => void; onRun: () => void }) {
  return <div className="agent-tab-content"><div className="tab-title-row"><div><span className="detail-kicker">EVALUATION BINDINGS</span><h3>已绑定评测</h3><p>查看 {agent.name} 当前版本关联的数据集、触发方式和失败阈值。</p></div><button className="primary-btn compact-btn" onClick={onBind}><Plus size={14} />绑定评测</button></div><div className="version-table"><div className="version-table-head"><span>策略</span><span>生命周期</span><span>数据集</span><span>触发方式</span><span>操作</span></div>{detail?.bindings.length ? detail.bindings.map((binding) => <div className="version-row" key={binding.id}><div><strong>{binding.policy_name}</strong><small>{binding.id}</small></div><span>{binding.lifecycle}</span><span>{binding.dataset_name}@{binding.dataset_version}</span><span>{binding.trigger_type}</span><button className="text-btn" onClick={onRun}>立即运行</button></div>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无评测绑定" />}</div></div>
}

type AgentRuntimeLiveProps = ComponentProps<typeof AgentRuntimePanel> & {
  onDeploy: (agentId: string) => Promise<{ access: ApiDeploymentToken; invoke_url: string }>
  onCreateAccessToken: (agentId: string, name: string) => Promise<ApiDeploymentToken>
  onRevokeAccessToken: (tokenId: string) => Promise<void>
  onCreateSdkKey: (agentId: string, name: string) => Promise<ApiSdkKey>
  onRevokeSdkKey: (keyId: string) => Promise<void>
  onInvoke: (agentId: string, payload: Record<string, unknown>) => Promise<{ output: unknown; latency_ms: number; version: string }>
}

function AgentRuntimeLivePanel(props: AgentRuntimeLiveProps) {
  const [issuedToken, setIssuedToken] = useState('')
  const [issuedSdkKey, setIssuedSdkKey] = useState('')
  const [playgroundInput, setPlaygroundInput] = useState('查询订单 A001 是否可以退款')
  const [playgroundOutput, setPlaygroundOutput] = useState('')
  const [isInvoking, setIsInvoking] = useState(false)
  const [isDeploying, setIsDeploying] = useState(false)
  const revoke = async (credentialId: string) => {
    await props.onDeleteCredential(credentialId)
    props.onRefresh()
  }
  const createAccessToken = async () => {
    const created = await props.onCreateAccessToken(props.agent.id, '业务调用 Token')
    setIssuedToken(created.token || '')
    props.onRefresh()
  }
  const deploy = async () => {
    setIsDeploying(true)
    try {
      const result = await props.onDeploy(props.agent.id)
      setIssuedToken(result.access.token || '')
      window.setTimeout(props.onRefresh, 400)
      props.onNotify('部署命令已提交，调用 Token 已生成')
    } finally {
      setIsDeploying(false)
    }
  }
  const createSdkKey = async () => {
    const created = await props.onCreateSdkKey(props.agent.id, '轮换 SDK 密钥')
    setIssuedSdkKey(created.key || '')
    props.onRefresh()
  }
  const invoke = async () => {
    setIsInvoking(true)
    try {
      const result = await props.onInvoke(props.agent.id, { input: playgroundInput })
      setPlaygroundOutput(JSON.stringify(result, null, 2))
      props.onRefresh()
    } catch (error) {
      setPlaygroundOutput(error instanceof Error ? error.message : '调用失败')
    } finally {
      setIsInvoking(false)
    }
  }
  if (props.agent.mode === 'SDK 接入') {
    const sdkCode = `from agent_eval import PlatformSink, configure, observe as platform_observe\nfrom deepeval.tracing import observe as deepeval_observe\n\nconfigure(sinks=[PlatformSink(\n    "${window.location.origin}",\n    "${issuedSdkKey || 'evk_...'}",\n)])\n\n@platform_observe(kind="agent", name="my_agent")\n@deepeval_observe(type="agent")\ndef my_agent(task):\n    ...`
    return <div className="agent-tab-content sdk-runtime-panel"><div className="tab-title-row"><div><span className="detail-kicker">SDK TELEMETRY</span><h3>SDK 接入与 Trace 上报</h3><p>Agent 保持在你的运行环境；本平台只接收结构化 Trace 和评测事件。</p></div><button className="primary-btn compact-btn" onClick={() => void createSdkKey()}><Plus size={14} />生成新密钥</button></div><div className="config-grid"><div className="config-field wide"><span>Trace 上报地址</span><strong className="mono-value">{`${window.location.origin}/v1/traces`}</strong></div><div className="config-field"><span>已接收事件</span><strong>{props.detail?.sdk_trace_count ?? 0}</strong></div><div className="config-field"><span>协议</span><strong>NDJSON v1</strong></div></div>{issuedSdkKey && <div className="sdk-credential-row"><div><span>新 Agent SDK Key · 仅显示一次</span><code>{issuedSdkKey}</code></div><button className="secondary-btn" onClick={() => void navigator.clipboard?.writeText(issuedSdkKey)}><Copy size={15} />复制密钥</button></div>}<div className="sdk-code-block"><div><span>Python 配置</span><button onClick={() => void navigator.clipboard?.writeText(sdkCode)}><Copy size={14} />复制代码</button></div><pre>{sdkCode}</pre></div><div className="version-table"><div className="version-table-head"><span>SDK 密钥</span><span>末四位</span><span>创建时间</span><span>状态</span><span>操作</span></div>{props.detail?.sdk_keys.length ? props.detail.sdk_keys.map((key) => <div className="version-row" key={key.id}><div><strong>{key.name}</strong><small>{key.id}</small></div><strong>•••• {key.last_four}</strong><span>{new Date(key.created_at).toLocaleString('zh-CN', { hour12: false })}</span><span className={`release-pill ${key.revoked_at ? '' : 'stable'}`}>{key.revoked_at ? '已撤销' : '可用'}</span><button className="text-btn" disabled={Boolean(key.revoked_at)} onClick={() => void props.onRevokeSdkKey(key.id).then(props.onRefresh)}>撤销</button></div>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无 SDK 密钥" />}</div><div className="sdk-separation-note"><ShieldCheck size={17} /><div><strong>SDK 密钥不能调用 Agent</strong><span>它只允许向当前 Agent 写入 Trace。业务调用仍使用部署 Token，模型密钥由 Agent 自己或平台密钥库管理。</span></div></div></div>
  }
  return <>
    <AgentRuntimePanel {...props} />
    <div className="agent-tab-content">
      <div className="tab-title-row"><div><span className="detail-kicker">SERVICE GATEWAY</span><h3>服务调用与 Playground</h3><p>这里调用的就是当前运行实例；评测任务也优先复用同一实例。</p></div><div className="heading-actions"><button className="primary-btn compact-btn" onClick={() => void deploy()} disabled={isDeploying}><Server size={14} />{isDeploying ? '部署中…' : '一键部署并生成 Token'}</button><button className="secondary-btn" onClick={createAccessToken}><ShieldCheck size={14} />追加 Token</button></div></div>
      <div className="config-grid">
        <div className="config-field wide"><span>稳定调用地址</span><strong className="mono-value">{`${window.location.origin}/v1/agents/${props.agent.id}/invoke`}</strong></div>
        <div className="config-field"><span>运行实例</span><strong>{props.detail?.instances.find((instance) => instance.status === 'running')?.id ?? '未启动'}</strong></div>
      </div>
      {issuedToken && <div className="modal-info warning"><ShieldCheck size={16} /><span><strong>请立即保存：{issuedToken}</strong><br />Token 仅本次显示，刷新后只保留末四位。<pre>{`curl -X POST '${window.location.origin}/v1/agents/${props.agent.id}/invoke' \\\n  -H 'Authorization: Bearer ${issuedToken}' \\\n  -H 'Content-Type: application/json' \\\n  -d '{"input":"查询订单 A001"}'`}</pre></span></div>}
      <div className="config-grid">
        <div className="config-field wide"><span>调用输入</span><textarea rows={3} value={playgroundInput} onChange={(event) => setPlaygroundInput(event.target.value)} /></div>
        <button className="primary-btn" onClick={() => void invoke()} disabled={isInvoking || !props.detail?.instances.some((instance) => instance.status === 'running')}><Play size={14} />{isInvoking ? '调用中…' : '调用当前实例'}</button>
        <div className="config-field wide"><span>调用结果</span><pre className="mono-value">{playgroundOutput || '等待调用'}</pre></div>
      </div>
      <div className="version-table">
        <div className="version-table-head"><span>Token</span><span>末四位</span><span>创建时间</span><span>状态</span><span>操作</span></div>
        {props.detail?.access_tokens.length ? props.detail.access_tokens.map((token) => <div className="version-row" key={token.id}><div><strong>{token.name}</strong><small>{token.id}</small></div><strong>•••• {token.last_four}</strong><span>{new Date(token.created_at).toLocaleString('zh-CN', { hour12: false })}</span><span className={`release-pill ${token.revoked_at ? '' : 'stable'}`}>{token.revoked_at ? '已撤销' : '可用'}</span><button className="text-btn" disabled={Boolean(token.revoked_at)} onClick={() => void props.onRevokeAccessToken(token.id).then(props.onRefresh)}>撤销</button></div>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无调用 Token" />}
      </div>
      <div className="version-table">
        <div className="version-table-head"><span>最近调用</span><span>来源</span><span>状态</span><span>延迟</span><span>时间</span></div>
        {props.detail?.invocations.length ? props.detail.invocations.slice(0, 5).map((invocation) => <div className="version-row" key={invocation.id}><div><strong>{invocation.id}</strong><small>{invocation.instance_id}</small></div><span>{invocation.caller_type}</span><span className={`release-pill ${invocation.status === 'completed' ? 'stable' : ''}`}>{invocation.status}</span><strong>{invocation.latency_ms}ms</strong><span>{new Date(invocation.created_at).toLocaleString('zh-CN', { hour12: false })}</span></div>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无调用记录" />}
      </div>
    </div>
    <div className="agent-tab-content">
      <div className="tab-title-row"><div><span className="detail-kicker">SECRET INVENTORY</span><h3>已保存密钥</h3><p>只返回 Provider、名称与末四位；密文不会通过 API 回传。</p></div></div>
      <div className="version-table">
        <div className="version-table-head"><span>名称</span><span>Provider</span><span>末四位</span><span>更新时间</span><span>操作</span></div>
        {props.detail?.credentials.length ? props.detail.credentials.map((credential) => <div className="version-row" key={credential.id}>
          <div><strong>{credential.name}</strong><small>{credential.id}</small></div>
          <span>{credential.provider}</span>
          <strong>•••• {credential.last_four}</strong>
          <span>{new Date(credential.updated_at).toLocaleString('zh-CN', { hour12: false })}</span>
          <button className="text-btn" onClick={() => void revoke(credential.id)}>撤销</button>
        </div>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无密钥" />}
      </div>
    </div>
  </>
}

function AgentRuntimePanel({ agent, detail, onRefresh, onCreateInstance, onInstanceAction, onSaveCredential, onDeleteCredential: _onDeleteCredential, onNotify }: { agent: Agent; detail?: ApiAgentDetail; onRefresh: () => void; onCreateInstance: (agentId: string, versionId: string) => Promise<void>; onInstanceAction: (instanceId: string, action: 'start' | 'stop' | 'delete') => Promise<void>; onSaveCredential: (agentId: string, provider: string, value: string) => Promise<void>; onDeleteCredential: (credentialId: string) => Promise<void>; onNotify: (message: string) => void }) {
  const [provider, setProvider] = useState('openai')
  const [apiKey, setApiKey] = useState('')
  const currentVersion = detail?.versions.find((version) => version.id === agent.versionId) ?? detail?.versions[0]
  const submitCredential = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!apiKey) return
    await onSaveCredential(agent.id, provider, apiKey)
    setApiKey('')
  }
  const createInstance = async () => {
    if (!currentVersion) return onNotify('请先创建 AgentVersion')
    await onCreateInstance(agent.id, currentVersion.id)
    window.setTimeout(onRefresh, 300)
    onNotify('Agent 实例创建命令已提交')
  }
  const act = async (instanceId: string, action: 'start' | 'stop' | 'delete') => {
    await onInstanceAction(instanceId, action)
    window.setTimeout(onRefresh, 300)
    onNotify(`实例${action === 'start' ? '启动' : action === 'stop' ? '停止' : '删除'}命令已提交`)
  }
  return <div className="agent-tab-content"><div className="tab-title-row"><div><span className="detail-kicker">RUNTIME & CREDENTIALS</span><h3>实例与密钥</h3><p>实例由 Worker 在执行面创建；API Key 加密保存，前端只提交一次且不会回显。</p></div><button className="primary-btn compact-btn" onClick={createInstance}><Plus size={14} />创建实例</button></div><div className="config-grid"><div className="config-field"><span>当前版本</span><strong>{currentVersion?.version ?? '—'}</strong></div><div className="config-field"><span>实例数量</span><strong>{detail?.instances.length ?? agent.instanceCount ?? 0}</strong></div><div className="config-field wide"><span>Runtime</span><strong>{detail?.instances[0]?.runtime_backend ?? 'local / kubernetes 可切换'}</strong></div></div><div className="version-table"><div className="version-table-head"><span>实例</span><span>状态</span><span>Runtime</span><span>Endpoint</span><span>操作</span></div>{detail?.instances.length ? detail.instances.map((instance) => <div className="version-row" key={instance.id}><div><strong>{instance.id}</strong><small>{instance.agent_version_id}</small></div><span className={`release-pill ${instance.status === 'running' ? 'stable' : ''}`}>{instance.status}</span><span>{instance.runtime_backend}</span><strong>{instance.endpoint || '—'}</strong><span>{instance.status === 'running' ? <button className="text-btn" onClick={() => void act(instance.id, 'stop')}>停止</button> : <button className="text-btn" onClick={() => void act(instance.id, 'start')}>启动</button>}<button className="text-btn" onClick={() => void act(instance.id, 'delete')}>删除</button></span></div>) : <div className="empty-state"><Server size={20} /><strong>暂无运行实例</strong><span>创建后由执行面异步启动</span></div>}</div><form className="config-grid" onSubmit={submitCredential}><div className="config-field"><span>Provider</span><select value={provider} onChange={(event) => setProvider(event.target.value)}><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="deepseek">DeepSeek</option><option value="custom">Custom</option></select></div><div className="config-field wide"><span>API Key</span><input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="仅提交时传输，保存后不回显" /></div><button className="secondary-btn" type="submit" disabled={!apiKey}><ShieldCheck size={14} />加密保存密钥</button></form></div>
}

function AgentReleasePipeline({ agent, selectedStage, releaseQueued, candidateVersion, onSelectStage, onRelease, onOpenEvals, onOpenRuns, onTrace }: { agent: Agent; selectedStage: string; releaseQueued: boolean; candidateVersion: string; onSelectStage: (stage: string) => void; onRelease: () => void; onOpenEvals: () => void; onOpenRuns: () => void; onTrace: () => void }) {
  const stages = [
    { id: 'prepare', label: '候选版本', detail: releaseQueued ? `${candidateVersion} · 已创建` : 'Revision 固定', icon: GitBranch },
    { id: 'smoke', label: '快速检查', detail: releaseQueued ? '执行器准备中' : '30 / 30 通过', icon: CheckCircle2 },
    { id: 'regression', label: '版本对比', detail: `${agent.success} · 28 次运行`, icon: Activity },
    { id: 'canary', label: '灰度发布', detail: releaseQueued ? '尚未开始' : agent.environment === 'production' ? '已完成灰度' : '等待灰度', icon: Zap },
    { id: 'production', label: '生产环境', detail: releaseQueued ? '当前稳定版本' : agent.environment === 'production' ? '当前接收流量' : '未发布', icon: Server },
  ]
  const activeIndex = releaseQueued ? 1 : agent.environment === 'production' ? 4 : agent.environment === 'staging' ? 3 : 2
  const selectedIndex = stages.findIndex((stage) => stage.id === selectedStage)
  const selected = stages[selectedIndex] ?? stages[activeIndex]
  const selectedIsLocked = selectedIndex > activeIndex

  return <section className="release-pipeline-card"><div className="pipeline-heading"><div><span className="detail-kicker">RELEASE PIPELINE</span><h3>发布流水线</h3><p>{releaseQueued ? `${candidateVersion} · candidate · 等待 Smoke 门禁` : `${agent.version} · ${agent.environment} · 由门禁控制晋级`}</p></div><button className="secondary-btn pipeline-action" onClick={onRelease}><Plus size={14} />创建候选版本</button></div><div className="pipeline-track">{stages.map((stage, index) => { const Icon = stage.icon; const isDone = index < activeIndex; const isActive = index === activeIndex; return <button key={stage.id} className={`pipeline-stage ${isDone ? 'done' : ''} ${isActive ? 'active' : ''} ${selectedStage === stage.id ? 'selected' : ''}`} onClick={() => onSelectStage(stage.id)} aria-pressed={selectedStage === stage.id}><span className="pipeline-stage-marker"><Icon size={14} /></span><span className="pipeline-stage-copy"><strong>{stage.label}</strong><small>{stage.detail}</small></span>{index < stages.length - 1 && <i className={`pipeline-connector ${index < activeIndex ? 'done' : ''}`} />}</button> })}</div><div className={`pipeline-inspector ${selectedIsLocked ? 'locked' : ''}`}><div><span className="detail-kicker">{selectedIsLocked ? 'GATE LOCKED' : 'CURRENT STAGE'}</span><strong>{selected.label}</strong><p>{selectedIsLocked ? `需要先完成 ${stages[activeIndex].label}，当前阶段尚未开放。` : releaseQueued && selected.id === 'smoke' ? 'Smoke 门禁已创建，Runner 正在准备 30 个任务。完成后会自动进入 Regression。' : selected.id === 'production' ? '当前版本已进入生产，可从 Trace 和线上指标继续观察。' : selected.id === 'regression' ? '回归门禁已绑定 3 个数据集，最近一次通过率高于 80% 阈值。' : `${selected.label} 已记录在当前发布链路中。`}</p></div><div className="pipeline-inspector-actions">{releaseQueued && selected.id === 'smoke' && !selectedIsLocked ? <button className="small-action" onClick={onOpenRuns}><Activity size={13} />查看实验运行</button> : selected.id === 'production' && !selectedIsLocked ? <button className="small-action" onClick={onTrace}><ExternalLink size={13} />查看线上 Trace</button> : selected.id === 'regression' && !selectedIsLocked ? <button className="small-action" onClick={onOpenEvals}><ArrowUpRight size={13} />查看评测结果</button> : <button className="small-action" onClick={onRelease} disabled={selectedIsLocked}><Plus size={13} />进入发布配置</button>}</div></div></section>
}

function EvaluationPolicyModal({ datasets, onClose, onCreate: persistPolicy }: { datasets: DatasetItem[]; onClose: () => void; onCreate: (payload: { name: string; datasetName: string; evaluators: string[]; trigger: string; gates: Record<string, unknown> }) => void }) {
  const [trigger, setTrigger] = useState('发布后自动触发')
  const [policyName, setPolicyName] = useState('客服助手 · Regression v2')
  const [datasetName, setDatasetName] = useState(datasets[0]?.name || '')
  const [evaluatorGroup, setEvaluatorGroup] = useState('business')
  const evaluators = evaluatorGroup === 'recovery' ? ['policy_compliance', 'error_recovery'] : evaluatorGroup === 'efficiency' ? ['cost_efficiency', 'latency'] : ['deterministic_match', 'policy_compliance', 'tool_selection']
  const onCreate = () => persistPolicy({ name: policyName, datasetName, evaluators, trigger, gates: { success_rate: 0.85, safety_violation_rate: 0, p95_latency_seconds: 5, cost_ratio: 1.2 } })

  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><div className="modal evaluation-policy-modal" role="dialog" aria-modal="true" aria-labelledby="policy-modal-title"><div className="modal-header"><div><span className="detail-kicker">EVALUATION POLICY · CONTROL PLANE</span><h2 id="policy-modal-title">创建评测策略</h2><p>把测试集、评分器和发布门禁固定成一份可重复运行的策略。</p></div><button className="icon-btn" onClick={onClose} aria-label="关闭评测策略弹窗"><X size={18} /></button></div><form onSubmit={(event) => { event.preventDefault(); onCreate() }}><label>策略名称<input name="policyName" autoComplete="off" value={policyName} onChange={(event) => setPolicyName(event.target.value)} required /></label><label>数据集快照<select name="dataset" value={datasetName} onChange={(event) => setDatasetName(event.target.value)}>{datasets.map((dataset) => <option key={dataset.id} value={dataset.name}>{dataset.name}@{dataset.version}</option>)}</select></label><div className="form-two-col"><label>评分器集合<select name="evaluators" value={evaluatorGroup} onChange={(event) => setEvaluatorGroup(event.target.value)}><option value="business">业务结果 + 工具调用 + 安全</option><option value="recovery">规则遵循 + 错误恢复</option><option value="efficiency">成本效率 + 延迟</option></select></label><label>触发方式<select name="trigger" value={trigger} onChange={(event) => setTrigger(event.target.value)}><option>发布后自动触发</option><option>每 6 小时</option><option>仅手动运行</option></select></label></div><div className="policy-gate-box"><div><span className="detail-kicker">RELEASE GATES</span><strong>发布门禁</strong></div><div className="policy-gate-grid"><label><span>任务成功率</span><select name="successGate"><option>≥ 85%</option><option>≥ 90%</option><option>不设门禁</option></select></label><label><span>安全越权率</span><select name="safetyGate"><option>= 0</option><option>≤ 1%</option><option>不设门禁</option></select></label><label><span>P95 延迟</span><select name="latencyGate"><option>≤ 5 秒</option><option>≤ 8 秒</option><option>不设门禁</option></select></label><label><span>成本对比</span><select name="costGate"><option>≤ baseline 1.2×</option><option>≤ baseline 1.5×</option><option>不设门禁</option></select></label></div></div><div className="modal-info"><ShieldCheck size={16} /><span>{trigger === '发布后自动触发' ? '创建后可直接绑定到 Agent Revision，发布时自动执行。' : trigger === '每 6 小时' ? '创建后会按固定周期运行，并在异常时通知负责人。' : '策略只保存配置，不会自动消耗 Runner 资源。'}</span></div><div className="modal-footer"><button type="button" className="secondary-btn" onClick={onClose}>取消</button><button type="submit" className="primary-btn"><Check size={16} />保存评测策略</button></div></form></div></div>
}

function AgentConfigModal({ agent, onClose, onSave }: { agent: Agent; onClose: () => void; onSave: (updates: Partial<Pick<Agent, 'endpoint' | 'environment' | 'owner'>>) => void }) {
  const [endpoint, setEndpoint] = useState(agent.endpoint)
  const [environment, setEnvironment] = useState(agent.environment)
  const [owner, setOwner] = useState(agent.owner)

  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><div className="modal agent-config-modal" role="dialog" aria-modal="true" aria-labelledby="config-modal-title"><div className="modal-header"><div><span className="detail-kicker">CONFIG CHANGE · {agent.name}</span><h2 id="config-modal-title">编辑接入配置</h2><p>修改会先保存为待校验配置，完成健康检查后才允许用于下一次发布。</p></div><button className="icon-btn" onClick={onClose} aria-label="关闭接入配置弹窗"><X size={18} /></button></div><div className="config-modal-revision"><div><span className="detail-kicker">ACTIVE REVISION</span><strong>{agent.version} · {agent.environment}</strong></div><span className="release-pill stable">当前生效</span></div><form onSubmit={(event) => { event.preventDefault(); onSave({ endpoint, environment, owner }) }}><label>Endpoint / 镜像地址<input aria-label="Endpoint 或镜像地址" autoComplete="off" spellCheck={false} value={endpoint} onChange={(event) => setEndpoint(event.target.value)} required /></label><div className="form-two-col"><label>运行环境<select aria-label="运行环境" value={environment} onChange={(event) => setEnvironment(event.target.value)}><option value="sandbox">Sandbox · 沙箱</option><option value="staging">Staging · 预发布</option><option value="production">Production · 生产</option></select></label><label>负责人<input aria-label="负责人" autoComplete="name" value={owner} onChange={(event) => setOwner(event.target.value)} required /></label></div><div className="config-change-list"><div><span>影响范围</span><strong>{environment === agent.environment ? '连接地址变更' : `${agent.environment} → ${environment}`}</strong></div><div><span>校验动作</span><strong>健康检查 · 权限校验 · 协议检查</strong></div><div><span>生效时机</span><strong>下一个候选版本发布</strong></div></div><div className="modal-info"><ShieldCheck size={16} /><span>保存后不会直接切换生产流量；系统会在发布流水线的 Smoke 阶段重新校验。</span></div><div className="modal-footer"><button type="button" className="secondary-btn" onClick={onClose}>取消</button><button type="submit" className="primary-btn"><Check size={16} />保存待校验配置</button></div></form></div></div>
}

function AgentReleaseModal({ agent, onClose, onRelease }: { agent?: Agent; onClose: () => void; onRelease: (version: string, channel: string, changelog?: string) => void }) {
  const [channel, setChannel] = useState('candidate')

  if (!agent) return null

  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><div className="modal agent-release-modal" role="dialog" aria-modal="true" aria-labelledby="release-modal-title"><div className="modal-header"><div><span className="detail-kicker">RELEASE CONTROL · {agent.name}</span><h2 id="release-modal-title">发布新版本</h2><p>发布前先固定 revision、通道和变更说明，便于后续评测与回滚。</p></div><button className="icon-btn" onClick={onClose} aria-label="关闭版本发布弹窗"><X size={18} /></button></div><form onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget); onRelease(String(data.get('version') || ''), String(data.get('channel') || 'candidate'), String(data.get('changelog') || '')) }}><div className="release-target"><div className="agent-avatar-large" style={{ background: agent.accent }}>{agent.name.slice(0, 1)}</div><div><span className="detail-kicker">CURRENT REVISION</span><strong>{agent.version}</strong><small>{agent.endpoint}</small></div><span className={`environment-chip ${agent.environment}`}>{agent.environment}</span></div><div className="form-two-col"><label>新版本号<input name="version" autoComplete="off" spellCheck={false} defaultValue={agent.version.replace(/\d+$/, (value) => String(Number(value) + 1))} /></label><label>发布通道<select name="channel" value={channel} onChange={(event) => setChannel(event.target.value)}><option value="candidate">candidate · 灰度</option><option value="stable">stable · 正式</option><option value="canary">canary · 实验</option></select></label></div><label>变更说明<textarea name="changelog" autoComplete="off" placeholder="例如：优化退款策略，增加订单状态兜底…" rows={3} /></label><div className="release-checklist"><div><CheckCircle2 size={15} /><span><strong>健康检查</strong><small>Endpoint、权限与响应格式已通过</small></span><b>通过</b></div><div><ShieldCheck size={15} /><span><strong>回归评测</strong><small>绑定 3 个数据集 · 最近成功率 84%</small></span><b>通过</b></div><div><Activity size={15} /><span><strong>回滚策略</strong><small>保留 {agent.version} 作为上一稳定版本</small></span><b>已配置</b></div></div><div className="modal-info"><ShieldCheck size={16} /><span>{channel === 'stable' ? '正式发布会触发完整回归；正式发布会切换当前版本，并完整记录发布审计。' : '灰度发布会先进入候选通道，确认评测结果后再提升为 stable。'}</span></div><div className="modal-footer"><button type="button" className="secondary-btn" onClick={onClose}>取消</button><button type="submit" className="primary-btn"><GitBranch size={16} />创建发布任务</button></div></form></div></div>
}

function AgentEvaluationBindingModal({ agent, policies, onClose, onBind }: { agent?: Agent; policies: ApiPolicy[]; onClose: () => void; onBind: (payload: { policyId: string; schedule: string; failureThreshold: number; autoRegression: boolean; notifyOwner: boolean }) => void }) {
  const [selectedPolicy, setSelectedPolicy] = useState(policies[0]?.id || '')
  if (!agent) return null

  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><div className="modal agent-binding-modal" role="dialog" aria-modal="true" aria-labelledby="binding-modal-title"><div className="modal-header"><div><span className="detail-kicker">EVALUATION BINDING · {agent.name}</span><h2 id="binding-modal-title">绑定评测</h2><p>为当前 revision 固定数据集、评分器与触发策略，后续运行会自动记录到 Agent。</p></div><button className="icon-btn" onClick={onClose} aria-label="关闭评测绑定弹窗"><X size={18} /></button></div><form onSubmit={(event) => { event.preventDefault(); onBind({ policyId: selectedPolicy, schedule: String(new FormData(event.currentTarget).get('schedule') || 'manual'), failureThreshold: Number(new FormData(event.currentTarget).get('threshold') || 0.8), autoRegression: new FormData(event.currentTarget).get('autoRegression') === 'on', notifyOwner: new FormData(event.currentTarget).get('notifyOwner') === 'on' }) }}><div className="binding-target"><div className="agent-avatar-large" style={{ background: agent.accent }}>{agent.name.slice(0, 1)}</div><div><span className="detail-kicker">TARGET REVISION</span><strong>{agent.name} / {agent.version}</strong><small>stable · {agent.environment}</small></div><span className="release-pill stable">可绑定</span></div><label>评测模板<select name="evaluation" value={selectedPolicy} onChange={(event) => setSelectedPolicy(event.target.value)}>{policies.map((policy) => <option key={policy.id} value={policy.id}>{policy.name} · {policy.dataset_name}</option>)}</select></label><div className="form-two-col"><label>触发策略<select name="schedule"><option value="0 9 * * *">每日 09:00</option><option value="0 */6 * * *">每 6 小时</option><option value="release">发布后自动触发</option><option value="manual">手动触发</option></select></label><label>失败阈值<select name="threshold"><option value="0.8">低于 80% 告警</option><option value="0.85">低于 85% 告警</option><option value="0.9">低于 90% 告警</option></select></label></div><div className="binding-options"><label><input name="autoRegression" type="checkbox" defaultChecked /> 发布后自动回归</label><label><input name="notifyOwner" type="checkbox" defaultChecked /> 失败时通知负责人</label></div><div className="modal-info"><ShieldCheck size={16} /><span>绑定后会创建持续评测任务；不会改变 Agent 的生产流量配置。</span></div><div className="modal-footer"><button type="button" className="secondary-btn" onClick={onClose}>取消</button><button type="submit" className="primary-btn"><Link2 size={16} />创建绑定</button></div></form></div></div>
}

function AgentRollbackModal({ agent, version, onClose, onConfirm }: { agent?: Agent; version: string; onClose: () => void; onConfirm: () => void }) {
  if (!agent) return null

  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><div className="modal agent-rollback-modal" role="dialog" aria-modal="true" aria-labelledby="rollback-modal-title"><div className="modal-header"><div><span className="detail-kicker">ROLLBACK PREVIEW · {agent.name}</span><h2 id="rollback-modal-title">回滚预览</h2><p>先检查影响范围与回归门槛，再创建可审批的回滚任务。</p></div><button className="icon-btn" onClick={onClose} aria-label="关闭回滚预览弹窗"><X size={18} /></button></div><div className="rollback-route"><div><span>当前生产版本</span><strong>{agent.version}</strong><small>stable · 正在接收流量</small></div><ArrowRight size={17} /><div className="rollback-destination"><span>目标版本</span><strong>{version}</strong><small>历史版本 · 79% 质量得分</small></div></div><div className="rollback-checks"><div><CheckCircle2 size={15} /><span><strong>版本可恢复</strong><small>镜像与配置仍保留在注册表</small></span><b>通过</b></div><div><ShieldCheck size={15} /><span><strong>评测门槛</strong><small>需要完成绑定评测后才允许切换流量</small></span><b>待审批</b></div><div><AlertTriangle size={15} /><span><strong>影响范围</strong><small>只影响 {agent.name} 的 production endpoint</small></span><b>低风险</b></div></div><div className="modal-info warning"><AlertTriangle size={16} /><span>确认后会切换当前版本并记录回滚审计；运行实例需按新版本重新部署。</span></div><div className="modal-footer"><button type="button" className="secondary-btn" onClick={onClose}>取消</button><button type="button" className="primary-btn" onClick={onConfirm}><GitBranch size={16} />创建回滚预览</button></div></div></div>
}

function NewRunModal({ agents, datasets, defaultAgent, onClose, onSubmit }: { agents: Agent[]; datasets: DatasetItem[]; defaultAgent?: string; onClose: () => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void }) {
  const selectedDefault = defaultAgent ?? `${agents[0]?.name ?? '客服助手'} / ${agents[0]?.version ?? 'v1.8.2'}`
  const [selectedAgentValue, setSelectedAgentValue] = useState(selectedDefault)
  const selectedAgent = agents.find((agent) => selectedAgentValue.startsWith(`${agent.name} /`))
  const blocked = !selectedAgent || selectedAgent.status === 'offline'
  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="run-modal-title"><div className="modal-header"><div><span className="detail-kicker">NEW EVALUATION RUN</span><h2 id="run-modal-title">创建评测运行</h2><p>选择一个已注册 Agent、数据集和能力模板。</p></div><button className="icon-btn" onClick={onClose} aria-label="关闭创建评测运行弹窗"><X size={18} /></button></div><form onSubmit={onSubmit}><label>Agent 版本<select name="agent" value={selectedAgentValue} onChange={(event) => setSelectedAgentValue(event.target.value)}>{agents.map((agent) => <option key={agent.id} disabled={agent.status === 'offline'}>{agent.name} / {agent.version}{agent.status === 'offline' ? ' · 待健康检查' : ''}</option>)}</select></label>{blocked && <div className="modal-info warning"><AlertTriangle size={16} /><span>当前 Agent 还没有通过健康检查，请先回到 Agent 管理页完成检查。</span></div>}<label>数据集<select name="dataset" defaultValue={datasets[0]?.name}>{datasets.map((dataset) => <option key={dataset.id} value={dataset.name}>{dataset.name} · {dataset.version}</option>)}</select></label><div className="form-two-col"><label>最大步数<input name="steps" type="number" min="1" defaultValue="50" /></label><label>最大成本<input name="budget" inputMode="decimal" defaultValue="$10.00" /></label></div><div className="run-contract-preview"><span className="detail-kicker">RUN CONTRACT</span><div><span>Agent revision</span><strong>{selectedAgent?.version ?? '—'}</strong></div><div><span>连接</span><strong>{selectedAgent?.mode ?? '—'}</strong></div><div><span>结果回写</span><strong>Trace + Score</strong></div></div><div className="modal-info"><ShieldCheck size={16} /><span>运行会固定当前 Agent revision 和数据集快照；Runner 将按 Provision → Execute → Score 顺序执行。</span></div><div className="modal-footer"><button type="button" className="secondary-btn" onClick={onClose}>取消</button><button type="submit" className="primary-btn" disabled={blocked}><Play size={16} />{blocked ? '等待健康检查' : '启动评测'}</button></div></form></div></div>
}

function AgentModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: (payload: { name: string; mode: string; endpoint: string; environment: string; packageFile?: File; branch: string; entrypoint: string; timeout: string }) => Promise<{ agent: ApiAgent; sdkAccess?: ApiSdkKey }> }) {
  const [mode, setMode] = useState('Code Package')
  const [environment, setEnvironment] = useState('sandbox')
  const [step, setStep] = useState<1 | 2 | 3>(1)
  const [validationState, setValidationState] = useState<'idle' | 'checking' | 'ready'>('idle')
  const [formState, setFormState] = useState({ name: '', endpoint: '', branch: 'main', entrypoint: 'run.py', timeout: '30' })
  const [fileName, setFileName] = useState('')
  const [packageFile, setPackageFile] = useState<File>()
  const [isDragging, setIsDragging] = useState(false)
  const [sdkAccess, setSdkAccess] = useState<ApiSdkKey>()
  const [submitError, setSubmitError] = useState('')

  const selectPackage = (file?: File) => {
    if (!file || !/\.(zip|tar\.gz)$/i.test(file.name)) return
    setPackageFile(file)
    setFileName(file.name)
    if (!formState.name) setFormState((current) => ({ ...current, name: file.name.replace(/\.(zip|tar\.gz)$/i, '') }))
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (step === 1) {
      if (mode === 'Code Package' && !packageFile) return
      setStep(2)
      setValidationState('checking')
      window.setTimeout(() => setValidationState('ready'), 1100)
      return
    }
    if (validationState === 'ready') {
      setSubmitError('')
      try {
        const result = await onSuccess({ name: formState.name, mode, endpoint: formState.endpoint, environment, packageFile, branch: formState.branch, entrypoint: formState.entrypoint, timeout: formState.timeout })
        if (result.sdkAccess) {
          setSdkAccess(result.sdkAccess)
          setStep(3)
        }
      } catch (error) {
        setSubmitError(error instanceof Error ? error.message : 'Agent 添加失败')
      }
    }
  }

  const sourceTypes = [
    { name: 'Code Package', label: '上传代码包', icon: FileArchive, note: '拖入 ZIP / TAR.GZ，由平台构建和部署' },
    { name: 'Git Repository', label: '导入 Git 仓库', icon: GitBranch, note: '支持 GitHub、Gitee 和企业 Git 地址' },
    { name: 'SDK Access', label: '使用 SDK 接入', icon: Code2, note: 'Agent 自行运行，通过密钥上报 Trace 与评测事件' },
  ]
  const sourceSummary = mode === 'Code Package' ? fileName : mode === 'Git Repository' ? formState.endpoint : 'Eval Loom SDK exporter · DeepEval instrumentation'
  const validationItems = [
    ['来源检查', mode === 'Code Package' ? 'agent.yaml 与启动入口存在' : mode === 'Git Repository' ? '仓库地址、分支和提交引用可解析' : 'SDK 版本、Agent 标识和上报目标已生成'],
    ['DeepEval 观测', '使用 DeepEval SDK 记录 span、tool call、模型用量与评分上下文'],
    ['AgenticBench Adapter', '实现 agentic-bench/v1 的 Task → Action → Observation 循环'],
    ['运行契约', mode === 'SDK Access' ? 'NDJSON 批量上报 · 幂等事件 ID · 5 MiB 限制' : `${formState.entrypoint} · /health · /invoke · timeout ${formState.timeout}s`],
    ['安全边界', '密钥仅通过运行时注入；代码不得内置 API Key，容器以非 root 运行'],
  ]
  const sdkSnippet = `from agent_eval import PlatformSink, configure, observe as platform_observe\nfrom deepeval.tracing import observe as deepeval_observe\n\nconfigure(sinks=[PlatformSink(\n    "${window.location.origin}",\n    "${sdkAccess?.key ?? 'evk_...'}",\n)])\n\n@platform_observe(kind="agent", name="my_agent")\n@deepeval_observe(type="agent")\ndef my_agent(task):\n    ...`

  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><div className="modal agent-modal-pro agent-import-modal" role="dialog" aria-modal="true" aria-labelledby="agent-modal-title">
    <div className="modal-header"><div><span className="detail-kicker">ADD AGENT · STEP 0{step} / 03</span><h2 id="agent-modal-title">添加 Agent</h2><p>{step === 1 ? '上传源码、导入 Git 仓库，或使用 SDK 密钥上报已有 Agent 的运行轨迹。' : step === 2 ? '确认 Agent 满足观测、评测协议和运行安全约束。' : 'SDK 接入信息已生成。密钥仅在这里完整显示一次。'}</p></div><button className="icon-btn" onClick={onClose} aria-label="关闭添加 Agent 弹窗"><X size={20} /></button></div>
    <div className="registration-progress"><span className="active"><b>01</b>选择来源</span><i /><span className={step >= 2 ? 'active' : ''}><b>02</b>检查接入契约</span><i /><span className={step === 3 ? 'active' : ''}><b>03</b>{mode === 'SDK Access' ? '配置 SDK' : '一键部署'}</span></div>
    <form onSubmit={submit}>{step === 1 ? <div className="agent-import-layout">
      <div className="agent-import-main">
        <div className="registration-section"><span className="form-section-label">Agent 来源</span><div className="connection-type-grid">{sourceTypes.map(({ name, label, icon: Icon, note }) => <button type="button" key={name} className={`connection-type ${mode === name ? 'selected' : ''}`} onClick={() => { setMode(name); setValidationState('idle') }}><span><Icon size={19} /></span><strong>{label}</strong><small>{note}</small>{mode === name && <CheckCircle2 size={16} className="connection-check" />}</button>)}</div></div>
        {mode === 'Code Package' ? <div className={`agent-package-dropzone ${isDragging ? 'dragging' : ''}`} onDragEnter={(event) => { event.preventDefault(); setIsDragging(true) }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => setIsDragging(false)} onDrop={(event) => { event.preventDefault(); setIsDragging(false); selectPackage(event.dataTransfer.files?.[0]) }}><span className="dropzone-icon"><UploadCloud size={26} /></span><div><strong>{fileName || '把 Agent 代码包拖到这里'}</strong><p>{fileName ? '已选择代码制品，将检查目录结构与安全限制。' : '支持 .zip / .tar.gz，最大 100 MiB'}</p></div><input id="agent-package" className="visually-hidden" type="file" accept=".tar.gz,.zip" onChange={(event) => selectPackage(event.target.files?.[0])} /><label htmlFor="agent-package" className="secondary-btn">浏览文件</label></div> : mode === 'Git Repository' ? <label>Git 仓库地址<input name="endpoint" type="url" autoComplete="off" spellCheck={false} value={formState.endpoint} onChange={(event) => setFormState((current) => ({ ...current, endpoint: event.target.value }))} placeholder="https://github.com/acme/order-agent.git" required /></label> : <div className="sdk-access-intro"><span><Network size={21} /></span><div><strong>不需要平台托管运行</strong><p>平台生成 Agent 专属密钥。你的服务使用 SDK 将 Trace 和评测事件推送到本平台。</p></div></div>}
        <div className="form-two-col"><label>Agent 名称<input name="name" autoComplete="off" value={formState.name} onChange={(event) => setFormState((current) => ({ ...current, name: event.target.value }))} placeholder="例如：订单助手" required /></label>{mode === 'Git Repository' ? <label>分支 / Tag / Commit<input name="branch" autoComplete="off" value={formState.branch} onChange={(event) => setFormState((current) => ({ ...current, branch: event.target.value }))} required /></label> : mode === 'SDK Access' ? <label>上报协议<input value="Eval Loom Trace NDJSON v1" readOnly /></label> : <label>启动入口<input name="entrypoint" autoComplete="off" value={formState.entrypoint} onChange={(event) => setFormState((current) => ({ ...current, entrypoint: event.target.value }))} required /></label>}</div>
        <div className="form-two-col"><label>运行环境<select value={environment} onChange={(event) => setEnvironment(event.target.value)}><option value="sandbox">Sandbox · 沙箱</option><option value="staging">Staging · 预发布</option><option value="production">Production · 生产</option></select></label><label>单任务超时<select value={formState.timeout} onChange={(event) => setFormState((current) => ({ ...current, timeout: event.target.value }))}><option value="15">15 秒</option><option value="30">30 秒</option><option value="60">60 秒</option><option value="120">120 秒</option></select></label></div>
      </div>
      <aside className="agent-contract-card"><span className="detail-kicker">IMPORT CONTRACT</span><h3>Agent 接入规范</h3><p>{mode === 'SDK Access' ? 'SDK 模式只上报观测事件，不接管你的 Agent 进程。' : '缺少必需项的版本不会进入部署流水线。'}</p><ul>{mode !== 'SDK Access' && <><li><Check size={14} /><span><strong>固定清单</strong>agent.yaml + 可复现依赖锁</span></li><li><Check size={14} /><span><strong>统一入口</strong>/health 与 /invoke</span></li></>}<li><Check size={14} /><span><strong>DeepEval SDK</strong>Trace、Tool Call、Token 与评分埋点</span></li><li><Check size={14} /><span><strong>AgenticBench</strong>Adapter 转换 Action / Observation</span></li><li><Check size={14} /><span><strong>密钥安全</strong>仅保存哈希，明文只显示一次，可随时吊销</span></li></ul><span className="contract-doc-link">完整字段见项目接入规范 <ArrowUpRight size={14} /></span></aside>
      <div className="modal-footer agent-import-footer"><button type="button" className="secondary-btn" onClick={onClose}>取消</button><button type="submit" className="primary-btn" disabled={mode === 'Code Package' && !packageFile}><ArrowRight size={17} />检查并继续</button></div>
    </div> : step === 2 ? <div className="agent-validation-layout">
      <div className="validation-summary"><div className="validation-summary-icon"><Server size={20} /></div><div><span className="detail-kicker">SOURCE READY</span><strong>{formState.name}</strong><p>{sourceSummary} · {environment}</p></div><button type="button" className="text-btn" onClick={() => { setStep(1); setValidationState('idle') }}>返回修改</button></div>
      <div className="validation-list contract-validation-list">{validationItems.map(([title, detail], index) => <div key={title} className={validationState === 'checking' ? 'checking' : 'passed'}><span>{index === 1 ? <Activity size={16} /> : index === 2 ? <Network size={16} /> : index === 4 ? <ShieldCheck size={16} /> : <CheckCircle2 size={16} />}</span><div><strong>{title}</strong><small>{validationState === 'checking' ? '正在检查制品与配置…' : detail}</small></div><b>{validationState === 'checking' ? '检查中' : '通过'}</b></div>)}</div>
      <div className="deployment-next-step"><Zap size={18} /><div><strong>{mode === 'SDK Access' ? '下一步：生成 SDK 密钥' : '下一步：一键部署'}</strong><span>{mode === 'SDK Access' ? '平台将生成 Agent 专属的上报密钥和代码片段；该密钥不会用于调用模型或访问部署实例。' : '添加完成后，在“实例与密钥”中点击一键部署；平台会创建隔离实例、注入密钥并生成调用 Token。'}</span></div></div>
      {submitError && <div className="modal-info warning"><AlertTriangle size={16} /><span>{submitError}</span></div>}
      <div className="modal-footer"><button type="button" className="secondary-btn" onClick={() => { setStep(1); setValidationState('idle') }}>上一步</button><button type="submit" className="primary-btn" disabled={validationState !== 'ready'}><Check size={17} />{validationState === 'checking' ? '正在检查…' : '添加 Agent'}</button></div>
    </div> : <div className="sdk-success-panel"><div className="sdk-success-heading"><span><CheckCircle2 size={22} /></span><div><strong>{formState.name} 已开始接收 Trace</strong><p>把以下配置加入 Agent 进程。密钥只显示一次，关闭后只能重新生成。</p></div></div><div className="sdk-credential-row"><div><span>Agent SDK Key</span><code>{sdkAccess?.key}</code></div><button type="button" className="secondary-btn" onClick={() => void navigator.clipboard?.writeText(sdkAccess?.key ?? '')}><Copy size={15} />复制密钥</button></div><div className="sdk-code-block"><div><span>Python · Eval Loom SDK</span><button type="button" onClick={() => void navigator.clipboard?.writeText(sdkSnippet)}><Copy size={14} />复制代码</button></div><pre>{sdkSnippet}</pre></div><div className="sdk-separation-note"><ShieldCheck size={17} /><div><strong>三类密钥相互隔离</strong><span>SDK Key 用于上报 Trace；部署 Token 用于调用 Agent；OpenAI 等模型密钥仍存放在平台密钥库。</span></div></div><div className="modal-footer"><button type="button" className="primary-btn" onClick={onClose}>完成</button></div></div>}</form>
  </div></div>
}

function SystemSettingsModal({ onClose, onSave }: { onClose: () => void; onSave: (payload: { refresh_interval_seconds: number; trace_retention_days: number; confirm_destructive: boolean }) => Promise<void> }) {
  const [refreshInterval, setRefreshInterval] = useState('30 秒')
  const [retention, setRetention] = useState('30 天')
  const onNotify = (_message?: string) => void onSave({ refresh_interval_seconds: refreshInterval === '15 秒' ? 15 : refreshInterval === '1 分钟' ? 60 : 30, trace_retention_days: Number(retention.replace(' 天', '')), confirm_destructive: true })

  return <AntModal className="mature-modal" open onCancel={onClose} title={<span><span className="detail-kicker">WORKSPACE SETTINGS</span><h2 id="system-settings-title">工作区设置</h2></span>} width={560} footer={<AntButton type="primary" icon={<Check size={16} />} onClick={() => { onNotify('工作区设置已保存'); onClose() }}>保存设置</AntButton>}>
    <p className="modal-description">调整控制台刷新节奏与 Trace 保留策略。这里只修改当前工作区的展示偏好。</p>
    <div className="settings-list mature-settings-list">
      <label><span>状态刷新间隔</span><AntSelect value={refreshInterval} onChange={setRefreshInterval} options={['15 秒', '30 秒', '1 分钟'].map((value) => ({ value, label: value }))} /></label>
      <label><span>Trace 保留时间</span><AntSelect value={retention} onChange={setRetention} options={['7 天', '30 天', '90 天'].map((value) => ({ value, label: value }))} /></label>
      <div className="settings-row"><div><strong>操作确认</strong><small>停止 Run、暂停 Agent 等动作显示确认提示</small></div><Tag color="success">已开启</Tag></div>
      <div className="settings-row"><div><strong>运行模式</strong><small>控制面 API · 异步本地 Runner</small></div><Tag color="processing">Local</Tag></div>
    </div>
    <Alert className="modal-info mature-alert" type="info" showIcon message="生产接入时，这里会对应控制面配置；真正的 Runner、Trace Store 和 Scorer 仍需接入后端。" />
  </AntModal>
}

export default App
