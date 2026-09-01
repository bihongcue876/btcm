<script setup lang="ts">
import { h, onMounted, onUnmounted, ref } from 'vue'
import { NTag, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { api, ApiError, ADMIN_TOKEN_CHANGED_EVENT } from '@/api/client'
import type { LogItem } from '@/types'
import {
  formatDurationMs,
  formatTokens,
  shapeLabel,
  terminationLabel,
  verdictLabel,
  verdictTagType,
} from '@/labels'

const message = useMessage()
const loading = ref(false)
const items = ref<LogItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { hour12: false })
}

function renderDetail(row: LogItem) {
  const nodes = []
  nodes.push(
    h('div', { class: 'detail-row' }, [
      h('div', { class: 'detail-label' }, 'request_id'),
      h('code', { class: 'detail-rid' }, row.request_id),
    ]),
  )
  if (row.error) {
    nodes.push(
      h('div', { class: 'detail-error' }, [
        h(
          NTag,
          { size: 'small', type: 'error', bordered: false },
          { default: () => row.error },
        ),
      ]),
    )
  }
  if (row.conclusion) {
    nodes.push(
      h('div', { class: 'detail-text' }, [
        h('div', { class: 'detail-label' }, '结论'),
        row.conclusion,
      ]),
    )
  }
  if (row.usage) {
    nodes.push(
      h('div', { class: 'detail-usage' }, [
        h('div', { class: 'detail-label' }, 'token 计量'),
        `输入 ${formatTokens(row.usage.prompt_tokens)} · 输出 ${formatTokens(
          row.usage.completion_tokens,
        )} · LLM 调用 ${row.usage.llm_calls} 次` +
          (row.usage.tool_calls ? ` · 工具调用 ${row.usage.tool_calls} 次` : ''),
      ]),
    )
  }
  if (!row.conclusion && !row.error) {
    nodes.push(h('div', { class: 'detail-text dim' }, '无结论'))
  }
  return h('div', { class: 'detail' }, nodes)
}

async function load() {
  loading.value = true
  try {
    const data = await api.getLogs(pageSize.value, (page.value - 1) * pageSize.value)
    total.value = data.total
    items.value = data.items
  } catch (e) {
    message.error(e instanceof ApiError ? e.message : String(e))
  } finally {
    loading.value = false
  }
}

function onTokenChanged() {
  load()
}

const columns: DataTableColumns<LogItem> = [
  { type: 'expand', renderExpand: renderDetail },
  { title: '时间', key: 'timestamp', width: 160, render: (r) => formatTime(r.timestamp) },
  {
    title: '形态',
    key: 'shape',
    width: 90,
    render: (r) => shapeLabel(r.enable_creative, r.enable_validator),
  },
  {
    title: '判定',
    key: 'verdict',
    width: 110,
    render: (r) => {
      const v = r.verdict
      return v
        ? h(
            NTag,
            { size: 'small', type: verdictTagType(v) },
            { default: () => verdictLabel(v) },
          )
        : '—'
    },
  },
  {
    title: '状态',
    key: 'error',
    width: 90,
    render: (r) =>
      r.error
        ? h(
            NTag,
            { size: 'small', type: 'error', bordered: false },
            { default: () => r.error },
          )
        : h(
            NTag,
            { size: 'small', type: 'success', bordered: false },
            { default: () => '成功' },
          ),
  },
  { title: '轮数', key: 'iterations_used', width: 60, render: (r) => r.iterations_used ?? '—' },
  {
    title: '耗时',
    key: 'duration_ms',
    width: 80,
    render: (r) => (r.duration_ms != null ? formatDurationMs(r.duration_ms) : '—'),
  },
  {
    title: '终止',
    key: 'termination_reason',
    width: 90,
    render: (r) => (r.termination_reason ? terminationLabel(r.termination_reason) : '—'),
  },
  { title: '问题', key: 'user_query', ellipsis: { tooltip: true } },
]

onMounted(() => {
  load()
  window.addEventListener(ADMIN_TOKEN_CHANGED_EVENT, onTokenChanged)
})
onUnmounted(() => window.removeEventListener(ADMIN_TOKEN_CHANGED_EVENT, onTokenChanged))
</script>

<template>
  <div>
    <header class="page-head">
      <div>
        <h1 class="page-title">日志</h1>
        <p class="page-desc">历史调用记录（共 {{ total }} 条），点击行首展开结论与 token 计量</p>
      </div>
      <n-button secondary size="small" :loading="loading" @click="load">刷新</n-button>
    </header>
    <n-card size="small">
      <n-data-table
        remote
        :loading="loading"
        :columns="columns"
        :data="items"
        :row-key="(r: LogItem) => r.request_id"
        :pagination="false"
      >
      <template #empty>暂无调用记录</template>
    </n-data-table>
    <div class="pager">
      <n-pagination
        v-model:page="page"
        :page-size="pageSize"
        :item-count="total"
        @update:page="load"
      />
    </div>
    </n-card>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
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
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
/* renderExpand 内容不带 scoped 属性，需穿透 */
.n-data-table :deep(.detail) {
  padding: 4px 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.n-data-table :deep(.detail-row) {
  display: flex;
  align-items: center;
  gap: 10px;
}
.n-data-table :deep(.detail-rid) {
  font-size: 12px;
  color: #b9c1d3;
  background: rgba(148, 163, 200, 0.1);
  padding: 2px 8px;
  border-radius: 6px;
}
.n-data-table :deep(.detail-error) {
  margin-bottom: 0;
}
.n-data-table :deep(.detail-label) {
  font-size: 12px;
  color: #888;
  margin-bottom: 2px;
  flex: none;
}
.n-data-table :deep(.detail-text) {
  font-size: 13px;
  line-height: 1.6;
}
.n-data-table :deep(.detail-usage) {
  font-size: 12px;
  color: #9aa3b8;
  font-variant-numeric: tabular-nums;
}
.n-data-table :deep(.dim) {
  color: #999;
}
</style>
