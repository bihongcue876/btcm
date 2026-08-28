// 将 vite 构建产物（build/）复制到 btcmodule/static/，实现单端口托管（spec 约定）
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const buildDir = path.resolve(here, '../build')
const staticDir = path.resolve(here, '../btcmodule/static')

if (!existsSync(buildDir)) {
  console.error('[copy-static] 未找到构建产物，请先执行 pnpm build')
  process.exit(1)
}

// 清空旧产物；某些沙箱环境会拦截删除，失败则退化为覆盖复制
try {
  rmSync(staticDir, { recursive: true, force: true })
} catch {
  console.warn('[copy-static] 警告：无法清空 static 目录，旧产物可能残留')
}
mkdirSync(staticDir, { recursive: true })

// 条目级复制，避免「目录复制到已存在目录」时嵌套出 static/build/
for (const entry of readdirSync(buildDir)) {
  cpSync(path.join(buildDir, entry), path.join(staticDir, entry), {
    recursive: true,
  })
}
console.log('[copy-static] 已复制 build/ → btcmodule/static/')
