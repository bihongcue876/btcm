<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import { api, ApiError, setAdminToken } from '@/api/client'
import type { GlobalConfig, MCPServerConfig } from '@/types'

const message = useMessage()
const dialog = useDialog()
const loading = ref(false)
const submitting = ref(false)

const cfg = reactive<GlobalConfig>({
  max_iterations: 2,
  timeout: 3600,
  enable_creative: true,
  enable_validator: true,
  lock_invoke: false,
  default_provider: null,
  default_model: null,
  structured_output: 'text',
  providers: {},
  mcp_servers: {},
  agents: {},
})

const apiKeys = reactive<Record<string, string>>({})
const clearedApiKeys = reactive<Record<string, boolean>>({})
const providerNames = ref<string[]>([])
const agentNames = ref<string[]>([])

const mcpServerNames = ref<string[]>([])
const mcpApiKeys = reactive<Record<string, string>>({})
const clearedMcpApiKeys = reactive<Record<string, boolean>>({})

const adminTokenInput = ref('')
const clearedAdminToken = ref(false)

// 服务端已注册的提供商名：拉取模型走服务端，条目未保存时服务端不认识它
const serverProviders = ref<Set<string>>(new Set())
// 本地已删除、保存时以 null 通知服务端移除（RFC 7386 删除语义）
const deletedProviders = ref<string[]>([])
const deletedMcpServers = ref<string[]>([])

const addingProvider = ref(false)
const newProviderName = ref('')
const newProviderBaseUrl = ref('')
const newProviderPreset = ref<string | null>(null)
const newProviderApiKey = ref('')

const addingMcp = ref(false)
const newMcpName = ref('')
const newMcpPreset = ref<string | null>(null)
const newMcpUrl = ref('')

// 跟随全局默认：true 时 provider/model 置空，由后端解析链回退
const followGlobal = reactive<Record<string, boolean>>({})
// 自定义模型输入：true 时用 n-input 替代 n-select
const useCustomModel = reactive<Record<string, boolean>>({})
// 每个 provider 的 options 编辑为 JSON 文本
const providerOptionsText = reactive<Record<string, string>>({})

const MCP_PRESET_OPTIONS = [
  { value: 'tavily', label: 'tavily · Tavily 网络搜索（需 api_key）' },
  { value: 'exa', label: 'exa · Exa 搜索（需 api_key）' },
  { value: 'deepwiki', label: 'deepwiki · 开源仓库文档（免密）' },
  { value: 'fetch', label: 'fetch · 网页抓取（免密）' },
  { value: 'duckduckgo', label: 'duckduckgo · DuckDuckGo 搜索（本地服务，免密）' },
]

// 指向本地回环地址的预设：创建条目时默认放行（否则后端私网校验会拒绝）
const MCP_PRESETS_LOCAL = ['duckduckgo']

// 内置 MCP 预设中需要 api_key 的（与服务端 MCP_PRESETS 的 needs_key 对应）
const MCP_PRESETS_NEED_KEY = ['tavily', 'exa']

// 常用 OpenAI 兼容服务预设：选名称即自动填充，也可全部手填
const PROVIDER_PRESET_OPTIONS = [
  { value: 'deepseek', label: 'DeepSeek（深度求索）', base_url: 'https://api.deepseek.com/v1' },
  { value: 'ollama-local', label: 'Ollama（本地，默认端口）', base_url: 'http://localhost:11434/v1' },
  { value: 'zhipu', label: '智谱 GLM', base_url: 'https://open.bigmodel.cn/api/paas/v4' },
  { value: 'moonshot', label: 'Moonshot Kimi', base_url: 'https://api.moonshot.cn/v1' },
  { value: 'openrouter', label: 'OpenRouter（多厂商聚合）', base_url: 'https://openrouter.ai/api/v1' },
  { value: 'siliconflow', label: '硅基流动 SiliconFlow', base_url: 'https://api.siliconflow.cn/v1' },
  { value: 'lmstudio', label: 'LM Studio（本地，默认端口）', base_url: 'http://localhost:1234/v1' },
  { value: 'custom', label: '自定义（手填名称与地址）', base_url: '' },
]

function onNewProviderPresetChange(v: string | null) {
  newProviderPreset.value = v
  const preset = PROVIDER_PRESET_OPTIONS.find((p) => p.value === v)
  if (preset) {
    if (v !== 'custom') {
      newProviderName.value = v as string
      newProviderBaseUrl.value = preset.base_url
    } else {
      newProviderBaseUrl.value = ''
    }
  }
}

const STRUCTURED_OUTPUT_OPTIONS = [
  { value: 'text', label: 'text · 正文内嵌 JSON（当前默认）' },
  { value: 'json_object', label: 'json_object · 请求 response_format（需模型支持）' },
]

const ALL_ENABLED_PROVIDERS = computed(() =>
  providerNames.value.filter((n) => cfg.providers[n].enabled !== false),
)

const providerCount = computed(() => providerNames.value.length)
const mcpCount = computed(() => mcpServerNames.value.length)
const agentCount = computed(() => agentNames.value.length)

function providerModelCount(name: string): number {
  return cfg.providers[name]?.models?.length ?? 0
}

function providerModels(provider: string): string[] {
  return cfg.providers[provider]?.models ?? []
}

/** 环境变量名片段：非字母数字转 _，大写（与服务端 _env_secret 规则一致） */
function envVarName(name: string): string {
  return name
    .toUpperCase()
    .split('')
    .map((c) => (c.match(/[A-Z0-9]/) ? c : '_'))
    .join('')
}

function providerModelOptions(name: string) {
  return (cfg.providers[name]?.models ?? []).map((m) => ({ label: m, value: m }))
}

/** 模型下拉选项：提供商的 models 列表 + 当前自定义值（若不在列表中） */
function modelSelectOptions(name: string): { label: string; value: string }[] {
  const provider = cfg.agents[name]?.provider
  if (!provider) return []
  const opts = providerModelOptions(provider)
  const current = cfg.agents[name]?.model
  if (current && !opts.some((o) => o.value === current)) {
    opts.push({ label: `${current}（自定义）`, value: current })
  }
  return opts
}

/** 前端预览：agent 实际使用的 provider 名（走解析链） */
function resolvedProvider(agentName: string): string {
  const a = cfg.agents[agentName]
  if (a?.provider) return a.provider
  if (cfg.default_provider) return cfg.default_provider
  return ALL_ENABLED_PROVIDERS.value[0] ?? '—'
}

/** 前端预览：agent 实际使用的 model */
function resolvedModel(agentName: string): string {
  const a = cfg.agents[agentName]
  if (a?.model) return a.model
  const p = resolvedProvider(agentName)
  const models = providerModels(p)
  if (cfg.default_model && models.includes(cfg.default_model)) return cfg.default_model
  if (models.length) return models[0]
  return '（全局兜底）'
}

function effectiveRoute(agentName: string): string {
  return `${resolvedProvider(agentName)} / ${resolvedModel(agentName)}`
}

function toggleFollowGlobal(name: string) {
  if (followGlobal[name]) {
    followGlobal[name] = false
    if (!cfg.agents[name].provider) cfg.agents[name].provider = resolvedProvider(name)
    if (!cfg.agents[name].model) cfg.agents[name].model = resolvedModel(name)
  } else {
    followGlobal[name] = true
    cfg.agents[name].provider = null
    cfg.agents[name].model = null
  }
}

function initFollowGlobal() {
  for (const name of agentNames.value) {
    followGlobal[name] = !cfg.agents[name].provider
  }
}

function initProviderOptions() {
  for (const name of providerNames.value) {
    const opts = cfg.providers[name].options
    if (opts && Object.keys(opts).length) {
      providerOptionsText[name] = JSON.stringify(opts, null, 2)
    } else {
      providerOptionsText[name] = ''
    }
  }
}

async function load() {
  loading.value = true
  try {
    const data = await api.getConfig()
    Object.assign(cfg, data)
    if (!cfg.mcp_servers) cfg.mcp_servers = {}
    if (!cfg.structured_output) cfg.structured_output = 'text'
    if (!cfg.default_provider) cfg.default_provider = null
    if (!cfg.default_model) cfg.default_model = null
    providerNames.value = Object.keys(cfg.providers)
    agentNames.value = Object.keys(cfg.agents)
    mcpServerNames.value = Object.keys(cfg.mcp_servers)
    serverProviders.value = new Set(providerNames.value)
    deletedProviders.value = []
    deletedMcpServers.value = []
    Object.keys(apiKeys).forEach((k) => delete apiKeys[k])
    Object.keys(clearedApiKeys).forEach((k) => delete clearedApiKeys[k])
    Object.keys(mcpApiKeys).forEach((k) => delete mcpApiKeys[k])
    Object.keys(clearedMcpApiKeys).forEach((k) => delete clearedMcpApiKeys[k])
    Object.keys(followGlobal).forEach((k) => delete followGlobal[k])
    Object.keys(providerOptionsText).forEach((k) => delete providerOptionsText[k])
    adminTokenInput.value = ''
    clearedAdminToken.value = false
    // 清除所有"标记清除"状态：api_key_set 为服务端权威状态
    Object.keys(clearedApiKeys).forEach((k) => delete clearedApiKeys[k])
    Object.keys(clearedMcpApiKeys).forEach((k) => delete clearedMcpApiKeys[k])
    initFollowGlobal()
    initProviderOptions()
  } catch (e) {
    message.error(e instanceof ApiError ? e.message : String(e))
  } finally {
    loading.value = false
  }
}

function addProvider() {
  const name = newProviderName.value.trim()
  if (!name) {
    message.warning('请输入提供商名称')
    return
  }
  if (cfg.providers[name]) {
    message.warning(`提供商 ${name} 已存在`)
    return
  }
  const baseUrl = newProviderBaseUrl.value.trim()
  if (!baseUrl) {
    message.warning('请输入 base_url（可先用上方预设自动填充）')
    return
  }
  if (!/^https?:\/\//i.test(baseUrl)) {
    message.warning('base_url 仅支持 http:// 或 https:// 开头')
    return
  }
  cfg.providers[name] = {
    base_url: baseUrl,
    models: [],
    timeout: 600,
    enabled: true,
    options: {},
  }
  providerOptionsText[name] = ''
  // 模态里一步填入的密钥：直接进待写入状态，保存时随配置提交
  if (newProviderApiKey.value.trim()) {
    apiKeys[name] = newProviderApiKey.value.trim()
  }
  // 删除后又重新添加同名条目：撤销待删除标记，否则保存时会把它一并删掉
  deletedProviders.value = deletedProviders.value.filter((n) => n !== name)
  providerNames.value = Object.keys(cfg.providers)
  addingProvider.value = false
  newProviderName.value = ''
  newProviderBaseUrl.value = ''
  newProviderPreset.value = null
  newProviderApiKey.value = ''
  message.success(`已添加提供商 ${name}，点击「保存配置」写入服务端`)
}

// ---------- 模型发现：从服务端拉取可用模型列表 ----------

const fetchingModels = reactive<Record<string, boolean>>({})

/** 拉取模型走服务端代理，要求该提供商已存在于服务端配置 */
function fetchModels(name: string) {
  if (fetchingModels[name]) return
  if (!serverProviders.value.has(name)) {
    dialog.warning({
      title: `提供商「${name}」尚未保存到服务端`,
      content:
        '拉取模型由服务端代理发起，未保存的条目服务端不认识（直接拉取会返回「提供商不存在」）。'
        + '继续将先保存当前配置的全部未保存修改，再拉取模型。',
      positiveText: '保存并拉取',
      negativeText: '取消',
      async onPositiveClick() {
        const saved = await save()
        if (saved) await doFetchModels(name)
      },
    })
    return
  }
  void doFetchModels(name)
}

async function doFetchModels(name: string) {
  if (fetchingModels[name]) return
  fetchingModels[name] = true
  try {
    const models = await api.fetchProviderModels(name)
    if (models.length) {
      cfg.providers[name].models = models
      message.success(`已拉取 ${name} 的 ${models.length} 个模型，点击「保存配置」写入`)
    } else {
      message.warning(`${name} 返回空模型列表（该服务可能不支持 /models）`)
    }
  } catch (e) {
    const msg = e instanceof ApiError ? `${e.code}: ${e.message}` : String(e)
    message.error(
      e instanceof ApiError && e.code === 'NOT_FOUND'
        ? `${msg}（该提供商需先保存到服务端）`
        : msg,
    )
  } finally {
    fetchingModels[name] = false
  }
}

function removeProvider(name: string) {
  const usedBy = agentNames.value.filter((a) => cfg.agents[a].provider === name)
  const doRemove = () => {
    delete cfg.providers[name]
    delete apiKeys[name]
    delete clearedApiKeys[name]
    delete providerOptionsText[name]
    // 服务端已有该条目时，保存需显式发 null 才会真正移除
    if (serverProviders.value.has(name)) {
      deletedProviders.value.push(name)
    }
    providerNames.value = Object.keys(cfg.providers)
    message.success(`已删除提供商 ${name}，点击「保存配置」生效`)
  }
  if (usedBy.length > 0) {
    dialog.warning({
      title: `删除提供商「${name}」？`,
      content: `以下 Agent 正在引用它：${usedBy.join('、')}。删除后这些 Agent 将无法访问模型，请在删除后将其 provider 改为其他提供商。`,
      positiveText: '仍然删除',
      negativeText: '取消',
      onPositiveClick: doRemove,
    })
  } else {
    doRemove()
  }
}

function addMcpServer() {
  const name = newMcpName.value.trim()
  if (!name) {
    message.warning('请输入 MCP 服务器名称')
    return
  }
  if (cfg.mcp_servers[name]) {
    message.warning(`MCP 服务器 ${name} 已存在`)
    return
  }
  const entry: MCPServerConfig = newMcpPreset.value
    ? {
        preset: newMcpPreset.value,
        enabled: true,
        timeout: 60,
        allowed_tools: [],
        ...(MCP_PRESETS_LOCAL.includes(newMcpPreset.value) ? { allow_private: true } : {}),
      }
    : {
        url: newMcpUrl.value.trim() || 'https://example.com/mcp',
        enabled: true,
        timeout: 60,
        allowed_tools: [],
      }
  cfg.mcp_servers[name] = entry
  mcpServerNames.value = Object.keys(cfg.mcp_servers)
  addingMcp.value = false
  newMcpName.value = ''
  newMcpPreset.value = null
  newMcpUrl.value = ''
  message.success(`已添加 MCP 服务器 ${name}，记得保存`)
}

function removeMcpServer(name: string) {
  const usedBy = agentNames.value.filter((a) =>
    (cfg.agents[a].mcp_servers ?? []).includes(name),
  )
  const doRemove = () => {
    delete cfg.mcp_servers[name]
    delete mcpApiKeys[name]
    delete clearedMcpApiKeys[name]
    for (const a of agentNames.value) {
      const refs = cfg.agents[a].mcp_servers
      if (refs?.includes(name)) {
        cfg.agents[a].mcp_servers = refs.filter((s) => s !== name)
      }
    }
    mcpServerNames.value = Object.keys(cfg.mcp_servers)
    // 服务端对该键发 null 是无害空操作，故不必区分是否已保存
    deletedMcpServers.value.push(name)
    message.success(`已删除 MCP 服务器 ${name}，点击「保存配置」生效`)
  }
  if (usedBy.length > 0) {
    dialog.warning({
      title: `删除 MCP 服务器「${name}」？`,
      content: `以下 Agent 正在引用它：${usedBy.join('、')}。删除后将同步移除这些引用，相关 Agent 退回纯逻辑验证。`,
      positiveText: '仍然删除',
      negativeText: '取消',
      onPositiveClick: doRemove,
    })
  } else {
    doRemove()
  }
}

function clearMcpApiKey(name: string) {
  mcpApiKeys[name] = ''
  clearedMcpApiKeys[name] = true
  message.success(`已标记清除 ${name} 的 api_key，保存后生效`)
}

function clearApiKey(name: string) {
  apiKeys[name] = ''
  clearedApiKeys[name] = true
  message.success(`已标记清除 ${name} 的 api_key，保存后生效`)
}

function confirmReset() {
  dialog.warning({
    title: '重置为默认配置？',
    content:
      '所有运行参数、提供商注册表与 Agent 路由将恢复为内置默认值，当前页面的未保存修改不会保留。',
    positiveText: '重置',
    negativeText: '取消',
    async onPositiveClick() {
      submitting.value = true
      try {
        await api.resetConfig()
        message.success('已重置为默认配置')
        await load()
      } catch (e) {
        message.error(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e))
      } finally {
        submitting.value = false
      }
    },
  })
}

async function save() {
  submitting.value = true
  try {
    const payload = JSON.parse(JSON.stringify(cfg)) as GlobalConfig
    for (const name of providerNames.value) {
      if (payload.providers[name].timeout == null) {
        payload.providers[name].timeout = 600
      }
      if (payload.providers[name].enabled == null) {
        payload.providers[name].enabled = true
      }
      const key = apiKeys[name]
      if (key && key.trim()) {
        payload.providers[name].api_key = key.trim()
      } else if (clearedApiKeys[name]) {
        payload.providers[name].api_key = null
      }
      // 解析 options JSON
      const raw = providerOptionsText[name]?.trim()
      if (raw) {
        try {
          payload.providers[name].options = JSON.parse(raw)
        } catch {
          message.warning(`提供商 ${name} 的 options 不是合法 JSON，已忽略`)
          payload.providers[name].options = {}
        }
      } else {
        payload.providers[name].options = {}
      }
    }
    for (const name of mcpServerNames.value) {
      const entry = payload.mcp_servers[name]
      if (entry.preset && !entry.url) {
        delete entry.url
      }
      const key = mcpApiKeys[name]
      if (key && key.trim()) {
        entry.api_key = key.trim()
      } else if (clearedMcpApiKeys[name]) {
        entry.api_key = null
      }
    }
    if (adminTokenInput.value.trim()) {
      payload.admin_token = adminTokenInput.value.trim()
      setAdminToken(payload.admin_token)
    } else if (clearedAdminToken.value) {
      payload.admin_token = null
      setAdminToken('')
    }
    // 跟随全局：provider/model 置空
    for (const name of agentNames.value) {
      if (followGlobal[name]) {
        payload.agents[name].provider = null
        payload.agents[name].model = null
      }
    }
    // 已删除的注册表条目：显式发 null，服务端按 RFC 7386 语义移除
    for (const name of deletedProviders.value) {
      ;(payload.providers as Record<string, unknown>)[name] = null
    }
    for (const name of deletedMcpServers.value) {
      ;(payload.mcp_servers as Record<string, unknown>)[name] = null
    }
    await api.updateConfig(payload)
    message.success('配置已保存')
    await load()
    return true
  } catch (e) {
    message.error(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e))
    return false
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<template>
  <n-spin :show="loading">
    <header class="page-head">
      <div class="page-head-left">
        <h1 class="page-title">配置</h1>
        <p class="page-desc">运行参数、提供商注册表、Agent 路由与全局默认</p>
      </div>
      <div class="page-stats">
        <span class="stat">
          <span class="stat-dot" style="background: #8794ff"></span>
          <b>{{ providerCount }}</b> 提供商
        </span>
        <span class="stat">
          <span class="stat-dot" style="background: #38bdf8"></span>
          <b>{{ mcpCount }}</b> MCP
        </span>
        <span class="stat">
          <span class="stat-dot" style="background: #34d399"></span>
          <b>{{ agentCount }}</b> Agent
        </span>
      </div>
    </header>

    <div class="toolbar">
      <div class="toolbar-hint">
        <span class="toolbar-dot"></span>
        修改后点击「保存配置」写入服务端并即生效
      </div>
      <div class="toolbar-actions">
        <n-button @click="load">刷新</n-button>
        <n-button type="primary" :loading="submitting" @click="save">保存配置</n-button>
        <n-button type="error" tertiary @click="confirmReset">重置为默认</n-button>
      </div>
    </div>

    <!-- 全局默认 -->
    <section class="section">
      <div class="section-head">
        <div class="section-heading">
          <span class="bar bar-blue"></span>
          <div>
            <div class="section-title">全局默认</div>
            <div class="section-desc">Agent 角色未显式指定时回退到此</div>
          </div>
        </div>
      </div>
      <n-card size="small" class="card">
        <n-grid :cols="3" :x-gap="16" responsive="screen">
          <n-form-item-gi label="默认提供商" label-placement="top" style="margin-bottom: 12px">
            <n-select
              :value="cfg.default_provider"
              :options="ALL_ENABLED_PROVIDERS.map((p) => ({ label: p, value: p }))"
              clearable
              placeholder="未设置时取首个已启用提供商"
              @update:value="(v: string | null) => {
                cfg.default_provider = v || null
                if (cfg.default_model && v && !providerModels(v).includes(cfg.default_model)) {
                  cfg.default_model = null
                }
              }"
            />
          </n-form-item-gi>
          <n-form-item-gi label="默认模型" label-placement="top" style="margin-bottom: 12px">
            <n-select
              v-if="!useCustomModel['__default']"
              :value="cfg.default_model"
              :options="cfg.default_provider ? providerModelOptions(cfg.default_provider) : []"
              filterable
              clearable
              :placeholder="cfg.default_provider ? '选择模型' : '请先选择默认提供商'"
              @update:value="(v: string | null) => cfg.default_model = v"
            />
            <n-input
              v-else
              :value="cfg.default_model ?? ''"
              placeholder="输入自定义模型名"
              class="mono-input"
              @update:value="(v: string) => cfg.default_model = v || null"
            />
            <n-button
              v-if="cfg.default_provider"
              text size="tiny" type="primary"
              style="margin-top: 4px"
              @click="useCustomModel['__default'] = !useCustomModel['__default']"
            >
              {{ useCustomModel['__default'] ? '从列表选择' : '输入自定义模型名' }}
            </n-button>
          </n-form-item-gi>
          <n-form-item-gi label="结构化输出模式" label-placement="top" style="margin-bottom: 12px">
            <n-select
              :value="cfg.structured_output ?? 'text'"
              :options="STRUCTURED_OUTPUT_OPTIONS"
              @update:value="(v: string) => cfg.structured_output = v"
            />
          </n-form-item-gi>
        </n-grid>
      </n-card>
    </section>

    <!-- 运行参数 -->
    <section class="section">
      <div class="section-head">
        <div class="section-heading">
          <span class="bar bar-violet"></span>
          <div>
            <div class="section-title">运行参数</div>
            <div class="section-desc">全局默认开关与超时</div>
          </div>
        </div>
      </div>
      <n-card size="small" class="card">
        <n-grid :cols="4" :x-gap="16" responsive="screen">
          <n-form-item-gi label="max_iterations" label-placement="top" style="margin-bottom: 12px">
            <n-input-number
              :value="cfg.max_iterations"
              :min="1"
              style="width: 100%"
              @update:value="(v: number | null) => { if (v != null) cfg.max_iterations = v }"
            />
          </n-form-item-gi>
          <n-form-item-gi label="timeout（秒）" label-placement="top" style="margin-bottom: 12px">
            <n-input-number
              :value="cfg.timeout"
              :min="1"
              style="width: 100%"
              @update:value="(v: number | null) => { if (v != null) cfg.timeout = v }"
            />
          </n-form-item-gi>
          <n-form-item-gi label="创意 Agent（全局默认）" label-placement="top" style="margin-bottom: 12px">
            <n-switch v-model:value="cfg.enable_creative" />
          </n-form-item-gi>
          <n-form-item-gi label="验证 Agent（全局默认）" label-placement="top" style="margin-bottom: 12px">
            <n-switch v-model:value="cfg.enable_validator" />
          </n-form-item-gi>
          <n-form-item-gi label="锁定 invoke（需令牌）" label-placement="top" style="margin-bottom: 12px">
            <n-switch v-model:value="cfg.lock_invoke" />
          </n-form-item-gi>
          <n-form-item-gi label="管理令牌 admin_token（不回显）" label-placement="top" style="margin-bottom: 12px">
            <n-input
              v-model:value="adminTokenInput"
              type="password"
              show-password-on="mousedown"
              :placeholder="cfg.admin_token_set ? '已设置（输入以更新）' : '设置后写配置/重置/日志接口需 X-Admin-Token'"
            >
              <template #suffix>
                <n-button
                  v-if="!clearedAdminToken && cfg.admin_token_set"
                  size="tiny"
                  quaternary
                  type="error"
                  @click="() => { clearedAdminToken = true; adminTokenInput = '' }"
                >
                  清除
                </n-button>
                <span v-else-if="clearedAdminToken" class="cleared-tag">已标记清除</span>
              </template>
            </n-input>
            <div class="field-hint mono">
              环境变量注入：BTCM_ADMIN_TOKEN（优先于此处，不回写）
            </div>
          </n-form-item-gi>
        </n-grid>
      </n-card>
    </section>

    <!-- 提供商注册表 -->
    <section class="section">
      <div class="section-head">
        <div class="section-heading">
          <span class="bar bar-violet"></span>
          <div>
            <div class="section-title">提供商注册表</div>
            <div class="section-desc">管理 OpenAI 兼容服务的地址、密钥、模型与厂商参数</div>
          </div>
          <n-tag v-if="providerCount" size="small" round :bordered="false" class="count-tag">
            {{ providerCount }}
          </n-tag>
        </div>
        <n-button size="small" secondary type="primary" @click="addingProvider = true">
          + 新增提供商
        </n-button>
      </div>

      <template v-if="providerCount">
        <n-card v-for="name in providerNames" :key="`p-${name}`" size="small" class="card">
          <template #header>
            <div class="card-head">
              <div class="card-head-left">
                <span
                  class="dot"
                  :style="{
                    background: cfg.providers[name].enabled === false ? '#5d6474' : '#7c6cf0',
                    boxShadow: cfg.providers[name].enabled === false
                      ? 'none'
                      : '0 0 8px rgba(139,124,255,0.7)'
                  }"
                ></span>
                <span
                  class="card-title"
                  :style="{ color: cfg.providers[name].enabled === false ? '#5d6474' : undefined }"
                >{{ name }}</span>
                <span class="mono chip">{{ cfg.providers[name].base_url }}</span>
                <n-tag
                  v-if="!serverProviders.has(name)"
                  size="tiny"
                  round
                  :bordered="false"
                  type="info"
                  class="subtle-tag"
                  title="该条目尚未写入服务端配置，保存后才生效"
                >
                  未保存
                </n-tag>
                <n-tag size="tiny" round :bordered="false" class="subtle-tag">
                  {{ providerModelCount(name) }} 模型
                </n-tag>
                <n-tag
                  size="tiny"
                  round
                  :bordered="false"
                  :type="cfg.providers[name].api_key_set ? 'success' : 'warning'"
                  class="subtle-tag"
                >
                  {{ cfg.providers[name].api_key_set ? '密钥已设' : '未设密钥' }}
                </n-tag>
                <n-tag
                  size="tiny"
                  round
                  :bordered="false"
                  :type="cfg.providers[name].enabled === false ? 'default' : 'success'"
                >
                  {{ cfg.providers[name].enabled === false ? '停用' : '启用' }}
                </n-tag>
              </div>
              <div class="card-head-actions">
                <n-tooltip trigger="hover">
                  <template #trigger>
                    <n-button
                      size="tiny"
                      secondary
                      :loading="fetchingModels[name]"
                      @click="fetchModels(name)"
                    >
                      拉取模型
                    </n-button>
                  </template>
                  从服务端 GET /models 拉取可用模型列表，替换下方 models
                </n-tooltip>
                <n-button size="tiny" quaternary type="error" @click="removeProvider(name)">
                  删除
                </n-button>
              </div>
            </div>
          </template>
          <n-grid :cols="2" :x-gap="16" responsive="screen">
            <n-form-item-gi label="base_url" label-placement="top" style="margin-bottom: 12px">
              <n-input v-model:value="cfg.providers[name].base_url" class="mono-input" />
            </n-form-item-gi>
            <n-form-item-gi label="启用" label-placement="top" style="margin-bottom: 12px">
              <n-switch
                :value="cfg.providers[name].enabled ?? true"
                @update:value="(v: boolean) => cfg.providers[name].enabled = v"
              />
            </n-form-item-gi>
            <n-form-item-gi
              label="api_key（不回显，留空不修改）"
              label-placement="top"
              style="margin-bottom: 12px"
            >
              <n-input
                v-model:value="apiKeys[name]"
                type="password"
                show-password-on="mousedown"
                :placeholder="cfg.providers[name].api_key_set ? '已设置（输入以更新）' : '输入以设置'"
                style="width: 100%"
              >
                <template #suffix>
                  <n-button
                    v-if="!clearedApiKeys[name] && cfg.providers[name].api_key_set"
                    size="tiny"
                    quaternary
                    type="error"
                    @click="clearApiKey(name)"
                  >
                    清除
                  </n-button>
                  <span v-else-if="clearedApiKeys[name]" class="cleared-tag">已标记清除</span>
                </template>
              </n-input>
              <div class="field-hint mono">
                环境变量注入：BTCM_PROVIDER_{{ envVarName(name) }}_API_KEY（优先于此处，不回写）
              </div>
            </n-form-item-gi>
            <n-form-item-gi label="单请求超时（秒）" label-placement="top" style="margin-bottom: 12px">
              <n-input-number
                :value="cfg.providers[name].timeout"
                :min="1"
                style="width: 100%"
                @update:value="(v: number | null) => (cfg.providers[name].timeout = v ?? 600)"
              />
            </n-form-item-gi>
            <n-form-item-gi label="models（回车添加标签）" label-placement="top" style="margin-bottom: 12px">
              <n-dynamic-tags
                v-model:value="cfg.providers[name].models"
                style="width: 100%"
              />
            </n-form-item-gi>
            <n-form-item-gi label="厂商参数 options（JSON 对象，透传进请求）" label-placement="top" style="margin-bottom: 12px" :span="2">
              <n-input
                v-model:value="providerOptionsText[name]"
                type="textarea"
                :rows="2"
                placeholder='{ "top_p": 0.9, "reasoning_effort": "high" }'
                class="mono-input"
              />
            </n-form-item-gi>
          </n-grid>
        </n-card>
      </template>
      <div v-else class="empty-well">
        <n-empty description="暂无提供商，点击右上角「新增提供商」添加第一个服务" />
      </div>
    </section>

    <!-- MCP 服务器注册表 -->
    <section class="section">
      <div class="section-head">
        <div class="section-heading">
          <span class="bar bar-cyan"></span>
          <div>
            <div class="section-title">MCP 服务器注册表</div>
            <div class="section-desc">验证 Agent 联网工具（内置预设或自定义端点）</div>
          </div>
          <n-tag v-if="mcpCount" size="small" round :bordered="false" class="count-tag">
            {{ mcpCount }}
          </n-tag>
        </div>
        <n-button size="small" secondary type="primary" @click="addingMcp = true">
          + 新增 MCP 服务器
        </n-button>
      </div>

      <template v-if="mcpCount">
        <n-card v-for="name in mcpServerNames" :key="`m-${name}`" size="small" class="card">
          <template #header>
            <div class="card-head">
              <div class="card-head-left">
                <span class="dot dot-cyan"></span>
                <span class="card-title">{{ name }}</span>
                <n-tag
                  v-if="cfg.mcp_servers[name].preset"
                  size="tiny"
                  round
                  :bordered="false"
                  class="subtle-tag"
                >
                  preset · {{ cfg.mcp_servers[name].preset }}
                </n-tag>
                <n-tag
                  v-if="cfg.mcp_servers[name].preset && MCP_PRESETS_NEED_KEY.includes(cfg.mcp_servers[name].preset!)"
                  size="tiny"
                  round
                  :bordered="false"
                  :type="cfg.mcp_servers[name].api_key_set ? 'success' : 'warning'"
                  class="subtle-tag"
                >
                  {{ cfg.mcp_servers[name].api_key_set ? '密钥已设' : '需密钥未设' }}
                </n-tag>
                <n-tag
                  size="tiny"
                  round
                  :bordered="false"
                  :type="cfg.mcp_servers[name].enabled === false ? 'default' : 'success'"
                >
                  {{ cfg.mcp_servers[name].enabled === false ? '停用' : '启用' }}
                </n-tag>
              </div>
              <n-button size="tiny" quaternary type="error" @click="removeMcpServer(name)">
                删除
              </n-button>
            </div>
          </template>
          <n-grid :cols="2" :x-gap="16" responsive="screen">
            <n-form-item-gi label="preset" label-placement="top" style="margin-bottom: 12px">
              <n-select
                :value="cfg.mcp_servers[name].preset ?? null"
                :options="MCP_PRESET_OPTIONS"
                clearable
                placeholder="自定义：留空并填写 url"
                @update:value="(v: string | null) => (cfg.mcp_servers[name].preset = v)"
              />
            </n-form-item-gi>
            <n-form-item-gi label="url" label-placement="top" style="margin-bottom: 12px">
              <n-input
                :value="cfg.mcp_servers[name].url ?? ''"
                placeholder="https://example.com/mcp"
                class="mono-input"
                @update:value="(v: string) => (cfg.mcp_servers[name].url = v || null)"
              />
            </n-form-item-gi>
            <n-form-item-gi label="api_key（不回显）" label-placement="top" style="margin-bottom: 12px">
              <n-input
                v-model:value="mcpApiKeys[name]"
                type="password"
                show-password-on="mousedown"
                :placeholder="cfg.mcp_servers[name].api_key_set ? '已设置（输入以更新）' : '预设需要密钥时填写'"
                style="width: 100%"
              >
                <template #suffix>
                  <n-button
                    v-if="!clearedMcpApiKeys[name] && cfg.mcp_servers[name].api_key_set"
                    size="tiny"
                    quaternary
                    type="error"
                    @click="clearMcpApiKey(name)"
                  >
                    清除
                  </n-button>
                  <span v-else-if="clearedMcpApiKeys[name]" class="cleared-tag">已标记清除</span>
                </template>
              </n-input>
              <div class="field-hint mono">
                环境变量注入：BTCM_MCP_{{ envVarName(name) }}_API_KEY（优先于此处，不回写）
              </div>
            </n-form-item-gi>
            <n-form-item-gi label="单请求超时（秒）" label-placement="top" style="margin-bottom: 12px">
              <n-input-number
                :value="cfg.mcp_servers[name].timeout ?? 60"
                :min="1"
                style="width: 100%"
                @update:value="(v: number | null) => (cfg.mcp_servers[name].timeout = v ?? 60)"
              />
            </n-form-item-gi>
            <n-form-item-gi label="启用" label-placement="top" style="margin-bottom: 12px">
              <n-switch
                :value="cfg.mcp_servers[name].enabled ?? true"
                @update:value="(v: boolean) => (cfg.mcp_servers[name].enabled = v)"
              />
            </n-form-item-gi>
            <n-form-item-gi label="允许私网地址" label-placement="top" style="margin-bottom: 12px">
              <n-switch
                :value="cfg.mcp_servers[name].allow_private ?? false"
                @update:value="(v: boolean) => (cfg.mcp_servers[name].allow_private = v)"
              />
            </n-form-item-gi>
            <n-form-item-gi label="allowed_tools（留空 = 全部）" label-placement="top" style="margin-bottom: 12px">
              <n-dynamic-tags
                :value="cfg.mcp_servers[name].allowed_tools ?? []"
                style="width: 100%"
                @update:value="(v: string[]) => (cfg.mcp_servers[name].allowed_tools = v)"
              />
            </n-form-item-gi>
          </n-grid>
        </n-card>
      </template>
      <div v-else class="empty-well">
        <n-empty description="暂无 MCP 服务器，点击右上角「新增 MCP 服务器」添加" />
      </div>
    </section>

    <!-- Agent 路由与参数 -->
    <section class="section">
      <div class="section-head">
        <div class="section-heading">
          <span class="bar bar-green"></span>
          <div>
            <div class="section-title">Agent 路由与参数</div>
            <div class="section-desc">按角色绑定提供商与模型，可选跟随全局默认</div>
          </div>
          <n-tag v-if="agentCount" size="small" round :bordered="false" class="count-tag">
            {{ agentCount }}
          </n-tag>
        </div>
      </div>

      <template v-if="agentCount">
        <n-card v-for="name in agentNames" :key="`a-${name}`" size="small" class="card">
          <template #header>
            <div class="card-head">
              <div class="card-head-left">
                <span class="dot dot-green"></span>
                <span class="card-title">{{ name }}</span>
                <n-tag size="tiny" round :bordered="false" :type="followGlobal[name] ? 'info' : 'default'" class="subtle-tag">
                  {{ followGlobal[name] ? '跟随全局' : '显式指定' }}
                </n-tag>
                <span class="route">{{ effectiveRoute(name) }}</span>
              </div>
              <n-button
                size="tiny"
                quaternary
                :type="followGlobal[name] ? 'warning' : 'info'"
                @click="toggleFollowGlobal(name)"
              >
                {{ followGlobal[name] ? '取消跟随' : '跟随全局' }}
              </n-button>
            </div>
          </template>
          <n-grid :cols="3" :x-gap="16" responsive="screen">
            <n-form-item-gi label="provider" label-placement="top" style="margin-bottom: 12px">
              <n-select
                v-model:value="cfg.agents[name].provider"
                :disabled="followGlobal[name]"
                :options="providerNames.map((p) => ({
                  label: p + (cfg.providers[p].enabled === false ? '（已停用）' : ''),
                  value: p,
                  disabled: cfg.providers[p].enabled === false
                }))"
                clearable
                :placeholder="followGlobal[name] ? resolvedProvider(name) : '选择提供商'"
              />
            </n-form-item-gi>
            <n-form-item-gi label="model" label-placement="top" style="margin-bottom: 12px">
              <template v-if="followGlobal[name]">
                <div class="resolved-route">{{ resolvedModel(name) }}</div>
                <div class="field-hint">跟随全局默认</div>
              </template>
              <template v-else>
                <n-select
                  v-if="!useCustomModel[name]"
                  :value="cfg.agents[name].model"
                  :options="modelSelectOptions(name)"
                  filterable
                  clearable
                  :placeholder="cfg.agents[name].provider ? '选择模型' : '请先选择提供商'"
                  @update:value="(v: string | null) => cfg.agents[name].model = v"
                />
                <n-input
                  v-else
                  :value="cfg.agents[name].model ?? ''"
                  placeholder="输入自定义模型名"
                  class="mono-input"
                  @update:value="(v: string) => cfg.agents[name].model = v || null"
                />
                <div class="model-toggle">
                  <n-button text size="tiny" type="primary" @click="useCustomModel[name] = !useCustomModel[name]">
                    {{ useCustomModel[name] ? '从列表选择' : '输入自定义模型名' }}
                  </n-button>
                  <span v-if="cfg.agents[name].provider" class="field-hint mono">
                    可用：{{ providerModels(cfg.agents[name].provider!).join('、') || '无' }}
                  </span>
                </div>
              </template>
            </n-form-item-gi>
            <n-form-item-gi label="temperature" label-placement="top" style="margin-bottom: 12px">
              <n-input-number
                :value="cfg.agents[name].temperature"
                :min="0"
                :max="2"
                :step="0.1"
                style="width: 100%"
                @update:value="(v: number | null) => { if (v != null) (cfg.agents[name].temperature = v) }"
              />
            </n-form-item-gi>
            <n-form-item-gi label="max_tokens" label-placement="top" style="margin-bottom: 12px">
              <n-input-number
                :value="cfg.agents[name].max_tokens"
                :min="256"
                style="width: 100%"
                @update:value="(v: number | null) => { if (v != null) (cfg.agents[name].max_tokens = v) }"
              />
            </n-form-item-gi>
            <n-form-item-gi label="单请求超时（秒，可空）" label-placement="top" style="margin-bottom: 12px">
              <n-input-number
                :value="cfg.agents[name].timeout ?? null"
                :min="1"
                style="width: 100%"
                clearable
                @update:value="(v: number | null) => (cfg.agents[name].timeout = v ?? null)"
              />
            </n-form-item-gi>

            <n-form-item-gi v-if="name === 'creative'" label="num_candidates" label-placement="top" style="margin-bottom: 12px">
              <n-input-number
                :value="cfg.agents[name].num_candidates"
                :min="1"
                style="width: 100%"
                @update:value="(v: number | null) => { if (v != null) (cfg.agents[name].num_candidates = v) }"
              />
            </n-form-item-gi>

            <template v-if="name === 'validator'">
              <n-form-item-gi label="允许联网搜索" label-placement="top" style="margin-bottom: 12px">
                <n-switch v-model:value="cfg.agents[name].enable_web_search" />
              </n-form-item-gi>
              <n-form-item-gi label="web_sources（回车添加标签）" label-placement="top" style="margin-bottom: 12px">
                <n-dynamic-tags
                  v-model:value="cfg.agents[name].web_sources"
                  style="width: 100%"
                />
              </n-form-item-gi>
              <n-form-item-gi label="MCP 服务器（可用时调用）" label-placement="top" style="margin-bottom: 12px">
                <n-select
                  :value="cfg.agents[name].mcp_servers ?? []"
                  multiple
                  clearable
                  :options="mcpServerNames.map((s) => ({ label: s, value: s }))"
                  placeholder="从注册表选择，留空 = 纯逻辑验证"
                  @update:value="(v: string[]) => (cfg.agents[name].mcp_servers = v)"
                />
              </n-form-item-gi>
            </template>

            <n-form-item-gi v-if="name === 'meta'" label="log_intermediate" label-placement="top" style="margin-bottom: 12px">
              <n-switch v-model:value="cfg.agents[name].log_intermediate" />
            </n-form-item-gi>
          </n-grid>
        </n-card>
      </template>
      <div v-else class="empty-well">
        <n-empty description="暂无 Agent 配置" />
      </div>
    </section>

    <!-- 新增提供商模态 -->
    <n-modal v-model:show="addingProvider" preset="card" title="新增提供商" style="width: 480px">
      <n-form label-placement="top">
        <n-form-item label="服务预设（自动填充名称与地址）">
          <n-select
            :value="newProviderPreset"
            :options="PROVIDER_PRESET_OPTIONS"
            clearable
            placeholder="选择常用服务，或留空手填"
            @update:value="onNewProviderPresetChange"
          />
        </n-form-item>
        <n-form-item label="名称">
          <n-input v-model:value="newProviderName" placeholder="如 deepseek、ollama-local" />
        </n-form-item>
        <n-form-item label="base_url（OpenAI 兼容端点）">
          <n-input
            v-model:value="newProviderBaseUrl"
            class="mono-input"
            placeholder="如 http://localhost:11434/v1"
          />
        </n-form-item>
        <n-form-item label="api_key（本地服务可留空，稍后也可在卡片中填写）">
          <n-input
            v-model:value="newProviderApiKey"
            type="password"
            show-password-on="mousedown"
            placeholder="输入后保存配置时一并写入"
          />
        </n-form-item>
        <p class="modal-hint">
          添加后可在卡片上点「拉取模型」从服务端获取模型列表，免去手敲。
        </p>
      </n-form>
      <template #footer>
        <n-button @click="addingProvider = false">取消</n-button>
        <n-button type="primary" @click="addProvider">添加</n-button>
      </template>
    </n-modal>

    <!-- 新增 MCP 服务器模态 -->
    <n-modal v-model:show="addingMcp" preset="card" title="新增 MCP 服务器" style="width: 460px">
      <n-form label-placement="top">
        <n-form-item label="名称">
          <n-input v-model:value="newMcpName" placeholder="如 tavily、内网知识库" />
        </n-form-item>
        <n-form-item label="内置预设（选择后免填 url，密钥保存后在下表填入）">
          <n-select
            v-model:value="newMcpPreset"
            :options="MCP_PRESET_OPTIONS"
            clearable
            placeholder="自定义：留空并填写 url"
          />
        </n-form-item>
        <n-form-item v-if="!newMcpPreset" label="url（Streamable HTTP 端点）">
          <n-input v-model:value="newMcpUrl" placeholder="https://example.com/mcp" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-button @click="addingMcp = false">取消</n-button>
        <n-button type="primary" @click="addMcpServer">添加</n-button>
      </template>
    </n-modal>
  </n-spin>
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
  color: #8a92a6;
}
.page-stats {
  display: flex;
  gap: 8px;
}
.stat {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: #9aa3b8;
  padding: 5px 12px;
  border: 1px solid rgba(148, 163, 200, 0.14);
  border-radius: 999px;
  background: rgba(18, 22, 33, 0.5);
}
.stat b {
  font-weight: 600;
  color: #e8ecf5;
  font-variant-numeric: tabular-nums;
}
.stat-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  box-shadow: 0 0 8px currentColor;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 14px;
  margin-bottom: 20px;
  border: 1px solid rgba(148, 163, 200, 0.14);
  border-radius: 12px;
  background: rgba(18, 22, 33, 0.55);
  backdrop-filter: blur(8px);
}
.toolbar-hint {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #8a92a6;
}
.toolbar-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 10px rgba(52, 211, 153, 0.7);
}
.toolbar-actions {
  display: flex;
  gap: 10px;
}

.section {
  margin-bottom: 28px;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin: 0 2px 12px;
}
.section-heading {
  display: flex;
  align-items: center;
  gap: 10px;
}
.bar {
  width: 4px;
  height: 26px;
  border-radius: 2px;
  flex: none;
}
.bar-blue {
  background: linear-gradient(180deg, #8794ff, #5466e0);
  box-shadow: 0 0 10px rgba(109, 124, 255, 0.5);
}
.bar-violet {
  background: linear-gradient(180deg, #a78bfa, #7c6cf0);
  box-shadow: 0 0 10px rgba(139, 124, 255, 0.5);
}
.bar-cyan {
  background: linear-gradient(180deg, #38bdf8, #0ea5e9);
  box-shadow: 0 0 10px rgba(56, 189, 248, 0.5);
}
.bar-green {
  background: linear-gradient(180deg, #34d399, #10b981);
  box-shadow: 0 0 10px rgba(52, 211, 153, 0.5);
}
.section-title {
  font-size: 14px;
  font-weight: 500;
  color: #e8ecf5;
  line-height: 1.2;
}
.section-desc {
  margin-top: 2px;
  font-size: 12px;
  color: #8a92a6;
}
.count-tag {
  margin-left: 2px;
  background: rgba(109, 124, 255, 0.16);
  color: #a8b8ff;
}

.card {
  margin-bottom: 14px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}
.card-head-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}
.dot-cyan {
  background: #38bdf8;
  box-shadow: 0 0 8px rgba(56, 189, 248, 0.7);
}
.dot-green {
  background: #34d399;
  box-shadow: 0 0 8px rgba(52, 211, 153, 0.7);
}
.card-title {
  font-size: 14px;
  font-weight: 500;
  flex: none;
}
.chip {
  font-size: 12px;
  color: #9aa3b8;
  padding: 2px 8px;
  border: 1px solid rgba(148, 163, 200, 0.12);
  border-radius: 6px;
  background: rgba(11, 14, 22, 0.5);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 320px;
}
.subtle-tag {
  background: rgba(148, 163, 200, 0.12);
  color: #9aa3b8;
}
.route {
  font-size: 12px;
  color: #b9c1d3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.resolved-route {
  font-size: 13px;
  color: #e8ecf5;
  padding: 6px 0;
}
.model-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.mono,
.mono-input :deep(input),
.mono-input :deep(textarea) {
  font-family: 'JetBrains Mono', 'SFMono-Regular', 'Cascadia Code', Consolas, monospace;
}
.field-hint {
  margin-top: 5px;
  font-size: 11px;
  color: #6b7280;
  line-height: 1.5;
  word-break: break-all;
}

.cleared-tag {
  font-size: 12px;
  color: #f87171;
}
.card-head-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: none;
}
.modal-hint {
  margin: 0;
  font-size: 12px;
  color: #8a92a6;
  line-height: 1.6;
}
.empty-well {
  padding: 8px 0 4px;
}

@media (max-width: 640px) {
  .page-head {
    flex-direction: column;
    align-items: flex-start;
  }
  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }
  .toolbar-actions {
    flex-wrap: wrap;
  }
  .chip {
    max-width: 160px;
  }
}
</style>