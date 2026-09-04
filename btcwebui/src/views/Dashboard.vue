<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { api, ApiError, invokeStream } from '@/api/client'
import type {
  ApiError as ApiErrorType,
  InvokeData,
  InvokePayload,
  StreamBlock,
} from '@/types'
import InvokeForm from '@/components/InvokeForm.vue'
import ResultView from '@/components/ResultView.vue'
import ShapeIndicator from '@/components/ShapeIndicator.vue'
import ThinkingStream from '@/components/ThinkingStream.vue'

const message = useMessage()
// 开关默认值跟随全局配置（协议约定：请求未提供时回落全局默认）
const creative = ref(true)
const validator = ref(true)
const result = ref<InvokeData | null>(null)
const error = ref<ApiErrorType | null>(null)
const loading = ref(false)
const durationMs = ref<number>()
const requestId = ref('')
const elapsedMs = ref(0)
const invokeForm = ref<InstanceType<typeof InvokeForm> | null>(null)
let elapsedTimer: ReturnType<typeof setInterval> | undefined

// 流式面板：agent_start/delta/agent_done 事件聚合为可折叠块
const streamBlocks = ref<StreamBlock[]>([])
let blockSeq = 0
let abortController: AbortController | null = null

async function syncSwitchesFromGlobal() {
  try {
    const cfg = await api.getConfig()
    creative.value = cfg.enable_creative
    validator.value = cfg.enable_validator
  } catch {
    // 拉取失败保持默认（后端默认均为 true），不阻塞运行台
  }
}

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

async function handleSubmit(payload: InvokePayload) {
  // 上一次调用若仍在进行，直接掐断，避免并发达上限
  abortController?.abort()
  abortController = new AbortController()
  const signal = abortController.signal

  loading.value = true
  error.value = null
  result.value = null
  requestId.value = ''
  streamBlocks.value = []
  invokeForm.value?.setSubmitting(true)
  const started = performance.now()
  elapsedMs.value = 0
  clearInterval(elapsedTimer)
  elapsedTimer = setInterval(() => {
    elapsedMs.value = Math.round(performance.now() - started)
  }, 1000)
  try {
    await invokeStream(
      payload,
      {
        onEvent: (e) => applyStreamEvent(e as unknown as Record<string, unknown>),
        onDone: (body) => {
          durationMs.value = Math.round(performance.now() - started)
          result.value = body.data
        },
        onError: (body) => {
          durationMs.value = Math.round(performance.now() - started)
          error.value = body.error ?? { code: 'UNKNOWN', message: '未知错误' }
        },
      },
      signal,
    )
  } catch (e) {
    if (e instanceof ApiError && e.code === 'STREAM_INTERRUPTED') {
      // 事件已部分展示，仅提示连接中断
      error.value = { code: e.code, message: e.message }
    } else if (e instanceof DOMException && e.name === 'AbortError') {
      // 用户主动重新发起，不算错误
    } else if (e instanceof ApiError) {
      error.value = { code: e.code, message: e.message }
    } else {
      error.value = { code: 'UNKNOWN', message: String(e) }
    }
  } finally {
    clearInterval(elapsedTimer)
    loading.value = false
    invokeForm.value?.setSubmitting(false)
  }
}

onMounted(syncSwitchesFromGlobal)
onUnmounted(() => {
  clearInterval(elapsedTimer)
  abortController?.abort()
})
</script>

<template>
  <div class="dashboard">
    <header class="page-head">
      <div>
        <h1 class="page-title">运行</h1>
        <p class="page-desc">输入任务，观察生成-验证-反思过程</p>
      </div>
    </header>

    <ShapeIndicator v-model:creative="creative" v-model:validator="validator" class="shape" />

    <n-grid :cols="2" :x-gap="16" responsive="screen" item-responsive class="main-grid">
      <n-grid-item span="2 m:1 l:1">
        <InvokeForm
          ref="invokeForm"
          :creative="creative"
          :validator="validator"
          @submit="handleSubmit"
        />
      </n-grid-item>
      <n-grid-item span="2 m:1 l:1">
        <div>
          <ThinkingStream
            v-if="streamBlocks.length"
            :blocks="streamBlocks"
          />
          <ResultView
            :data="result"
            :error="error"
            :loading="loading"
            :duration-ms="durationMs"
            :elapsed-ms="elapsedMs"
            :request-id="requestId"
          />
        </div>
      </n-grid-item>
    </n-grid>
  </div>
</template>

<style scoped>
.page-head {
  margin-bottom: 16px;
}
.page-title {
  margin: 0;
  font-size: 22px;
  font-weight: 500;
  letter-spacing: 0.5px;
}
.page-desc {
  margin: 6px 0 0;
  font-size: 13px;
  color: #8b93a7;
}
.shape {
  margin-bottom: 18px;
}
.main-grid {
  align-items: start;
}
</style>
