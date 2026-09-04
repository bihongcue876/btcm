<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useMessage } from 'naive-ui'
import type { InvokePayload } from '@/types'

const props = defineProps<{
  creative: boolean
  validator: boolean
}>()
const emit = defineEmits<{
  submit: [payload: InvokePayload]
}>()
const message = useMessage()

const form = reactive({
  user_query: '',
  candidate: '',
  evidenceText: '',
  context_summary: '',
  /** 思考深度：0 略想 / 1 通用 / 2 深层 */
  effort: 1,
  max_iterations: null as number | null,
  timeout: null as number | null,
})

const EFFORT_VALUES = ['light', 'standard', 'deep'] as const

const EFFORT_HINTS: Record<number, string> = {
  0: '略想：单轮快速出结果，不展开深思',
  1: '通用：按全局配置的正常循环深度',
  2: '深层：充分深思，多角度检验逻辑与事实',
}

const effortHint = computed(() => EFFORT_HINTS[form.effort] ?? '')

const showAdvanced = ref(false)
const submitting = ref(false)

async function handleSubmit() {
  if (!form.user_query.trim()) {
    message.warning('请输入用户问题')
    return
  }
  if (!props.creative && props.validator && !form.candidate.trim()) {
    message.warning('纯验证形态下 candidate 必填')
    return
  }
  const evidence = form.evidenceText
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)

  const payload: InvokePayload = {
    user_query: form.user_query.trim(),
    enable_creative: props.creative,
    enable_validator: props.validator,
    effort: EFFORT_VALUES[form.effort],
  }
  // 完整循环/纯验证下候选为可选输入（完整循环作为首轮候选）；纯创意不发送
  if (props.validator && form.candidate.trim()) payload.candidate = form.candidate.trim()
  if (form.context_summary.trim()) payload.context_summary = form.context_summary.trim()
  if (evidence.length) payload.evidence = evidence
  if (form.max_iterations != null || form.timeout != null) {
    payload.config = {}
    if (form.max_iterations != null) payload.config.max_iterations = form.max_iterations
    if (form.timeout != null) payload.config.timeout = form.timeout
  }
  emit('submit', payload)
}

function onQueryKeydown(e: KeyboardEvent) {
  if (e.ctrlKey && e.key === 'Enter') {
    e.preventDefault()
    handleSubmit()
  }
}

defineExpose({ setSubmitting: (v: boolean) => (submitting.value = v) })
</script>

<template>
  <n-card title="发起调用" size="small">
    <n-form label-placement="left" label-width="104">
      <n-form-item label="用户问题" required>
        <n-input
          v-model:value="form.user_query"
          type="textarea"
          :rows="2"
          placeholder="例如：下周去东京，预算 5000，能去哪些地方？"
          @keydown="onQueryKeydown"
        />
      </n-form-item>

      <n-form-item
        v-if="props.validator"
        label="候选内容"
        :required="!props.creative && props.validator"
      >
        <n-input
          v-model:value="form.candidate"
          type="textarea"
          :rows="2"
          :placeholder="
            props.creative
              ? '可选：作为首轮候选进入循环，留空则由创意 Agent 发散生成'
              : '待验证/待改进的候选内容（纯验证必填）'
          "
        />
      </n-form-item>

      <n-form-item label="参考证据">
        <n-input
          v-model:value="form.evidenceText"
          type="textarea"
          :rows="2"
          placeholder="每行一条证据，可选"
        />
      </n-form-item>

      <n-form-item label="上下文摘要">
        <n-input
          v-model:value="form.context_summary"
          placeholder="由主控压缩的上下文摘要，可选"
        />
      </n-form-item>

      <n-form-item label="思考深度">
        <div class="effort">
          <n-slider
            v-model:value="form.effort"
            :min="0"
            :max="2"
            :step="1"
            :marks="{ 0: '略想', 1: '通用', 2: '深层' }"
          />
          <div class="effort-hint">{{ effortHint }}</div>
        </div>
      </n-form-item>

      <n-form-item label="高级参数">
        <n-collapse-transition :show="showAdvanced">
          <div class="advanced">
            <n-input-number
              v-model:value="form.max_iterations"
              :min="1"
              :max="10"
              placeholder="轮数上限"
            >
              <template #prefix>轮数</template>
            </n-input-number>
            <n-input-number
              v-model:value="form.timeout"
              :min="1"
              :max="3600"
              placeholder="超时秒数"
            >
              <template #prefix>超时</template>
            </n-input-number>
          </div>
        </n-collapse-transition>
        <n-button text type="primary" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? '收起' : '展开（仅当次调用生效）' }}
        </n-button>
      </n-form-item>

      <n-form-item label=" ">
        <n-button type="primary" size="large" :loading="submitting" @click="handleSubmit">
          发起调用
        </n-button>
        <span class="submit-hint">Ctrl+Enter 快速提交</span>
      </n-form-item>
    </n-form>
  </n-card>
</template>

<style scoped>
.advanced {
  display: flex;
  gap: 12px;
  margin-bottom: 8px;
}
.effort {
  width: 100%;
  padding: 0 8px;
}
.effort-hint {
  margin-top: 22px;
  font-size: 12px;
  color: #6b7280;
}
.submit-hint {
  margin-left: 12px;
  font-size: 12px;
  color: #6b7280;
}
</style>
