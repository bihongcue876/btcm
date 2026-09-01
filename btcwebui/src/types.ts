// 类型定义，对齐 share/protocol.md（alpha 阶段随实现迭代）

export interface ProviderConfig {
  base_url: string
  api_key?: string | null
  models: string[]
  timeout?: number
  enabled?: boolean
  options?: Record<string, unknown>
  /** 只读：服务端是否已设置密钥（含环境变量注入），GET 回显 */
  api_key_set?: boolean
}

export interface MCPServerConfig {
  preset?: string | null
  url?: string | null
  api_key?: string | null
  enabled?: boolean
  timeout?: number
  allowed_tools?: string[]
  allow_private?: boolean
  /** 只读：服务端是否已设置密钥（含环境变量注入），GET 回显 */
  api_key_set?: boolean
}

export interface AgentConfig {
  provider?: string | null
  model?: string | null
  num_candidates?: number
  temperature?: number
  max_tokens?: number
  timeout?: number | null
  enable_web_search?: boolean
  web_sources?: string[]
  mcp_servers?: string[]
  log_intermediate?: boolean
}

export interface GlobalConfig {
  max_iterations: number
  timeout: number
  enable_creative: boolean
  enable_validator: boolean
  admin_token?: string | null
  /** 只读：服务端是否已设置管理令牌（含环境变量注入），GET 回显 */
  admin_token_set?: boolean
  lock_invoke?: boolean
  default_provider?: string | null
  default_model?: string | null
  structured_output?: string
  providers: Record<string, ProviderConfig>
  mcp_servers: Record<string, MCPServerConfig>
  agents: Record<string, AgentConfig>
}

export interface RuntimeAgentOverride {
  num_candidates?: number | null
  temperature?: number | null
  max_tokens?: number | null
  timeout?: number | null
  enable_web_search?: boolean | null
  web_sources?: string[] | null
  mcp_servers?: string[] | null
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

export interface Usage {
  prompt_tokens: number
  completion_tokens: number
  llm_calls: number
  tool_calls: number
}

export interface ValidatorOutput {
  verdict: 'pass' | 'conditional_pass' | 'fail'
  issues: string[]
}

export interface HybridIntermediateEntry {
  iteration: number
  creative_output?: string[]
  validator_output?: ValidatorOutput
  meta_reflection?: { decision?: string; next_direction?: string }
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
  usage?: Usage
}

export interface CreativeData {
  candidates: string[]
  conclusion: string
  iterations_used: number
  termination_reason: string
  usage?: Usage
}

export interface LongChainData {
  conclusion: string
  iterations_used: number
  termination_reason: string
  intermediate_log?: LongChainIntermediateEntry[]
  usage?: Usage
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
  usage?: Usage | null
}

export interface LogsData {
  total: number
  items: LogItem[]
}

// ---------- health ----------

export interface HealthData {
  status: string
  version: string
  uptime_s: number
}
