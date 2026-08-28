<script setup lang="ts">
import { reactive, ref } from 'vue'
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
  max_iterations: null as number | null,
  timeout: null as number | null,
})

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
  }
  if (form.candidate.trim()) payload.candidate = form.candidate.trim()
  if (form.context_summary.trim()) payload.context_summary = form.context_summary.trim()
  if (evidence.length) payload.evidence = evidence
  if (form.max_iterations != null || form.timeout != null) {
    payload.config = {}
    if (form.max_iterations != null) payload.config.max_iterations = form.max_iterations
    if (form.timeout != null) payload.config.timeout = form.timeout
  }
  emit('submit', payload)
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
        />
      </n-form-item>

      <n-form-item
        label="候选内容"
        :required="!props.creative && props.validator"
      >
        <n-input
          v-model:value="form.candidate"
          type="textarea"
          :rows="2"
          placeholder="待验证/待改进的候选内容（纯验证必填）"
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
</style>
