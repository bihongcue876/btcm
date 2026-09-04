import axios, { type AxiosInstance, type AxiosResponse } from 'axios'
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

const http: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 0, // invoke 可能耗时较长，不设前端超时，交由后端 timeout 控制
  headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
})

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

// 后端配置 admin_token 后，写配置/重置/日志接口要求该请求头；自动附加
http.interceptors.request.use((config) => {
  const token = getAdminToken()
  if (token) {
    config.headers['X-Admin-Token'] = token
  }
  return config
})

/** 统一解包 {success, data, error} 外层结构，成功时返回完整 body（含 request_id） */
async function unwrapBody<T>(promise: Promise<AxiosResponse<ApiResponse<T>>>): Promise<ApiResponse<T>> {
  let resp: AxiosResponse<ApiResponse<T>>
  try {
    resp = await promise
  } catch (e) {
    if (axios.isAxiosError(e) && e.response?.data) {
      const body = e.response.data as ApiResponse<T>
      if (body.error) {
        throw new ApiError(body.error.code, body.error.message)
      }
    }
    throw new ApiError('NETWORK_ERROR', `网络请求失败：${(e as Error).message}`)
  }
  const body = resp.data
  if (!body.success || body.error) {
    throw new ApiError(body.error?.code ?? 'UNKNOWN', body.error?.message ?? '未知错误')
  }
  return body
}

async function unwrap<T>(promise: Promise<AxiosResponse<ApiResponse<T>>>): Promise<T> {
  const body = await unwrapBody(promise)
  return body.data as T
}

export const api = {
  async invoke(payload: InvokePayload): Promise<{ data: InvokeData; requestId: string }> {
    const body = await unwrapBody<InvokeData>(http.post('/invoke', payload))
    return { data: body.data as InvokeData, requestId: body.request_id }
  },
  getHealth(): Promise<HealthData> {
    return unwrap<HealthData>(http.get('/health'))
  },
  getConfig(): Promise<GlobalConfig> {
    return unwrap<GlobalConfig>(http.get('/config'))
  },
  updateConfig(partial: object): Promise<GlobalConfig> {
    return unwrap<GlobalConfig>(http.put('/config', partial))
  },
  resetConfig(): Promise<GlobalConfig> {
    return unwrap<GlobalConfig>(http.post('/config/reset'))
  },
  getLogs(limit: number, offset: number): Promise<LogsData> {
    return unwrap<LogsData>(http.get('/logs', { params: { limit, offset } }))
  },
  /** 拉取提供商可用模型列表（OpenAI 兼容 GET /models 的服务端代理） */
  fetchProviderModels(name: string): Promise<string[]> {
    return unwrap<{ models: string[] }>(
      http.get(`/providers/${encodeURIComponent(name)}/models`),
    ).then((d) => d.models)
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
    resp = await fetch('/api/invoke/stream', {
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
    throw new ApiError('NETWORK_ERROR', `网络请求失败：${(e as Error).message}`)
  }
  if (!resp.ok || !resp.body) {
    // 流开始前的校验失败（鉴权/缺 candidate/限流）返回普通 JSON 错误
    let body: ApiResponse<InvokeData> | null = null
    try {
      body = await resp.json()
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

export default http
