<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref } from 'vue'
import { NTag, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { api, ApiError, ADMIN_TOKEN_CHANGED_EVENT } from '@/api/client'
import type { LogItem } from '@/types'
import { formatDurationMs } from '@/labels'

const message = useMessage()
const loading = ref(false)
const items = ref<LogItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

// ---------- 结论缩放 ----------

const ZOOM_KEY = 'btcm_logs_zoom'
const ZOOM_MIN = 12
const ZOOM_MAX = 26
const ZOOM_STEP = 2
const ZOOM_DEFAULT = 13

function loadZoom(): number {
  const saved = Number(localStorage.getItem(ZOOM_KEY))
  return Number.isInteger(saved) && saved >= ZOOM_MIN && saved <= ZOOM_MAX ? saved : ZOOM_DEFAULT
}
const zoom = ref(loadZoom())

function applyZoom(v: number) {
  zoom.value = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, v))
  localStorage.setItem(ZOOM_KEY, String(zoom.value))
}

/** 结论列内联字号：render 是普通函数，用 CSS 变量下发避免每帧重渲染整表 */
const zoomVar = computed(() => ({ '--conclusion-fs': `${zoom.value}px` }))

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { hour12: false })
}

/** 结论列：成功显示结论，失败显示错误码提示；字号随缩放控件变化 */
function renderOutcome(row: LogItem) {
  if (row.conclusion) {
    return h('span', { class: 'outcome conclusion', title: row.conclusion }, row.conclusion)
  }
  if (row.error) {
    return h('span', { class: 'outcome error' }, `调用失败（${row.error}）`)
  }
  return h('span', { class: 'outcome dim' }, '无结论')
}

async function load() {
  loading.value = true
  try {
    const data = await api.getLogs(pageSize.value, (page.value - 1) * pageSize.value)
    total.value = data.total
    items.value = data.items
    // 日志条目减少导致当前页越界：回退到最后一页重拉
    if (!data.items.length && data.total > 0 && page.value > 1) {
      page.value = Math.max(1, Math.ceil(data.total / pageSize.value))
      await load()
      return
    }
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
  { title: '时间', key: 'timestamp', width: 165, render: (r) => formatTime(r.timestamp) },
  {
    title: '状态',
    key: 'error',
    width: 80,
    render: (r) =>
      r.error
        ? h(
            NTag,
            { size: 'small', type: 'error', bordered: false },
            { default: () => '失败' },
          )
        : h(
            NTag,
            { size: 'small', type: 'success', bordered: false },
            { default: () => '成功' },
          ),
  },
  {
    title: '结论',
    key: 'conclusion',
    render: renderOutcome,
  },
  {
    title: '问题',
    key: 'user_query',
    width: 220,
    ellipsis: { tooltip: true },
  },
  {
    title: '耗时',
    key: 'duration_ms',
    width: 80,
    render: (r) => (r.duration_ms != null ? formatDurationMs(r.duration_ms) : '—'),
  },
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
        <p class="page-desc">调用历史与结论（共 {{ total }} 条），悬浮结论可查看全文</p>
      </div>
      <div class="head-actions">
        <div class="zoom" role="group" aria-label="结论字号缩放">
          <button
            type="button"
            class="zoom-btn"
            :disabled="zoom <= ZOOM_MIN"
            title="缩小结论字号"
            @click="applyZoom(zoom - ZOOM_STEP)"
          >
            A−
          </button>
          <span class="zoom-value n-num">{{ zoom }}px</span>
          <button
            type="button"
            class="zoom-btn"
            :disabled="zoom >= ZOOM_MAX"
            title="放大结论字号"
            @click="applyZoom(zoom + ZOOM_STEP)"
          >
            A+
          </button>
        </div>
        <n-button secondary size="small" :loading="loading" @click="load">刷新</n-button>
      </div>
    </header>
    <n-card size="small" :style="zoomVar">
      <n-data-table
        remote
        :loading="loading"
        :columns="columns"
        :data="items"
        :row-key="(r: LogItem) => r.request_id"
        :row-class-name="(r: LogItem) => (r.error ? 'row-fail' : '')"
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
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
.head-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.zoom {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px 6px;
  border: 1px solid rgba(148, 163, 200, 0.16);
  border-radius: 999px;
  background: rgba(18, 22, 33, 0.5);
}
.zoom-btn {
  appearance: none;
  font: inherit;
  font-size: 12px;
  color: #9aa3b8;
  background: transparent;
  border: none;
  border-radius: 6px;
  padding: 3px 10px;
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
}
.zoom-btn:hover:not(:disabled) {
  color: #dbe0ec;
  background: rgba(148, 163, 200, 0.12);
}
.zoom-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.zoom-value {
  min-width: 42px;
  text-align: center;
  font-size: 12px;
  color: #8a92a6;
}
/* 结论列：字号由 --conclusion-fs 控制（缩放），多行截断，悬浮 title 展示全文 */
.n-data-table :deep(.outcome) {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
  font-size: var(--conclusion-fs, 13px);
  line-height: 1.6;
  word-break: break-word;
}
.n-data-table :deep(.outcome.conclusion) {
  color: #dfe3ec;
}
.n-data-table :deep(.outcome.error) {
  color: #f0a4a4;
}
.n-data-table :deep(.outcome.dim) {
  color: #6b7280;
}
.n-data-table :deep(.row-fail) {
  background: rgba(248, 113, 113, 0.04);
}
</style>
