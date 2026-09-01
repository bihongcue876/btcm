<script setup lang="ts">
import { computed } from 'vue'
import type {
  ApiError,
  CreativeData,
  InvokeData,
  LongChainData,
  Usage,
  ValidationData,
} from '@/types'
import {
  formatDurationMs,
  formatTokens,
  terminationLabel,
  terminationTagType,
  verdictLabel,
  verdictTagType,
} from '@/labels'
import IntermediateLog from './IntermediateLog.vue'

const props = defineProps<{
  data: InvokeData | null
  error: ApiError | null
  loading: boolean
  durationMs?: number
  elapsedMs?: number
  requestId?: string
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
const usage = computed<Usage | null>(() => props.data?.usage ?? null)
</script>

<template>
  <n-card title="调用结果" size="small">
    <n-spin :show="loading">
      <div v-if="loading" class="waiting">
        <span class="waiting-dot"></span>
        思考中，已耗时
        <b class="waiting-time n-num">{{ formatDurationMs(elapsedMs ?? 0) }}</b>
        <span class="waiting-note">（多轮生成-验证-反思可能需要数十秒，请耐心等待）</span>
      </div>

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
          <n-tooltip trigger="hover">
            <template #trigger>
              <span>
                终止原因
                <n-tag
                  size="small"
                  :type="terminationTagType(data.termination_reason)"
                  :bordered="false"
                >
                  {{ terminationLabel(data.termination_reason) }}
                </n-tag>
              </span>
            </template>
            {{ data.termination_reason }}
          </n-tooltip>
          <span v-if="durationMs != null">
            耗时
            <n-tag size="small" :bordered="false" class="n-num">
              {{ formatDurationMs(durationMs) }}
            </n-tag>
          </span>
          <n-tooltip v-if="requestId" trigger="hover">
            <template #trigger>
              <span class="rid">
                请求
                <code class="rid-code">{{ requestId.slice(0, 8) }}</code>
              </span>
            </template>
            request_id：{{ requestId }}（可在日志页对账）
          </n-tooltip>
        </div>

        <!-- token 计量 -->
        <div v-if="usage" class="usage">
          <span class="usage-item" title="输入 token 合计">
            输入 <b class="n-num">{{ formatTokens(usage.prompt_tokens) }}</b>
          </span>
          <span class="usage-item" title="输出 token 合计">
            输出 <b class="n-num">{{ formatTokens(usage.completion_tokens) }}</b>
          </span>
          <span class="usage-item" title="LLM 调用次数">
            调用 <b class="n-num">{{ usage.llm_calls }}</b>
          </span>
          <span v-if="usage.tool_calls" class="usage-item" title="MCP 工具调用次数">
            工具 <b class="n-num">{{ usage.tool_calls }}</b>
          </span>
        </div>

        <!-- 验证类形态（完整循环 / 纯验证） -->
        <template v-if="validation">
          <n-divider />
          <div class="verdict-line">
            <span class="verdict-label">判定</span>
            <n-tooltip trigger="hover">
              <template #trigger>
                <n-tag :type="verdictTagType(validation.verdict)" size="medium" round>
                  {{ verdictLabel(validation.verdict) }}
                </n-tag>
              </template>
              {{ validation.verdict }}
            </n-tooltip>
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

      <n-empty v-else description="尚未发起调用，左侧输入问题后点击「发起调用」" />
    </n-spin>
  </n-card>
</template>

<style scoped>
.waiting {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 10px 14px;
  margin-bottom: 12px;
  font-size: 13px;
  color: #9aa3b8;
  border: 1px solid rgba(109, 124, 255, 0.22);
  border-radius: 10px;
  background: rgba(109, 124, 255, 0.08);
}
.waiting-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #8794ff;
  box-shadow: 0 0 8px rgba(109, 124, 255, 0.8);
  animation: waiting-pulse 1.2s ease-in-out infinite;
}
@keyframes waiting-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}
.waiting-time {
  color: #dbe0ec;
  font-weight: 600;
}
.waiting-note {
  font-size: 12px;
  color: #6b7280;
}
.meta {
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
  font-size: 13px;
  color: #8b93a7;
}
.meta span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-variant-numeric: tabular-nums;
}
.rid {
  cursor: default;
}
.rid-code {
  font-size: 12px;
  padding: 2px 7px;
  border-radius: 6px;
  background: rgba(148, 163, 200, 0.12);
  color: #b9c1d3;
}
.usage {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}
.usage-item {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  font-size: 12px;
  color: #8a92a6;
  padding: 4px 10px;
  border: 1px solid rgba(148, 163, 200, 0.12);
  border-radius: 999px;
  background: rgba(18, 22, 33, 0.5);
}
.usage-item b {
  font-weight: 600;
  color: #b9c1d3;
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
