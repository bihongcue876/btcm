<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { NTag, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { api, ApiError } from '@/api/client'
import type { LogItem } from '@/types'

const message = useMessage()
const loading = ref(false)
const items = ref<LogItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const expandedRows = ref<Array<string | number>>([])

function shapeLabel(item: LogItem): string {
  if (item.enable_creative && item.enable_validator) return '完整循环'
  if (item.enable_creative) return '纯创意'
  if (item.enable_validator) return '纯验证'
  return '长链思考'
}

function verdictType(v: string | null) {
  if (v === 'pass') return 'success'
  if (v === 'conditional_pass') return 'warning'
  if (v === 'fail') return 'error'
  return 'default'
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { hour12: false })
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

const columns: DataTableColumns<LogItem> = [
  { title: '时间', key: 'timestamp', width: 170, render: (r) => formatTime(r.timestamp) },
  { title: '形态', key: 'shape', width: 90, render: (r) => shapeLabel(r) },
  {
    title: '判定',
    key: 'verdict',
    width: 130,
    render: (r) =>
      r.verdict
        ? h(
            NTag,
            { size: 'small', type: verdictType(r.verdict) },
            { default: () => r.verdict as string },
          )
        : '—',
  },
  { title: '轮数', key: 'iterations_used', width: 70, render: (r) => r.iterations_used ?? '—' },
  {
    title: '耗时',
    key: 'duration_ms',
    width: 90,
    render: (r) => (r.duration_ms != null ? `${r.duration_ms}ms` : '—'),
  },
  {
    title: '终止',
    key: 'termination_reason',
    width: 140,
    render: (r) => r.termination_reason ?? '—',
  },
  { title: '问题', key: 'user_query', ellipsis: { tooltip: true } },
]

onMounted(load)
</script>

<template>
  <div>
    <header class="page-head">
      <div>
        <h1 class="page-title">日志</h1>
        <p class="page-desc">历史调用记录，展开查看结论与错误</p>
      </div>
    </header>
    <n-card size="small">
      <n-data-table
        remote
        :loading="loading"
        :columns="columns"
        :data="items"
        :row-key="(r: LogItem) => r.request_id"
        :expanded-row-keys="expandedRows"
        :pagination="false"
        @update:expanded-row-keys="(keys: Array<string | number>) => (expandedRows = keys)"
      >
      <template #empty>暂无调用记录</template>
      <template #row-expand="props">
        <div class="detail">
          <div v-if="props.row.error" class="detail-error">
            <n-tag size="small" type="error" :bordered="false">{{ props.row.error }}</n-tag>
          </div>
          <div v-if="props.row.conclusion" class="detail-text">
            <div class="detail-label">结论</div>
            {{ props.row.conclusion }}
          </div>
          <div v-if="!props.row.conclusion && !props.row.error" class="detail-text dim">
            无结论
          </div>
        </div>
      </template>
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
.detail {
  padding: 4px 8px;
}
.detail-error {
  margin-bottom: 6px;
}
.detail-label {
  font-size: 12px;
  color: #888;
  margin-bottom: 2px;
}
.detail-text {
  font-size: 13px;
  line-height: 1.6;
}
.dim {
  color: #999;
}
</style>
