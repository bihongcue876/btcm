<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { api, ApiError } from '@/api/client'
import type { GlobalConfig } from '@/types'

const message = useMessage()
const loading = ref(false)
const saving = ref(false)
const cfg = reactive<GlobalConfig>({
  max_iterations: 2,
  timeout: 300,
  enable_creative: true,
  enable_validator: true,
  providers: {},
  agents: {},
})

// api_key 不回显：单独保存输入值，仅提交时并入
const apiKeys = reactive<Record<string, string>>({})
// models / web_sources 用本地文本缓冲，避免受控输入光标跳变
const modelsText = reactive<Record<string, string>>({})
const webSourcesText = reactive<Record<string, string>>({})
const providerNames = ref<string[]>([])
const agentNames = ref<string[]>([])

// models 逗号串 <-> 数组
function modelsToText(list: string[] | undefined): string {
  return (list ?? []).join(', ')
}
function textToModels(text: string): string[] {
  return text
    .split(/[,，]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

async function load() {
  loading.value = true
  try {
    const data = await api.getConfig()
    Object.assign(cfg, data)
    providerNames.value = Object.keys(cfg.providers)
    agentNames.value = Object.keys(cfg.agents)
    // 同步本地文本缓冲
    Object.keys(modelsText).forEach((k) => delete modelsText[k])
    Object.keys(webSourcesText).forEach((k) => delete webSourcesText[k])
    Object.keys(apiKeys).forEach((k) => delete apiKeys[k])
    for (const name of providerNames.value) {
      modelsText[name] = modelsToText(cfg.providers[name].models)
    }
    for (const name of agentNames.value) {
      if (name === 'validator') {
        webSourcesText[name] = modelsToText(cfg.agents[name].web_sources)
      }
    }
  } catch (e) {
    message.error(e instanceof ApiError ? e.message : String(e))
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const payload = JSON.parse(JSON.stringify(cfg)) as GlobalConfig
    // 本地文本缓冲 → 数组；provider timeout null 兜底（后端非 Optional）
    for (const name of providerNames.value) {
      payload.providers[name].models = textToModels(modelsText[name] ?? '')
      if (payload.providers[name].timeout == null) payload.providers[name].timeout = 120
      const key = apiKeys[name]
      if (key && key.trim()) {
        payload.providers[name].api_key = key.trim()
      }
    }
    for (const name of agentNames.value) {
      if (name === 'validator') {
        payload.agents[name].web_sources = textToModels(webSourcesText[name] ?? '')
      }
    }
    await api.updateConfig(payload)
    message.success('配置已保存')
    await load()
  } catch (e) {
    message.error(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e))
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <n-spin :show="loading">
    <header class="page-head">
      <div>
        <h1 class="page-title">配置</h1>
        <p class="page-desc">运行参数、Agent 启用开关与模型路由</p>
      </div>
    </header>
    <div class="toolbar">
      <n-button @click="load">刷新</n-button>
      <n-button type="primary" :loading="saving" @click="save">保存配置</n-button>
    </div>

    <!-- 运行参数 -->
    <n-card title="运行参数" size="small" class="card">
      <n-grid :cols="4" :x-gap="16" responsive="screen">
        <n-form-item label="max_iterations" label-placement="top">
          <n-input-number
            :value="cfg.max_iterations"
            :min="1"
            :max="10"
            style="width: 100%"
            @update:value="(v: number | null) => { if (v != null) cfg.max_iterations = v }"
          />
        </n-form-item>
        <n-form-item label="timeout（秒）" label-placement="top">
          <n-input-number
            :value="cfg.timeout"
            :min="1"
            :max="3600"
            style="width: 100%"
            @update:value="(v: number | null) => { if (v != null) cfg.timeout = v }"
          />
        </n-form-item>
        <n-form-item label="创意 Agent（全局默认）" label-placement="top">
          <n-switch v-model:value="cfg.enable_creative" />
        </n-form-item>
        <n-form-item label="验证 Agent（全局默认）" label-placement="top">
          <n-switch v-model:value="cfg.enable_validator" />
        </n-form-item>
      </n-grid>
    </n-card>

    <!-- 提供商 -->
    <div class="section-title">提供商</div>
    <n-card v-for="name in providerNames" :key="`p-${name}`" :title="name" size="small" class="card">
      <n-grid :cols="2" :x-gap="16" responsive="screen">
        <n-form-item label="base_url" label-placement="top">
          <n-input v-model:value="cfg.providers[name].base_url" />
        </n-form-item>
        <n-form-item label="api_key（不回显，留空不修改）" label-placement="top">
          <n-input
            v-model:value="apiKeys[name]"
            type="password"
            show-password-on="mousedown"
            placeholder="输入以设置/更新"
          />
        </n-form-item>
        <n-form-item label="单请求超时（秒）" label-placement="top">
          <n-input-number
            :value="cfg.providers[name].timeout"
            :min="1"
            :max="3600"
            style="width: 100%"
            @update:value="(v: number | null) => (cfg.providers[name].timeout = v ?? 120)"
          />
        </n-form-item>
        <n-form-item label="models（逗号分隔）" label-placement="top">
          <n-input v-model:value="modelsText[name]" placeholder="model-a, model-b" />
        </n-form-item>
      </n-grid>
    </n-card>

    <!-- Agent 路由 -->
    <div class="section-title">Agent 路由与参数</div>
    <n-card v-for="name in agentNames" :key="`a-${name}`" :title="name" size="small" class="card">
      <n-grid :cols="3" :x-gap="16" responsive="screen">
        <n-form-item label="provider" label-placement="top">
          <n-select
            v-model:value="cfg.agents[name].provider"
            :options="providerNames.map((p) => ({ label: p, value: p }))"
          />
        </n-form-item>
        <n-form-item label="model" label-placement="top">
          <n-input v-model:value="cfg.agents[name].model" />
        </n-form-item>
        <n-form-item label="temperature" label-placement="top">
          <n-input-number
            :value="cfg.agents[name].temperature"
            :min="0"
            :max="2"
            :step="0.1"
            style="width: 100%"
            @update:value="(v: number | null) => { if (v != null) (cfg.agents[name].temperature = v) }"
          />
        </n-form-item>
        <n-form-item label="max_tokens" label-placement="top">
          <n-input-number
            :value="cfg.agents[name].max_tokens"
            :min="256"
            :max="32768"
            style="width: 100%"
            @update:value="(v: number | null) => { if (v != null) (cfg.agents[name].max_tokens = v) }"
          />
        </n-form-item>
        <n-form-item label="单请求超时（秒，可空）" label-placement="top">
          <n-input-number
            :value="cfg.agents[name].timeout ?? null"
            :min="1"
            :max="3600"
            style="width: 100%"
            clearable
            @update:value="(v: number | null) => (cfg.agents[name].timeout = v ?? null)"
          />
        </n-form-item>

        <n-form-item v-if="name === 'creative'" label="num_candidates" label-placement="top">
          <n-input-number
            :value="cfg.agents[name].num_candidates"
            :min="1"
            :max="10"
            style="width: 100%"
            @update:value="(v: number | null) => { if (v != null) (cfg.agents[name].num_candidates = v) }"
          />
        </n-form-item>

        <template v-if="name === 'validator'">
          <n-form-item label="允许联网搜索" label-placement="top">
            <n-switch v-model:value="cfg.agents[name].enable_web_search" />
          </n-form-item>
          <n-form-item label="web_sources（逗号分隔）" label-placement="top">
            <n-input v-model:value="webSourcesText[name]" />
          </n-form-item>
        </template>

        <n-form-item v-if="name === 'controller'" label="log_intermediate" label-placement="top">
          <n-switch v-model:value="cfg.agents[name].log_intermediate" />
        </n-form-item>
      </n-grid>
    </n-card>
  </n-spin>
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
.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.card {
  margin-bottom: 16px;
}
.section-title {
  margin: 4px 2px 10px;
  font-size: 13px;
  font-weight: 500;
  color: #8b93a7;
}
</style>
