import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { NaiveUiResolver } from 'unplugin-vue-components/resolvers'
import { fileURLToPath, URL } from 'node:url'

// dev 时 /api 代理到后端本体；生产独立部署：后端开 CORS，前端经
// VITE_API_BASE 指向后端（默认同源 /api）。
export default defineConfig({
  plugins: [
    vue(),
    // naive-ui 组件按需自动引入：模板 <n-xxx> 无需手动 import，tree-shaking 生效
    Components({ resolvers: [NaiveUiResolver()] }),
  ],
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
    // 独立构建产物，输出到 btcwebui/build/，由任意静态服务器托管
    // （前端与后端解耦，不再复制进后端包）
    outDir: 'build',
    // 每次构建清空旧产物：hashed 文件名只在当次有效，累积只会越滚越大
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // 框架独立 chunk：长缓存 + 主包瘦身。
        // 注意不要把 naive-ui 包入口写进 manualChunks——那会把整包
        // 拉进单一 chunk；按需引入的组件由 rollup 自动聚成共享 chunk
        manualChunks: {
          vue: ['vue', 'vue-router'],
        },
      },
    },
  },
})
