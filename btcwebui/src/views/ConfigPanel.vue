<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import { api, ApiError, setAdminToken } from '@/api/client'
import type { GlobalConfig, MCPServerConfig } from '@/types'

const message = useMessage()
const dialog = useDialog()
const loading = ref(false)
const submitting = ref(false)

const cfg = reactive<GlobalConfig>({
  max_iterations: 2,
  timeout: 300,
  enable_creative: true,
  enable_validator: true,
  providers: {},
  mcp_servers: {},
  agents: {},
})

// api_key 不回显：单独保存输入值，仅提交时并入；cleared 标记请求服务端清除该 key
const apiKeys = reactive<Record<string, string>>({})
const clearedApiKeys = reactive<Record<string, boolean>>({})
const providerNames = ref<string[]>([])
const agentNames = ref<string[]>([])

// MCP 服务器：api_key 同样不回显
const mcpServerNames = ref<string[]>([])
const mcpApiKeys = reactive<Record<string, string>>({})
const clearedMcpApiKeys = reactive<Record<string, boolean>>({})

// admin_token：写入式输入，不回显；保存后存 localStorage 供请求头附加
const adminTokenInput = ref('')
const clearedAdminToken = ref(false)

// 新增提供商模态
const addingProvider = ref(false)
const newProviderName = ref('')
const newProviderBaseUrl = ref('')

// 新增 MCP 服务器模态
const addingMcp = ref(false)
const newMcpName = ref('')
const newMcpPreset = ref<string | null>(null)
const newMcpUrl = ref('')

// 内置市面 MCP 预设（后端 MCP_PRESETS 对齐）
const MCP_PRESET_OPTIONS = [
  { value: 'tavily', label: 'tavily · Tavily 网络搜索（需 api_key）' },
  { value: 'exa', label: 'exa · Exa 搜索（需 api_key）' },
  { value: 'deepwiki', label: 'deepwiki · 开源仓库文档（免密）' },
  { value: 'fetch', label: 'fetch · 网页抓取（免密）' },
]

async function load() {
  loading.value = true
  try {
    const data = await api.getConfig()
    Object.assign(cfg, data)
    if (!cfg.mcp_servers) cfg.mcp_servers = {}
    providerNames.value = Object.keys(cfg.providers)
    agentNames.value = Object.keys(cfg.agents)
    mcpServerNames.value = Object.keys(cfg.mcp_servers)
    Object.keys(apiKeys).forEach((k) => delete apiKeys[k])
    Object.keys(clearedApiKeys).forEach((k) => delete clearedApiKeys[k])
    Object.keys(mcpApiKeys).forEach((k) => delete mcpApiKeys[k])
    Object.keys(clearedMcpApiKeys).forEach((k) => delete clearedMcpApiKeys[k])
    adminTokenInput.value = ''
    clearedAdminToken.value = false
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
  cfg.providers[name] = {
    base_url: newProviderBaseUrl.value.trim() || 'https://api.example.com/v1',
    models: [],
    timeout: 120,
  }
  providerNames.value = Object.keys(cfg.providers)
  addingProvider.value = false
  newProviderName.value = ''
  newProviderBaseUrl.value = ''
  message.success(`已添加提供商 ${name}，记得保存`)
}

function removeProvider(name: string) {
  const usedBy = agentNames.value.filter((a) => cfg.agents[a].provider === name)
  const doRemove = () => {
    delete cfg.providers[name]
    delete apiKeys[name]
    delete clearedApiKeys[name]
    providerNames.value = Object.keys(cfg.providers)
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

// ---------- MCP 服务器 ----------

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
    ? { preset: newMcpPreset.value, enabled: true, timeout: 60, allowed_tools: [] }
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
    // 同步移除各 Agent 对它的引用，避免保存时校验失败
    for (const a of agentNames.value) {
      const refs = cfg.agents[a].mcp_servers
      if (refs?.includes(name)) {
        cfg.agents[a].mcp_servers = refs.filter((s) => s !== name)
      }
    }
    mcpServerNames.value = Object.keys(cfg.mcp_servers)
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
      // provider timeout 后端非 Optional，清空时兜底 120
      if (payload.providers[name].timeout == null) {
        payload.providers[name].timeout = 120
      }
      const key = apiKeys[name]
      if (key && key.trim()) {
        payload.providers[name].api_key = key.trim()
      } else if (clearedApiKeys[name]) {
        payload.providers[name].api_key = null
      }
    }
    for (const name of mcpServerNames.value) {
      const entry = payload.mcp_servers[name]
      if (entry.preset && !entry.url) {
        delete entry.url // 预设服务器由后端按 preset + api_key 解析 URL
      }
      const key = mcpApiKeys[name]
      if (key && key.trim()) {
        entry.api_key = key.trim()
      } else if (clearedMcpApiKeys[name]) {
        entry.api_key = null
      }
    }
    // admin_token：写入式，不回显；输入即更新，清除按钮则置空
    if (adminTokenInput.value.trim()) {
      payload.admin_token = adminTokenInput.value.trim()
      setAdminToken(payload.admin_token)
    } else if (clearedAdminToken.value) {
      payload.admin_token = null
      setAdminToken('')
    }
    await api.updateConfig(payload)
    message.success('配置已保存')
    await load()
  } catch (e) {
    message.error(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e))
  } finally {
    submitting.value = false
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
      <n-button type="primary" :loading="submitting" @click="save">保存配置</n-button>
      <n-button type="error" tertiary @click="confirmReset">重置为默认</n-button>
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
        <n-form-item label="管理令牌 admin_token（不回显）" label-placement="top">
          <n-input
            v-model:value="adminTokenInput"
            type="password"
            show-password-on="mousedown"
            placeholder="设置后写配置/重置/日志接口需 X-Admin-Token"
          >
            <template #suffix>
              <n-button
                v-if="!clearedAdminToken"
                size="tiny"
                quaternary
                type="error"
                @click="() => { clearedAdminToken = true; adminTokenInput = '' }"
              >
                清除
              </n-button>
              <span v-else class="cleared-tag">已清除</span>
            </template>
          </n-input>
        </n-form-item>
      </n-grid>
    </n-card>

    <!-- 提供商注册表 -->
    <div class="section-head">
      <div class="section-title">提供商注册表</div>
      <n-button size="small" secondary type="primary" @click="addingProvider = true">
        + 新增提供商
      </n-button>
    </div>
    <n-card v-for="name in providerNames" :key="`p-${name}`" size="small" class="card">
      <template #header>
        <div class="card-head">
          <span class="card-title">{{ name }}</span>
          <n-button size="tiny" quaternary type="error" @click="removeProvider(name)">
            删除
          </n-button>
        </div>
      </template>
      <n-grid :cols="2" :x-gap="16" responsive="screen">
        <n-form-item label="base_url" label-placement="top" style="margin-bottom: 12px">
          <n-input v-model:value="cfg.providers[name].base_url" />
        </n-form-item>
        <n-form-item
          label="api_key（不回显，留空不修改）"
          label-placement="top"
          style="margin-bottom: 12px"
        >
          <n-input
            v-model:value="apiKeys[name]"
            type="password"
            show-password-on="mousedown"
            placeholder="输入以设置/更新"
            style="width: 100%"
          >
            <template #suffix>
              <n-button
                v-if="!clearedApiKeys[name]"
                size="tiny"
                quaternary
                type="error"
                @click="clearApiKey(name)"
              >
                清除
              </n-button>
              <span v-else class="cleared-tag">已清除</span>
            </template>
          </n-input>
        </n-form-item>
        <n-form-item label="单请求超时（秒）" label-placement="top" style="margin-bottom: 12px">
          <n-input-number
            :value="cfg.providers[name].timeout"
            :min="1"
            :max="3600"
            style="width: 100%"
            @update:value="(v: number | null) => (cfg.providers[name].timeout = v ?? 120)"
          />
        </n-form-item>
        <n-form-item label="models（回车添加标签）" label-placement="top" style="margin-bottom: 12px">
          <n-dynamic-tags
            v-model:value="cfg.providers[name].models"
            :max="20"
            style="width: 100%"
          />
        </n-form-item>
      </n-grid>
    </n-card>

    <!-- MCP 服务器注册表 -->
    <div class="section-head">
      <div class="section-title">MCP 服务器注册表（验证 Agent 联网工具）</div>
      <n-button size="small" secondary type="primary" @click="addingMcp = true">
        + 新增 MCP 服务器
      </n-button>
    </div>
    <n-card v-for="name in mcpServerNames" :key="`m-${name}`" size="small" class="card">
      <template #header>
        <div class="card-head">
          <span class="card-title">{{ name }}</span>
          <n-button size="tiny" quaternary type="error" @click="removeMcpServer(name)">
            删除
          </n-button>
        </div>
      </template>
      <n-grid :cols="2" :x-gap="16" responsive="screen">
        <n-form-item label="preset（内置预设，可清空改用 url）" label-placement="top" style="margin-bottom: 12px">
          <n-select
            :value="cfg.mcp_servers[name].preset ?? null"
            :options="MCP_PRESET_OPTIONS"
            clearable
            placeholder="自定义：留空并填写 url"
            @update:value="(v: string | null) => (cfg.mcp_servers[name].preset = v)"
          />
        </n-form-item>
        <n-form-item label="url（自定义服务器时填写）" label-placement="top" style="margin-bottom: 12px">
          <n-input
            :value="cfg.mcp_servers[name].url ?? ''"
            placeholder="https://example.com/mcp"
            @update:value="(v: string) => (cfg.mcp_servers[name].url = v || null)"
          />
        </n-form-item>
        <n-form-item label="api_key（不回显，留空不修改）" label-placement="top" style="margin-bottom: 12px">
          <n-input
            v-model:value="mcpApiKeys[name]"
            type="password"
            show-password-on="mousedown"
            placeholder="预设需要密钥时填写"
            style="width: 100%"
          >
            <template #suffix>
              <n-button
                v-if="!clearedMcpApiKeys[name]"
                size="tiny"
                quaternary
                type="error"
                @click="clearMcpApiKey(name)"
              >
                清除
              </n-button>
              <span v-else class="cleared-tag">已清除</span>
            </template>
          </n-input>
        </n-form-item>
        <n-form-item label="单请求超时（秒）" label-placement="top" style="margin-bottom: 12px">
          <n-input-number
            :value="cfg.mcp_servers[name].timeout ?? 60"
            :min="1"
            :max="600"
            style="width: 100%"
            @update:value="(v: number | null) => (cfg.mcp_servers[name].timeout = v ?? 60)"
          />
        </n-form-item>
        <n-form-item label="启用" label-placement="top" style="margin-bottom: 12px">
          <n-switch
            :value="cfg.mcp_servers[name].enabled ?? true"
            @update:value="(v: boolean) => (cfg.mcp_servers[name].enabled = v)"
          />
        </n-form-item>
        <n-form-item label="allowed_tools（留空 = 全部工具）" label-placement="top" style="margin-bottom: 12px">
          <n-dynamic-tags
            :value="cfg.mcp_servers[name].allowed_tools ?? []"
            :max="20"
            style="width: 100%"
            @update:value="(v: string[]) => (cfg.mcp_servers[name].allowed_tools = v)"
          />
        </n-form-item>
      </n-grid>
    </n-card>

    <!-- Agent 路由与参数 -->
    <div class="section-title" style="margin-top: 4px">Agent 路由与参数</div>
    <n-card v-for="name in agentNames" :key="`a-${name}`" :title="name" size="small" class="card">
      <n-grid :cols="3" :x-gap="16" responsive="screen">
        <n-form-item label="provider" label-placement="top" style="margin-bottom: 12px">
          <n-select
            v-model:value="cfg.agents[name].provider"
            :options="providerNames.map((p) => ({ label: p, value: p }))"
          />
        </n-form-item>
        <n-form-item label="model" label-placement="top" style="margin-bottom: 12px">
          <n-input
            v-model:value="cfg.agents[name].model"
            :placeholder="`${cfg.agents[name].provider} 上的模型名`"
          />
        </n-form-item>
        <n-form-item label="temperature" label-placement="top" style="margin-bottom: 12px">
          <n-input-number
            :value="cfg.agents[name].temperature"
            :min="0"
            :max="2"
            :step="0.1"
            style="width: 100%"
            @update:value="(v: number | null) => { if (v != null) (cfg.agents[name].temperature = v) }"
          />
        </n-form-item>
        <n-form-item label="max_tokens" label-placement="top" style="margin-bottom: 12px">
          <n-input-number
            :value="cfg.agents[name].max_tokens"
            :min="256"
            :max="32768"
            style="width: 100%"
            @update:value="(v: number | null) => { if (v != null) (cfg.agents[name].max_tokens = v) }"
          />
        </n-form-item>
        <n-form-item label="单请求超时（秒，可空）" label-placement="top" style="margin-bottom: 12px">
          <n-input-number
            :value="cfg.agents[name].timeout ?? null"
            :min="1"
            :max="3600"
            style="width: 100%"
            clearable
            @update:value="(v: number | null) => (cfg.agents[name].timeout = v ?? null)"
          />
        </n-form-item>

        <n-form-item v-if="name === 'creative'" label="num_candidates" label-placement="top" style="margin-bottom: 12px">
          <n-input-number
            :value="cfg.agents[name].num_candidates"
            :min="1"
            :max="10"
            style="width: 100%"
            @update:value="(v: number | null) => { if (v != null) (cfg.agents[name].num_candidates = v) }"
          />
        </n-form-item>

        <template v-if="name === 'validator'">
          <n-form-item label="允许联网搜索" label-placement="top" style="margin-bottom: 12px">
            <n-switch v-model:value="cfg.agents[name].enable_web_search" />
          </n-form-item>
          <n-form-item label="web_sources（回车添加标签）" label-placement="top" style="margin-bottom: 12px">
            <n-dynamic-tags
              v-model:value="cfg.agents[name].web_sources"
              :max="20"
              style="width: 100%"
            />
          </n-form-item>
          <n-form-item label="MCP 服务器（可用时调用）" label-placement="top" style="margin-bottom: 12px">
            <n-select
              :value="cfg.agents[name].mcp_servers ?? []"
              multiple
              clearable
              :options="mcpServerNames.map((s) => ({ label: s, value: s }))"
              placeholder="从注册表选择，留空 = 纯逻辑验证"
              @update:value="(v: string[]) => (cfg.agents[name].mcp_servers = v)"
            />
          </n-form-item>
        </template>

        <n-form-item v-if="name === 'controller'" label="log_intermediate" label-placement="top" style="margin-bottom: 12px">
          <n-switch v-model:value="cfg.agents[name].log_intermediate" />
        </n-form-item>
      </n-grid>
    </n-card>

    <!-- 新增提供商模态 -->
    <n-modal
      v-model:show="addingProvider"
      preset="card"
      title="新增提供商"
      style="width: 420px"
    >
      <n-form label-placement="top">
        <n-form-item label="名称">
          <n-input v-model:value="newProviderName" placeholder="如 openai-compatible" />
        </n-form-item>
        <n-form-item label="base_url（可稍后修改）">
          <n-input
            v-model:value="newProviderBaseUrl"
            placeholder="如 http://localhost:11434/v1"
          />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-button @click="addingProvider = false">取消</n-button>
        <n-button type="primary" @click="addProvider">添加</n-button>
      </template>
    </n-modal>

    <!-- 新增 MCP 服务器模态 -->
    <n-modal
      v-model:show="addingMcp"
      preset="card"
      title="新增 MCP 服务器"
      style="width: 460px"
    >
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
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 4px 2px 10px;
}
.section-title {
  font-size: 13px;
  font-weight: 500;
  color: #8b93a7;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
.card-title {
  font-size: 14px;
  font-weight: 500;
}
.cleared-tag {
  font-size: 12px;
  color: #f56c6c;
}
</style>