/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端 API 基址（独立部署时指向后端，如 http://127.0.0.1:8000；默认同源） */
  readonly VITE_API_BASE?: string
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}
