<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { darkTheme, type GlobalThemeOverrides } from 'naive-ui'
import { RouterLink, RouterView } from 'vue-router'
import { api, ADMIN_TOKEN_CHANGED_EVENT, getAdminToken, setAdminToken } from '@/api/client'
import type { HealthData } from '@/types'

// 语义化主题变量：蓝紫主色 + 青蓝/翡翠辅助色，深色控制台气质
const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#6d7cff',
    primaryColorHover: '#8794ff',
    primaryColorPressed: '#5565e6',
    primaryColorSuppl: '#6d7cff',
    successColor: '#34d399',
    warningColor: '#f6ad55',
    errorColor: '#f87171',
    infoColor: '#38bdf8',
    bodyColor: '#0b0e16',
    cardColor: 'rgba(18, 22, 33, 0.66)',
    modalColor: 'rgba(18, 22, 32, 0.98)',
    popoverColor: 'rgba(24, 28, 42, 0.98)',
    borderColor: 'rgba(148, 163, 200, 0.14)',
    dividerColor: 'rgba(148, 163, 200, 0.10)',
    textColorBase: '#e8ecf5',
    textColor1: '#e8ecf5',
    textColor2: '#b9c1d3',
    textColor3: '#8a92a6',
    borderRadius: '10px',
    borderRadiusSmall: '8px',
    fontFamily:
      '"HarmonyOS Sans SC", "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif',
    fontFamilyMono:
      '"JetBrains Mono", "SFMono-Regular", "Cascadia Code", Consolas, monospace',
  },
  Card: {
    borderRadius: '14px',
    borderColor: 'rgba(148, 163, 200, 0.16)',
    color: 'rgba(18, 22, 33, 0.62)',
    paddingMedium: '18px 20px',
    paddingSmall: '14px 16px',
  },
  Button: {
    borderRadiusMedium: '8px',
    borderRadiusSmall: '7px',
    borderRadiusLarge: '10px',
  },
  Input: {
    borderRadius: '8px',
  },
  Modal: {
    borderRadius: '16px',
  },
}

// ---------- 后端健康状态 ----------

const HEALTH_POLL_MS = 30_000
const online = ref(false)
const health = ref<HealthData | null>(null)
let healthTimer: ReturnType<typeof setInterval> | undefined

async function checkHealth() {
  try {
    health.value = await api.getHealth()
    online.value = true
  } catch {
    online.value = false
    health.value = null
  }
}

function formatUptime(s: number): string {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (h > 0) return `${h} 时 ${m} 分`
  if (m > 0) return `${m} 分`
  return `${s} 秒`
}

// ---------- 管理令牌 ----------

const showTokenPop = ref(false)
const tokenInput = ref('')
const tokenSavedHint = ref('')
const hasToken = ref(getAdminToken() !== '')

function saveToken() {
  const t = tokenInput.value.trim()
  if (!t) return
  setAdminToken(t)
  hasToken.value = true
  tokenInput.value = ''
  tokenSavedHint.value = '已保存，受限页面将自动重新加载'
  window.dispatchEvent(new CustomEvent(ADMIN_TOKEN_CHANGED_EVENT))
  setTimeout(() => (tokenSavedHint.value = ''), 2500)
}

function clearToken() {
  setAdminToken('')
  hasToken.value = false
  tokenInput.value = ''
  tokenSavedHint.value = '已清除，受限页面将自动重新加载'
  window.dispatchEvent(new CustomEvent(ADMIN_TOKEN_CHANGED_EVENT))
  setTimeout(() => (tokenSavedHint.value = ''), 2500)
}

onMounted(() => {
  checkHealth()
  healthTimer = setInterval(checkHealth, HEALTH_POLL_MS)
})
onUnmounted(() => clearInterval(healthTimer))
</script>

<template>
  <n-config-provider :theme="darkTheme" :theme-overrides="themeOverrides">
    <n-message-provider>
      <n-dialog-provider>
        <n-layout position="absolute" class="app-root">
          <n-layout-header bordered class="header">
            <div class="brand">
              <span class="brand-mark" aria-hidden="true">
                <svg viewBox="0 0 64 64" width="20" height="20">
                  <defs>
                    <linearGradient id="bm-g" x1="0" y1="1" x2="1" y2="0">
                      <stop offset="0" stop-color="#6D7CFF" />
                      <stop offset="1" stop-color="#38BDF8" />
                    </linearGradient>
                  </defs>
                  <rect width="64" height="64" rx="13" fill="#101014" />
                  <path
                    d="M32 13 L51.5 46.5 L12.5 46.5 Z"
                    fill="url(#bm-g)"
                    stroke="url(#bm-g)"
                    stroke-width="4.5"
                    stroke-linejoin="round"
                  />
                </svg>
              </span>
              <span>
                <span class="brand-title">BTCM</span>
                <span class="brand-sub">副思考链模块 · 控制面板</span>
              </span>
            </div>
            <div class="header-right">
              <nav class="nav" aria-label="主导航">
                <RouterLink to="/dashboard">运行</RouterLink>
                <RouterLink to="/config">配置</RouterLink>
                <RouterLink to="/logs">日志</RouterLink>
              </nav>
              <n-tooltip trigger="hover">
                <template #trigger>
                  <span class="health" :class="online ? 'up' : 'down'">
                    <span class="health-dot"></span>
                    {{ online ? '在线' : '离线' }}
                  </span>
                </template>
                <template v-if="online && health">
                  后端 v{{ health.version }} · 已运行 {{ formatUptime(health.uptime_s) }}
                </template>
                <template v-else>无法连接后端，请确认服务已启动</template>
              </n-tooltip>
              <n-popover v-model:show="showTokenPop" trigger="click" placement="bottom-end">
                <template #trigger>
                  <button type="button" class="token-btn" title="管理令牌">
                    <span class="token-dot" :class="{ set: hasToken }"></span>
                    令牌
                  </button>
                </template>
                <div class="token-pop">
                  <div class="token-pop-title">管理令牌（X-Admin-Token）</div>
                  <p class="token-pop-desc">
                    后端设置 admin_token 后，写配置 / 重置 / 日志接口需携带令牌。
                    {{ hasToken ? '当前浏览器已保存令牌。' : '当前浏览器未保存令牌。' }}
                  </p>
                  <n-input
                    v-model:value="tokenInput"
                    type="password"
                    show-password-on="mousedown"
                    size="small"
                    placeholder="输入令牌并保存"
                    @keydown.enter="saveToken"
                  />
                  <div class="token-pop-actions">
                    <n-button size="tiny" tertiary type="error" :disabled="!hasToken" @click="clearToken">
                      清除
                    </n-button>
                    <n-button size="tiny" type="primary" :disabled="!tokenInput.trim()" @click="saveToken">
                      保存
                    </n-button>
                  </div>
                  <p v-if="tokenSavedHint" class="token-pop-hint">{{ tokenSavedHint }}</p>
                </div>
              </n-popover>
            </div>
          </n-layout-header>
          <n-layout-content class="content" content-style="min-height: 100%">
            <main class="page">
              <RouterView />
            </main>
          </n-layout-content>
        </n-layout>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<style>
html,
body,
#app {
  height: 100%;
  margin: 0;
}
/* 背景纵深：多向辉光叠加，蓝紫为主、青蓝与翡翠点缀，避免纯黑平铺 */
body {
  background:
    radial-gradient(1100px 520px at 18% -12%, rgba(109, 124, 255, 0.18), transparent 62%),
    radial-gradient(820px 420px at 88% -4%, rgba(56, 189, 248, 0.10), transparent 55%),
    radial-gradient(1000px 620px at 50% 112%, rgba(52, 211, 153, 0.07), transparent 60%),
    #0b0e16;
  color: #e8ecf5;
}
.app-root {
  background: transparent;
}
.header {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 58px;
  background: rgba(11, 14, 22, 0.7);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(148, 163, 200, 0.12);
}
/* 顶部渐变描边：一条贯穿的 accent 线 */
.header::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(109, 124, 255, 0.65) 30%,
    rgba(56, 189, 248, 0.45) 70%,
    transparent
  );
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand-mark {
  display: inline-flex;
  align-items: center;
  line-height: 1;
  filter: drop-shadow(0 0 6px rgba(109, 124, 255, 0.55));
}
.brand-title {
  font-weight: 500;
  font-size: 17px;
  letter-spacing: 0.4px;
}
.brand-sub {
  margin-left: 8px;
  font-size: 12px;
  color: #8a92a6;
}
.nav {
  display: flex;
  gap: 4px;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 14px;
}
.nav a {
  position: relative;
  color: #9aa3b8;
  text-decoration: none;
  font-size: 14px;
  padding: 7px 14px;
  border-radius: 8px;
  transition: color 0.15s, background 0.15s;
}
.nav a:hover {
  color: #dbe0ec;
  background: rgba(148, 163, 200, 0.08);
}
.nav a.router-link-active {
  color: #fff;
  font-weight: 500;
  background: rgba(109, 124, 255, 0.16);
  box-shadow: inset 0 0 0 1px rgba(109, 124, 255, 0.35);
}
.health {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #9aa3b8;
  padding: 5px 10px;
  border: 1px solid rgba(148, 163, 200, 0.14);
  border-radius: 999px;
  cursor: default;
  white-space: nowrap;
}
.health-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.health.up .health-dot {
  background: #34d399;
  box-shadow: 0 0 8px rgba(52, 211, 153, 0.8);
}
.health.up {
  color: #7ee2b8;
}
.health.down .health-dot {
  background: #f87171;
  box-shadow: 0 0 8px rgba(248, 113, 113, 0.8);
}
.health.down {
  color: #f0a4a4;
}
.token-btn {
  appearance: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font: inherit;
  font-size: 12px;
  color: #9aa3b8;
  background: transparent;
  border: 1px solid rgba(148, 163, 200, 0.14);
  border-radius: 999px;
  padding: 5px 12px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
  white-space: nowrap;
}
.token-btn:hover {
  color: #dbe0ec;
  border-color: rgba(148, 163, 200, 0.32);
}
.token-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #5d6474;
}
.token-dot.set {
  background: #38bdf8;
  box-shadow: 0 0 8px rgba(56, 189, 248, 0.8);
}
.token-pop {
  width: 300px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.token-pop-title {
  font-size: 13px;
  font-weight: 500;
  color: #e8ecf5;
}
.token-pop-desc {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: #8a92a6;
}
.token-pop-actions {
  display: flex;
  justify-content: space-between;
}
.token-pop-hint {
  margin: 0;
  font-size: 12px;
  color: #34d399;
}
.content {
  background: transparent;
}
.page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px 24px 48px;
}

/* 等宽数字：状态数据用 tabular 对齐 */
.n-num {
  font-variant-numeric: tabular-nums;
}

/* 细滚动条：控制台质感 */
::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 200, 0.18);
  border-radius: 6px;
  border: 2px solid transparent;
  background-clip: padding-box;
}
::-webkit-scrollbar-thumb:hover {
  background: rgba(148, 163, 200, 0.32);
  background-clip: padding-box;
}
::selection {
  background: rgba(109, 124, 255, 0.35);
}

@media (max-width: 640px) {
  .header {
    padding: 0 14px;
  }
  .brand-sub {
    display: none;
  }
  .header-right {
    gap: 8px;
  }
  .health,
  .token-btn {
    padding: 5px 8px;
  }
  .page {
    padding: 14px 14px 40px;
  }
}
</style>