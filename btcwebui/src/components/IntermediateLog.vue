<script setup lang="ts">
import type { HybridIntermediateEntry, LongChainIntermediateEntry } from '@/types'

defineProps<{
  entries: (HybridIntermediateEntry | LongChainIntermediateEntry)[]
  type: 'hybrid' | 'longchain'
}>()

function verdictType(v: string | undefined) {
  if (v === 'pass') return 'success'
  if (v === 'conditional_pass') return 'warning'
  if (v === 'fail') return 'error'
  return 'default'
}
</script>

<template>
  <n-timeline v-if="entries && entries.length">
    <n-timeline-item
      v-for="entry in entries"
      :key="entry.iteration"
      :type="'default'"
      :title="`第 ${entry.iteration} 轮`"
      content-style="padding-top: 4px"
    >
      <template v-if="type === 'hybrid' && 'creative_output' in entry">
        <div class="block">
          <div class="label">创意输出</div>
          <ul class="list" v-if="entry.creative_output?.length">
            <li v-for="(c, i) in entry.creative_output" :key="i">{{ c }}</li>
          </ul>
        </div>
        <div
          class="block"
          v-if="entry.validator_output"
        >
          <div class="label">
            验证判定
            <n-tag
              size="small"
              :type="verdictType(entry.validator_output.verdict)"
              class="ml-1"
            >
              {{ entry.validator_output.verdict }}
            </n-tag>
          </div>
          <ul class="list" v-if="entry.validator_output.issues?.length">
            <li v-for="(issue, i) in entry.validator_output.issues" :key="i">
              {{ issue }}
            </li>
          </ul>
        </div>
        <div class="block" v-if="entry.controller_reflection?.decision">
          <div class="label">
            总控决策
            <n-tag size="small" type="info" class="ml-1">
              {{ entry.controller_reflection.decision }}
            </n-tag>
          </div>
        </div>
      </template>
      <template v-else-if="type === 'longchain' && 'thought' in entry">
        <div class="block">
          <div class="label">思考要点</div>
          <p class="thought">{{ entry.thought }}</p>
        </div>
      </template>
    </n-timeline-item>
  </n-timeline>
  <n-empty v-else description="无中间过程记录" />
</template>

<style scoped>
.block {
  margin-bottom: 6px;
}
.label {
  font-size: 12px;
  color: #888;
  margin-bottom: 2px;
}
.list {
  margin: 0;
  padding-left: 18px;
}
.list li {
  font-size: 13px;
  line-height: 1.6;
}
.thought {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
}
.ml-1 {
  margin-left: 6px;
}
</style>
