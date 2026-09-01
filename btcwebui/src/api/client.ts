import axios, { type AxiosInstance, type AxiosResponse } from 'axios'
import type {
  ApiResponse,
  GlobalConfig,
  HealthData,
  InvokeData,
  InvokePayload,
  LogsData,
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

export default http
