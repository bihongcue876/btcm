// 协议枚举值 → 中文标签与展示格式，供运行页 / 日志页 / 中间过程共用

export const VERDICT_LABELS: Record<string, string> = {
  pass: '通过',
  conditional_pass: '有条件通过',
  fail: '未通过',
}

export const TERMINATION_LABELS: Record<string, string> = {
  validation_passed: '验证通过',
  controller_stop: '总控收敛',
  max_iterations: '轮数上限',
  timeout: '超时',
  single_pass: '单次执行',
}

export function verdictLabel(v: string): string {
  return VERDICT_LABELS[v] ?? v
}

export type TagType = 'success' | 'warning' | 'error' | 'info' | 'default'

export function verdictTagType(v: string): TagType {
  if (v === 'pass') return 'success'
  if (v === 'conditional_pass') return 'warning'
  if (v === 'fail') return 'error'
  return 'default'
}

export function terminationLabel(r: string): string {
  return TERMINATION_LABELS[r] ?? r
}

export function terminationTagType(r: string): TagType {
  // 总控主动收敛与验证通过同为正常终止
  if (r === 'validation_passed' || r === 'controller_stop') return 'success'
  if (r === 'timeout') return 'warning'
  if (r === 'single_pass') return 'default'
  return 'info'
}

export function shapeLabel(creative: boolean, validator: boolean): string {
  if (creative && validator) return '完整循环'
  if (creative) return '纯创意'
  if (validator) return '纯验证'
  return '长链思考'
}

/** 830ms / 52.3s / 2m05s */
export function formatDurationMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const rest = Math.round(s % 60)
  return `${m}m${String(rest).padStart(2, '0')}s`
}

/** 12000 → 12k，600000 → 600k，1500000 → 1.5M */
export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}
