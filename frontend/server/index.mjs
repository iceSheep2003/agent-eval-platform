import { createServer } from 'node:http'
import { readFile } from 'node:fs/promises'
import { timingSafeEqual, randomBytes, scryptSync } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = dirname(fileURLToPath(import.meta.url))
const port = Number(process.env.PORT || 8787)
const sessionTtlMs = 8 * 60 * 60 * 1000
const sessions = new Map()

const workspaces = [
  { id: 'eval-dev', name: '评测平台开发', description: 'Agent evaluation workspace', role: 'Owner', memberCount: 4 },
  { id: 'support-lab', name: '客服 Agent Lab', description: '客服场景实验工作区', role: 'Maintainer', memberCount: 7 },
]

const users = JSON.parse(await readFile(join(root, 'data/users.json'), 'utf8'))

function publicUser(user) {
  return {
    id: user.id,
    username: user.username,
    email: user.email,
    displayName: user.displayName,
    role: user.role,
  }
}

function userWorkspaces(user) {
  return workspaces.filter((workspace) => user.workspaceIds.includes(workspace.id))
}

function verifyPassword(password, user) {
  const actual = scryptSync(password, user.salt, 64)
  const expected = Buffer.from(user.passwordHash, 'hex')
  return actual.length === expected.length && timingSafeEqual(actual, expected)
}

function parseCookies(request) {
  return Object.fromEntries((request.headers.cookie || '').split(';').filter(Boolean).map((part) => {
    const [key, ...value] = part.trim().split('=')
    return [key, decodeURIComponent(value.join('='))]
  }))
}

function currentUser(request) {
  const sessionId = parseCookies(request).sid
  const session = sessionId && sessions.get(sessionId)
  if (!session) return null
  if (session.expiresAt < Date.now()) {
    sessions.delete(sessionId)
    return null
  }
  return users.find((user) => user.id === session.userId) || null
}

function sendJson(response, status, payload, headers = {}) {
  response.writeHead(status, { 'content-type': 'application/json; charset=utf-8', ...headers })
  response.end(JSON.stringify(payload))
}

function sendError(response, status, message) {
  sendJson(response, status, { error: message })
}

async function readBody(request) {
  let body = ''
  for await (const chunk of request) {
    body += chunk
    if (body.length > 1024 * 1024) throw new Error('request_too_large')
  }
  if (!body) return {}
  try {
    return JSON.parse(body)
  } catch {
    throw new Error('invalid_json')
  }
}

function authPayload(user) {
  return { user: publicUser(user), workspaces: userWorkspaces(user) }
}

function sessionCookie(sessionId, maxAge = Math.floor(sessionTtlMs / 1000)) {
  return `sid=${encodeURIComponent(sessionId)}; HttpOnly; SameSite=Lax; Path=/; Max-Age=${maxAge}`
}

const server = createServer(async (request, response) => {
  response.setHeader('access-control-allow-origin', 'http://127.0.0.1:4173')
  response.setHeader('access-control-allow-credentials', 'true')
  response.setHeader('access-control-allow-headers', 'content-type')
  response.setHeader('access-control-allow-methods', 'GET,POST,OPTIONS')
  if (request.method === 'OPTIONS') return sendJson(response, 204, {})

  const url = new URL(request.url || '/', `http://${request.headers.host || '127.0.0.1'}`)
  try {
    if (request.method === 'GET' && url.pathname === '/api/health') {
      return sendJson(response, 200, { ok: true, service: 'eval-loom-auth', now: new Date().toISOString() })
    }

    if (request.method === 'POST' && url.pathname === '/api/auth/login') {
      const body = await readBody(request)
      const identifier = String(body.identifier || '').trim().toLowerCase()
      const password = String(body.password || '')
      const user = users.find((candidate) => candidate.username === identifier || candidate.email === identifier)
      if (!user || !password || !verifyPassword(password, user)) return sendError(response, 401, '账号或密码错误')

      const sessionId = randomBytes(32).toString('hex')
      sessions.set(sessionId, { userId: user.id, expiresAt: Date.now() + sessionTtlMs })
      return sendJson(response, 200, authPayload(user), { 'set-cookie': sessionCookie(sessionId) })
    }

    if (request.method === 'POST' && url.pathname === '/api/auth/logout') {
      const sessionId = parseCookies(request).sid
      if (sessionId) sessions.delete(sessionId)
      return sendJson(response, 200, { ok: true }, { 'set-cookie': sessionCookie('', 0) })
    }

    if (request.method === 'GET' && url.pathname === '/api/auth/me') {
      const user = currentUser(request)
      if (!user) return sendError(response, 401, '未登录')
      return sendJson(response, 200, authPayload(user))
    }

    if (request.method === 'GET' && url.pathname === '/api/workspaces') {
      const user = currentUser(request)
      if (!user) return sendError(response, 401, '未登录')
      return sendJson(response, 200, { workspaces: userWorkspaces(user) })
    }

    sendError(response, 404, 'Not found')
  } catch (error) {
    if (error.message === 'request_too_large') return sendError(response, 413, '请求体过大')
    if (error.message === 'invalid_json') return sendError(response, 400, '请求格式错误')
    console.error(error)
    sendError(response, 500, '服务暂时不可用')
  }
})

server.listen(port, '127.0.0.1', () => {
  console.log(`Eval Loom auth API listening on http://127.0.0.1:${port}`)
})
