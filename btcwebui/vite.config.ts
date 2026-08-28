import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// dev 时将 /api 代理到后端本体；生产由 FastAPI 同源托管，无需代理
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    // 产物输出到 btcwebui/build/，再由脚本复制到 btcmodule/static/（spec 约定）
    outDir: 'build',
    // 沙箱环境会拦截工作区内非空目录删除；旧产物由部署前手动清理
    emptyOutDir: false,
    rollupOptions: {
      output: {
        // 框架与 UI 库独立 chunk：长缓存 + 主包瘦身
        manualChunks: {
          vue: ['vue', 'vue-router'],
          naive: ['naive-ui'],
        },
      },
    },
  },
})
