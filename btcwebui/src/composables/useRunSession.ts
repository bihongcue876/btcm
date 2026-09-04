import { ref } from 'vue'
import { ApiError, invokeStream } from '@/api/client'
import type {
  ApiError as ApiErrorType,
  InvokeData,
  InvokePayload,
  StreamBlock,
} from '@/types'

/**
 * 调用会话：模块级单例，跨路由存活。
 * 运行页卸载（切换到配置/日志页）不打断进行中的流式调用，
 * 计时、思考块与结果持续更新，回到运行页恢复展示。
 * 仅浏览器刷新/关闭会中断连接（后端随之取消任务）。
 */
const result = ref<InvokeData | null>(null)
const error = ref<ApiErrorType | null>(null)
const loading = ref(false)
const durationMs = ref<number>()
const requestId = ref('')
const elapsedMs = ref(0)
const streamBlocks = ref<StreamBlock[]>([])

let elapsedTimer: ReturnType<typeof setInterval> | undefined
let blockSeq = 0
let abortController: AbortController | null = null
// 调用序号：新请求覆盖旧请求时，旧调用的收尾不再干扰新调用的状态
let runSeq = 0
// 区分"用户主动中止"与"被新请求覆盖中止"
let userAborted = false
let startedAt = 0

function applyStreamEvent(event: Record<string, unknown>) {
  const type = event['type'] as string
  if (type === 'start') {
    requestId.value = String(event['request_id'] ?? '')
    return
  }
  if (type === 'agent_start') {
    streamBlocks.value.push({
      id: `b${++blockSeq}`,
      agent: event['agent'] as StreamBlock['agent'],
      iteration: event['iteration'] as number | string,
      reasoning: '',
      content: '',
      done: false,
    })
    return
  }
  if (type === 'delta') {
    const block = [...streamBlocks.value]
      .reverse()
      .find((b) => b.agent === event['agent'] && !b.done)
    if (block) {
      const key = event['kind'] === 'reasoning' ? 'reasoning' : 'content'
      block[key] += String(event['text'] ?? '')
    }
    return
  }
  if (type === 'agent_done') {
    const block = [...streamBlocks.value]
      .reverse()
      .find((b) => b.agent === event['agent'] && !b.done)
    if (block) block.done = true
  }
}

export async function startRun(payload: InvokePayload): Promise<void> {
  // 上一次调用若仍在进行，直接掐断，避免并发达上限
  abortController?.abort()
  abortController = new AbortController()
  const signal = abortController.signal
  const seq = ++runSeq
  userAborted = false

  loading.value = true
  error.value = null
  result.value = null
  requestId.value = ''
  durationMs.value = undefined
  streamBlocks.value = []
  startedAt = performance.now()
  elapsedMs.value = 0
  clearInterval(elapsedTimer)
  elapsedTimer = setInterval(() => {
    elapsedMs.value = Math.round(performance.now() - startedAt)
  }, 1000)
  try {
    await invokeStream(
      payload,
      {
        onEvent: (e) => applyStreamEvent(e as unknown as Record<string, unknown>),
        onDone: (body) => {
          durationMs.value = Math.round(performance.now() - startedAt)
          result.value = body.data
        },
        onError: (body) => {
          durationMs.value = Math.round(performance.now() - startedAt)
          error.value = body.error ?? { code: 'UNKNOWN', message: '未知错误' }
        },
      },
      signal,
    )
  } catch (e) {
    // 已被更新的调用覆盖：任何错误都不再写状态，避免污染新调用
    if (seq !== runSeq) {
      // 空分支：静默吞掉
    } else if (e instanceof ApiError && e.code === 'STREAM_INTERRUPTED') {
      // 事件已部分展示，仅提示连接中断
      error.value = { code: e.code, message: e.message }
    } else if (e instanceof DOMException && e.name === 'AbortError') {
      // 用户主动中止：记录状态（提示由调用方在组件存活期间弹出）
      if (userAborted) {
        durationMs.value = Math.round(performance.now() - startedAt)
        error.value = {
          code: 'ABORTED',
          message: '已中止本次调用，服务端任务已停止；思考过程保留在上方',
        }
      }
    } else if (e instanceof ApiError) {
      error.value = { code: e.code, message: e.message }
    } else {
      error.value = { code: 'UNKNOWN', message: String(e) }
    }
  } finally {
    // 仅当本次调用仍是最新调用时才收尾，避免旧调用的清理覆盖新调用的状态
    if (seq === runSeq) {
      clearInterval(elapsedTimer)
      loading.value = false
    }
  }
}

/** 用户主动中止当前调用；返回是否有进行中的调用可中止 */
export function abortRun(): boolean {
  if (!loading.value || !abortController) return false
  userAborted = true
  abortController.abort()
  return true
}

export function useRunSession() {
  return {
    result,
    error,
    loading,
    durationMs,
    requestId,
    elapsedMs,
    streamBlocks,
  }
}
