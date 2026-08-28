// 类型定义，对齐 share/protocol.md v0.9

export interface ProviderConfig {
  base_url: string
  api_key?: string | null
  models: string[]
  timeout?: number
}

export interface AgentConfig {
  provider: string
  model: string
  num_candidates?: number
  temperature?: number
  max_tokens?: number
  timeout?: number | null
  enable_web_search?: boolean
  web_sources?: string[]
  log_intermediate?: boolean
}

export interface GlobalConfig {
  max_iterations: number
  timeout: number
  enable_creative: boolean
  enable_validator: boolean
  providers: Record<string, ProviderConfig>
  agents: Record<string, AgentConfig>
}

export interface RuntimeAgentOverride {
  num_candidates?: number | null
  temperature?: number | null
  max_tokens?: number | null
  timeout?: number | null
  enable_web_search?: boolean | null
  web_sources?: string[] | null
  log_intermediate?: boolean | null
}

export interface RuntimeConfig {
  max_iterations?: number | null
  timeout?: number | null
  agents?: Record<string, RuntimeAgentOverride>
}

export interface InvokePayload {
  request_id?: string
  user_query: string
  candidate?: string | null
  evidence?: string[]
  context_summary?: string | null
  enable_creative?: boolean | null
  enable_validator?: boolean | null
  config?: RuntimeConfig | null
}

export interface ApiError {
  code: string
  message: string
  details?: Record<string, unknown> | null
}

export interface ApiResponse<T = unknown> {
  success: boolean
  data: T | null
  error: ApiError | null
  request_id: string
}

// ---------- invoke 响应 data（按形态分化） ----------

export interface ValidatorOutput {
  verdict: 'pass' | 'conditional_pass' | 'fail'
  issues: string[]
}

export interface HybridIntermediateEntry {
  iteration: number
  creative_output?: string[]
  validator_output?: ValidatorOutput
  controller_reflection?: { decision?: string }
}

export interface LongChainIntermediateEntry {
  iteration: number
  thought?: string
}

export interface ValidationData {
  verdict: 'pass' | 'conditional_pass' | 'fail'
  conclusion: string
  issues: string[]
  suggestions: string[]
  next_actions: string[]
  iterations_used: number
  termination_reason: string
  intermediate_log?: HybridIntermediateEntry[]
}

export interface CreativeData {
  candidates: string[]
  conclusion: string
  iterations_used: number
  termination_reason: string
}

export interface LongChainData {
  conclusion: string
  iterations_used: number
  termination_reason: string
  intermediate_log?: LongChainIntermediateEntry[]
}

export type InvokeData = ValidationData | CreativeData | LongChainData

// ---------- logs ----------

export interface LogItem {
  request_id: string
  timestamp: string
  enable_creative: boolean
  enable_validator: boolean
  verdict: string | null
  iterations_used: number | null
  termination_reason?: string | null
  duration_ms?: number
  user_query: string
  conclusion?: string | null
  error?: string | null
}

export interface LogsData {
  total: number
  items: LogItem[]
}
