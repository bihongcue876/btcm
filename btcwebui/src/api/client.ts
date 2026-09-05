import type {
  ApiResponse,
  GlobalConfig,
  HealthData,
  InvokeData,
  InvokePayload,
  LogsData,
  StreamEvent,
} from '@/types'

export class ApiError extends Error {
  code: string
  constructor(code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
  }
}

// ---------- API 基址 ----------
// 前后端解耦：前端为独立 SPA。dev 由 vite 代理 /api；独立部署时用
// VITE_API_BASE 指向后端（如 http://127.0.0.1:8000），后端已开 CORS。
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

// ---------- 管理令牌（X-Admin-Token） ----------

const ADMIN_TOKEN_KEY = 'btcm_admin_token'

/** 令牌变更后广播，各页面监听并重新拉取（解决设令牌后各页 401 的死锁） */
export const ADMIN_TOKEN_CHANGED_EVENT = 'btcm:admin-token-changed'

export function getAdminToken(): string {
  return localStorage.getItem(ADMIN_TOKEN_KEY) ?? ''
}

export function setAdminToken(token: string): void {
  if (token) {
    localStorage.setItem(ADMIN_TOKEN_KEY, token)
  } else {
    localStorage.removeItem(ADMIN_TOKEN_KEY)
  }
}

/**
 * 统一 JSON 请求：解包 {success, data, error} 外层结构。
 * 面板 API 全集只需 GET/POST/PUT + SSE 流，fetch 足以覆盖，
 * 不引入 axios（保持面板零多余运行时依赖）。
 */
async function request<T>(
  method: 'GET' | 'POST' | 'PUT',
  path: string,
  body?: object,
): Promise<ApiResponse<T>> {
  let resp: Response
  try {
    resp = await fetch(`${API_BASE}/api${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        ...(getAdminToken() ? { 'X-Admin-Token': getAdminToken() } : {}),
      },
      // invoke 可能耗时较长，不设前端超时，交由后端 timeout 控制
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
  } catch (e) {
    throw new ApiError('NETWORK_ERROR', `网络请求失败：${(e as Error).message}`)
  }
  let data: ApiResponse<T> | null = null
  try {
    data = (await resp.json()) as ApiResponse<T>
  } catch {
    // 非 JSON 响应体（如网关拦截页），按 HTTP 状态归错
  }
  if (data && (!data.success || data.error)) {
    throw new ApiError(
      data.error?.code ?? 'UNKNOWN',
      data.error?.message ?? (resp.ok ? '未知错误' : `HTTP ${resp.status}`),
    )
  }
  if (!data) {
    throw new ApiError('NETWORK_ERROR', `网络请求失败（HTTP ${resp.status}）`)
  }
  return data
}

async function unwrap<T>(
  method: 'GET' | 'POST' | 'PUT',
  path: string,
  body?: object,
): Promise<T> {
  const resp = await request<T>(method, path, body)
  return resp.data as T
}

export const api = {
  async invoke(
    payload: InvokePayload,
  ): Promise<{ data: InvokeData; requestId: string }> {
    const body = await request<InvokeData>('POST', '/invoke', payload)
    return { data: body.data as InvokeData, requestId: body.request_id }
  },
  getHealth(): Promise<HealthData> {
    return unwrap<HealthData>('GET', '/health')
  },
  getConfig(): Promise<GlobalConfig> {
    return unwrap<GlobalConfig>('GET', '/config')
  },
  updateConfig(partial: object): Promise<GlobalConfig> {
    return unwrap<GlobalConfig>('PUT', '/config', partial)
  },
  resetConfig(): Promise<GlobalConfig> {
    return unwrap<GlobalConfig>('POST', '/config/reset')
  },
  getLogs(limit: number, offset: number): Promise<LogsData> {
    return unwrap<LogsData>('GET', `/logs?limit=${limit}&offset=${offset}`)
  },
  /** 拉取提供商可用模型列表（OpenAI 兼容 GET /models 的服务端代理） */
  async fetchProviderModels(name: string): Promise<string[]> {
    const d = await unwrap<{ models: string[] }>(
      'GET',
      `/providers/${encodeURIComponent(name)}/models`,
    )
    return d.models
  },
}

// ---------- 流式调用（SSE：EventSource 不支持 POST，用 fetch 手解） ----------

export interface StreamHandlers {
  onEvent: (event: StreamEvent) => void
  /** 正常结束：body 与 /invoke 响应同构 */
  onDone: (body: ApiResponse<InvokeData>) => void
  /** 服务端执行失败：body.error 携带错误码与信息 */
  onError: (body: ApiResponse<InvokeData>) => void
}

export async function invokeStream(
  payload: InvokePayload,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let resp: Response
  try {
    resp = await fetch(`${API_BASE}/api/invoke/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(getAdminToken() ? { 'X-Admin-Token': getAdminToken() } : {}),
      },
      body: JSON.stringify(payload),
      signal,
    })
  } catch (e) {
    // 用户中止（响应头未返回阶段）原样上抛，由调用方按 AbortError 语义处理
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new ApiError('NETWORK_ERROR', `网络请求失败：${(e as Error).message}`)
  }
  if (!resp.ok || !resp.body) {
    // 流开始前的校验失败（鉴权/缺 candidate/限流）返回普通 JSON 错误
    let body: ApiResponse<InvokeData> | null = null
    try {
      body = (await resp.json()) as ApiResponse<InvokeData>
    } catch {
      // 非 JSON 响应体，忽略
    }
    if (body?.error) throw new ApiError(body.error.code, body.error.message)
    throw new ApiError('NETWORK_ERROR', `流式请求失败（HTTP ${resp.status}）`)
  }

  let finished = false
  const handleFrame = (frame: string) => {
    let name = 'message'
    const dataLines: string[] = []
    for (const line of frame.split('\n')) {
      if (line.startsWith('event: ')) name = line.slice(7)
      else if (line.startsWith('data: ')) dataLines.push(line.slice(6))
    }
    if (!dataLines.length) return
    let parsed: unknown
    try {
      parsed = JSON.parse(dataLines.join('\n'))
    } catch {
      return
    }
    if (name === 'done') {
      finished = true
      handlers.onDone(parsed as ApiResponse<InvokeData>)
    } else if (name === 'error') {
      finished = true
      handlers.onError(parsed as ApiResponse<InvokeData>)
    } else {
      handlers.onEvent(parsed as StreamEvent)
    }
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      if (frame.trim()) handleFrame(frame)
    }
  }
  if (!finished) {
    throw new ApiError('STREAM_INTERRUPTED', '流式连接中断，未收到完整结果')
  }
}
