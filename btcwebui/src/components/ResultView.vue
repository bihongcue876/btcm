<script setup lang="ts">
import { computed } from 'vue'
import type {
  ApiError,
  CreativeData,
  InvokeData,
  LongChainData,
  ValidationData,
} from '@/types'
import IntermediateLog from './IntermediateLog.vue'

const props = defineProps<{
  data: InvokeData | null
  error: ApiError | null
  loading: boolean
  durationMs?: number
}>()

// 类型守卫：按 data 键集合分派形态（与协议 data 分化一一对应）
const validation = computed<ValidationData | null>(() =>
  props.data && 'verdict' in props.data ? (props.data as ValidationData) : null,
)
const creative = computed<CreativeData | null>(() =>
  props.data && 'candidates' in props.data ? (props.data as CreativeData) : null,
)
const longChain = computed<LongChainData | null>(() =>
  props.data && !('verdict' in props.data) && !('candidates' in props.data)
    ? (props.data as LongChainData)
    : null,
)
const logEntries = computed(() =>
  validation.value?.intermediate_log ?? longChain.value?.intermediate_log ?? null,
)
const logType = computed(() => (longChain.value ? ('longchain' as const) : ('hybrid' as const)))

function verdictType(v: string) {
  if (v === 'pass') return 'success'
  if (v === 'conditional_pass') return 'warning'
  return 'error'
}

function reasonType(r: string) {
  if (r === 'validation_passed') return 'success'
  if (r === 'timeout') return 'warning'
  if (r === 'single_pass') return 'default'
  return 'info'
}
</script>

<template>
  <n-card title="调用结果" size="small">
    <n-spin :show="loading">
      <n-alert v-if="error" type="error" :show-icon="true">
        <template #header>
          <code>{{ error.code }}</code>
        </template>
        {{ error.message }}
      </n-alert>

      <template v-else-if="data">
        <div class="meta">
          <span>
            轮数
            <n-tag size="small" :bordered="false">{{ data.iterations_used }}</n-tag>
          </span>
          <span>
            终止原因
            <n-tag size="small" :type="reasonType(data.termination_reason)" :bordered="false">
              {{ data.termination_reason }}
            </n-tag>
          </span>
          <span v-if="durationMs != null">
            耗时
            <n-tag size="small" :bordered="false">{{ durationMs }}ms</n-tag>
          </span>
        </div>

        <!-- 验证类形态（完整循环 / 纯验证） -->
        <template v-if="validation">
          <n-divider />
          <div class="verdict-line">
            <span class="verdict-label">判定</span>
            <n-tag :type="verdictType(validation.verdict)" size="medium" round>
              {{ validation.verdict }}
            </n-tag>
          </div>
          <p class="conclusion">{{ validation.conclusion }}</p>

          <div class="block" v-if="validation.issues.length">
            <div class="label">发现的问题</div>
            <n-list size="small" bordered>
              <n-list-item v-for="(issue, i) in validation.issues" :key="i">
                {{ issue }}
              </n-list-item>
            </n-list>
          </div>

          <div class="block" v-if="validation.suggestions.length">
            <div class="label">改进建议</div>
            <n-list size="small" bordered>
              <n-list-item v-for="(s, i) in validation.suggestions" :key="i">
                {{ s }}
              </n-list-item>
            </n-list>
          </div>

          <div class="block" v-if="validation.next_actions.length">
            <div class="label">下一步行动</div>
            <n-list size="small" bordered>
              <n-list-item v-for="(a, i) in validation.next_actions" :key="i">
                {{ a }}
              </n-list-item>
            </n-list>
          </div>
        </template>

        <!-- 纯创意 -->
        <template v-else-if="creative">
          <n-divider />
          <div class="label">候选方案</div>
          <n-list bordered size="small">
            <n-list-item v-for="(c, i) in creative.candidates" :key="i">
              <n-number-animation :from="0" :to="i + 1" />. {{ c }}
            </n-list-item>
          </n-list>
          <div class="block" v-if="creative.conclusion">
            <div class="label">结论</div>
            <p class="conclusion">{{ creative.conclusion }}</p>
          </div>
        </template>

        <!-- 长链持续思考 -->
        <template v-else-if="longChain">
          <n-divider />
          <p class="conclusion">{{ longChain.conclusion }}</p>
        </template>

        <!-- 中间过程 -->
        <template v-if="logEntries">
          <n-divider />
          <div class="label">中间过程（intermediate_log）</div>
          <IntermediateLog :entries="logEntries" :type="logType" />
        </template>
      </template>

      <n-empty v-else description="尚未发起调用" />
    </n-spin>
  </n-card>
</template>

<style scoped>
.meta {
  display: flex;
  gap: 16px;
  align-items: center;
  font-size: 13px;
  color: #8b93a7;
}
.meta span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-variant-numeric: tabular-nums;
}
.verdict-line {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.verdict-label {
  font-size: 13px;
  color: #8b93a7;
}
.verdict-line :deep(.n-tag) {
  font-size: 15px;
  font-weight: 500;
  padding: 6px 18px;
  letter-spacing: 0.4px;
  box-shadow: 0 0 16px rgba(255, 255, 255, 0.06);
}
.conclusion {
  font-size: 14px;
  line-height: 1.7;
  margin: 0 0 8px;
  color: #dfe3ec;
}
.block {
  margin-top: 12px;
}
.label {
  font-size: 13px;
  color: #8b93a7;
  margin-bottom: 6px;
}
</style>
