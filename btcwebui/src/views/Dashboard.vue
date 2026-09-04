<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '@/api/client'
import { formatDurationMs } from '@/labels'
import { abortRun, startRun, useRunSession } from '@/composables/useRunSession'
import type { InvokePayload } from '@/types'
import InvokeForm from '@/components/InvokeForm.vue'
import ResultView from '@/components/ResultView.vue'
import ThinkingStream from '@/components/ThinkingStream.vue'

const message = useMessage()
// 形态开关跟随全局配置（配置页 enable_creative / enable_validator），运行页只读展示
const creative = ref(true)
const validator = ref(true)

// 调用会话为模块级单例：切换页面不中止进行中的流，回到本页继续展示
const { result, error, loading, durationMs, requestId, elapsedMs, streamBlocks } =
  useRunSession()

const SHAPE_META = {
  hybrid: { label: '完整循环', desc: '生成 → 验证 → 反思' },
  creative: { label: '纯创意', desc: '单次发散候选' },
  validation: { label: '纯验证', desc: '单次判定候选' },
  longchain: { label: '长链持续思考', desc: 'controller 多轮自省' },
} as const

const shape = computed(() => {
  const key = creative.value && validator.value
    ? 'hybrid'
    : creative.value
      ? 'creative'
      : validator.value
        ? 'validation'
        : 'longchain'
  return { key, ...SHAPE_META[key] }
})

async function syncSwitchesFromGlobal() {
  try {
    const cfg = await api.getConfig()
    creative.value = cfg.enable_creative
    validator.value = cfg.enable_validator
  } catch {
    // 拉取失败保持默认（后端默认均为 true），不阻塞运行台
  }
}

async function handleSubmit(payload: InvokePayload) {
  await startRun(payload)
}

function handleAbort() {
  if (abortRun()) message.info('已中止当前调用')
}

onMounted(syncSwitchesFromGlobal)
</script>

<template>
  <div class="dashboard">
    <header class="page-head">
      <div>
        <h1 class="page-title">运行</h1>
        <p class="page-desc">
          输入任务，观察生成-验证-反思过程
          <span
            class="shape-tag"
            :class="`shape-${shape.key}`"
            :title="`当前形态跟随全局配置：${shape.desc}（可在配置页调整）`"
          >
            {{ shape.label }}
          </span>
        </p>
      </div>
      <div class="head-status">
        <transition name="status-fade">
          <span v-if="loading" class="status-chip running">
            <span class="status-dot"></span>
            运行中 · {{ formatDurationMs(elapsedMs) }}
          </span>
          <span v-else-if="result" class="status-chip done">已完成</span>
          <span v-else-if="error" class="status-chip fail">
            {{ error.code === 'ABORTED' ? '已中止' : '出错' }}
          </span>
        </transition>
      </div>
    </header>

    <n-grid :cols="2" :x-gap="16" responsive="screen" item-responsive class="main-grid">
      <n-grid-item span="2 m:1 l:1">
        <InvokeForm
          :creative="creative"
          :validator="validator"
          :running="loading"
          @submit="handleSubmit"
          @abort="handleAbort"
        />
      </n-grid-item>
      <n-grid-item span="2 m:1 l:1">
        <div>
          <ThinkingStream
            v-if="streamBlocks.length"
            :blocks="streamBlocks"
            :active="loading"
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
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.page-title {
  margin: 0;
  font-size: 22px;
  font-weight: 500;
  letter-spacing: 0.5px;
  background: linear-gradient(92deg, #e8ecf5 30%, #a8bcff 75%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.page-desc {
  margin: 6px 0 0;
  font-size: 13px;
  color: #8b93a7;
}
/* 形态标签：只读展示当前运行形态（跟随全局配置），替代原四卡选择器 */
.shape-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: 8px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 1.5;
  border: 1px solid rgba(148, 163, 200, 0.2);
  background: rgba(18, 22, 33, 0.5);
  color: #9aa3b8;
  vertical-align: 1px;
  white-space: nowrap;
}
.shape-tag::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 6px currentColor;
}
.shape-hybrid {
  color: #a8bcff;
  border-color: rgba(110, 140, 255, 0.35);
}
.shape-creative {
  color: #9cc2ff;
  border-color: rgba(91, 155, 255, 0.3);
}
.shape-validation {
  color: #f0c37a;
  border-color: rgba(230, 162, 60, 0.3);
}
.shape-longchain {
  color: #c9b1ff;
  border-color: rgba(160, 120, 255, 0.35);
}
.head-status {
  padding-top: 4px;
}
.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 200, 0.16);
  background: rgba(18, 22, 33, 0.5);
  color: #9aa3b8;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.status-chip.running {
  color: #a8bcff;
  border-color: rgba(109, 124, 255, 0.35);
}
.status-chip.running .status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #8794ff;
  box-shadow: 0 0 8px rgba(109, 124, 255, 0.8);
  animation: status-pulse 1.2s ease-in-out infinite;
}
.status-chip.done {
  color: #7ee2b8;
  border-color: rgba(52, 211, 153, 0.3);
}
.status-chip.fail {
  color: #f0a4a4;
  border-color: rgba(248, 113, 113, 0.3);
}
@keyframes status-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}
.status-fade-enter-active,
.status-fade-leave-active {
  transition: opacity 0.2s ease;
}
.status-fade-enter-from,
.status-fade-leave-to {
  opacity: 0;
}
.main-grid {
  align-items: start;
}
@media (max-width: 640px) {
  .page-head {
    flex-direction: column;
    gap: 8px;
  }
}
</style>
