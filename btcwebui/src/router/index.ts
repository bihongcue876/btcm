import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/views/Dashboard.vue'),
      meta: { title: '运行' },
    },
    {
      path: '/config',
      name: 'config',
      component: () => import('@/views/ConfigPanel.vue'),
      meta: { title: '配置' },
    },
    {
      path: '/logs',
      name: 'logs',
      component: () => import('@/views/Logs.vue'),
      meta: { title: '日志' },
    },
  ],
})

router.afterEach((to) => {
  document.title = `${String(to.meta.title ?? '')} · BTCM`
})

export default router
