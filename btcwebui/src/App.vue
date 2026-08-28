<script setup lang="ts">
import { darkTheme, type GlobalThemeOverrides } from 'naive-ui'
import { RouterLink, RouterView } from 'vue-router'

// 语义化主题变量：深色观察台气质，主色蓝紫，成功/警告/失败沿用语义
const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#6e8cff',
    primaryColorHover: '#8ba4ff',
    primaryColorPressed: '#5470e6',
    primaryColorSuppl: '#6e8cff',
    successColor: '#3fb68b',
    warningColor: '#e6a23c',
    errorColor: '#f56c6c',
    infoColor: '#5b9bff',
    bodyColor: 'transparent',
    cardColor: 'rgba(24, 28, 40, 0.82)',
    modalColor: 'rgba(24, 28, 40, 0.96)',
    popoverColor: 'rgba(30, 34, 48, 0.98)',
    borderColor: 'rgba(255, 255, 255, 0.08)',
    dividerColor: 'rgba(255, 255, 255, 0.08)',
    fontFamily:
      '"HarmonyOS Sans SC", "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif',
  },
}
</script>

<template>
  <n-config-provider :theme="darkTheme" :theme-overrides="themeOverrides">
    <n-message-provider>
      <n-dialog-provider>
        <n-layout position="absolute" class="app-root">
          <n-layout-header bordered class="header">
            <div class="brand">
              <span class="brand-mark">◆</span>
              <span>
                <span class="brand-title">BTCM</span>
                <span class="brand-sub">副思考链模块 · 控制面板</span>
              </span>
            </div>
            <nav class="nav" aria-label="主导航">
              <RouterLink to="/dashboard">运行</RouterLink>
              <RouterLink to="/config">配置</RouterLink>
              <RouterLink to="/logs">日志</RouterLink>
            </nav>
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
/* 背景纵深：深蓝紫径向渐变 + 顶部辉光，避免纯黑平铺 */
body {
  background:
    radial-gradient(1200px 500px at 20% -10%, rgba(110, 140, 255, 0.16), transparent 60%),
    radial-gradient(900px 420px at 85% 0%, rgba(150, 120, 255, 0.12), transparent 55%),
    radial-gradient(1000px 600px at 50% 110%, rgba(63, 182, 139, 0.07), transparent 60%),
    #0d1017;
  color: #e6e9f2;
}
.app-root {
  background: transparent;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 58px;
  background: rgba(13, 16, 23, 0.72);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand-mark {
  color: #6e8cff;
  font-size: 18px;
  text-shadow: 0 0 12px rgba(110, 140, 255, 0.7);
}
.brand-title {
  font-weight: 500;
  font-size: 17px;
  letter-spacing: 0.4px;
}
.brand-sub {
  margin-left: 8px;
  font-size: 12px;
  color: #8b93a7;
}
.nav {
  display: flex;
  gap: 4px;
}
.nav a {
  color: #9aa2b5;
  text-decoration: none;
  font-size: 14px;
  padding: 7px 14px;
  border-radius: 8px;
  transition: color 0.15s, background 0.15s;
}
.nav a:hover {
  color: #d7dce8;
  background: rgba(255, 255, 255, 0.05);
}
.nav a.router-link-active {
  color: #fff;
  font-weight: 500;
  background: rgba(110, 140, 255, 0.16);
  box-shadow: inset 0 0 0 1px rgba(110, 140, 255, 0.35);
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

@media (max-width: 640px) {
  .header {
    padding: 0 14px;
  }
  .brand-sub {
    display: none;
  }
  .page {
    padding: 14px 14px 40px;
  }
}
</style>
