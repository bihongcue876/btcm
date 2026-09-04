<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { StreamAgentName, StreamBlock } from '@/types'

const props = defineProps<{
  blocks: StreamBlock[]
  /** 调用进行中：进行中的块显示脉冲动画；中止/结束后静止 */
  active?: boolean
}>()

const AGENT_LABELS: Record<StreamAgentName, string> = {
  creative: '创意',
  validator: '验证',
  meta: 'meta',
  controller: '总控',
}

// 完成的块默认收起，进行中的默认展开；用户可手动切换
const collapsed = ref<Set<string>>(new Set())

function isCollapsed(block: StreamBlock): boolean {
  return collapsed.value.has(block.id)
}

function toggle(block: StreamBlock) {
  const next = new Set(collapsed.value)
  if (next.has(block.id)) next.delete(block.id)
  else next.add(block.id)
  collapsed.value = next
}

const scroller = ref<HTMLElement | null>(null)

watch(
  () => props.blocks.map((b) => b.reasoning.length + b.content.length).join(','),
  async () => {
    await nextTick()
    const el = scroller.value
    if (el) el.scrollTop = el.scrollHeight
  },
)
</script>

<template>
  <n-card size="small" class="thinking-stream">
    <template #header>
      <span class="stream-title">思考过程</span>
    </template>
    <div ref="scroller" class="blocks">
      <div
        v-for="block in blocks"
        :key="block.id"
        class="block"
        :class="{ done: block.done }"
      >
        <button class="block-head" @click="toggle(block)">
          <span class="agent-tag" :data-agent="block.agent">
            {{ AGENT_LABELS[block.agent] }}
          </span>
          <span class="block-label">
            {{ block.iteration === 'finalize' ? '整合' : `第 ${block.iteration} 轮` }}
          </span>
          <span v-if="!block.done && props.active" class="pulse" aria-hidden="true"></span>
          <span v-else-if="!block.done && !props.active" class="halted" aria-hidden="true">
            已停止
          </span>
          <span class="chevron" :class="{ open: !isCollapsed(block) }">▾</span>
        </button>
        <div v-show="!isCollapsed(block)" class="block-body">
          <pre v-if="block.reasoning" class="reasoning">{{ block.reasoning }}</pre>
          <pre v-if="block.content" class="content">{{ block.content }}</pre>
          <div v-if="!block.reasoning && !block.content" class="waiting">等待输出…</div>
        </div>
      </div>
    </div>
  </n-card>
</template>

<style scoped>
.thinking-stream {
  margin-bottom: 16px;
}
.stream-title {
  font-size: 14px;
  font-weight: 500;
}
.blocks {
  max-height: 420px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.block {
  border: 1px solid #2a2f3a;
  border-radius: 6px;
  overflow: hidden;
  /* flex 子项默认可压缩：超长内容会被压扁并由 overflow:hidden 掩盖，
     固定高度让容器滚动条接管 */
  flex: none;
}
.block.done {
  opacity: 0.85;
}
.block-head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 10px;
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
  color: inherit;
  font-size: 13px;
}
.agent-tag {
  flex: none;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 12px;
  color: #fff;
  background: #4b9e5f;
}
.agent-tag[data-agent='validator'] {
  background: #b8862e;
}
.agent-tag[data-agent='meta'] {
  background: #6b7bd6;
}
.agent-tag[data-agent='controller'] {
  background: #b06fc9;
}
.block-label {
  color: #8b93a7;
}
.pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #4b9e5f;
  animation: pulse 1.2s ease-in-out infinite;
}
.halted {
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 11px;
  color: #f0a4a4;
  background: rgba(248, 113, 113, 0.12);
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.25; }
}
.chevron {
  margin-left: auto;
  transition: transform 0.15s;
  color: #6b7280;
}
.chevron.open {
  transform: rotate(180deg);
}
.block-body {
  padding: 4px 12px 10px;
}
.reasoning {
  margin: 0 0 6px;
  padding: 8px;
  background: rgba(128, 128, 128, 0.08);
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  color: #8b93a7;
  font-family: inherit;
}
.content {
  margin: 0;
  padding: 8px;
  background: rgba(75, 158, 95, 0.08);
  border-radius: 4px;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
}
.waiting {
  font-size: 12px;
  color: #6b7280;
}
</style>
