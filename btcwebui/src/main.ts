import { createApp } from 'vue'
import App from './App.vue'
import router from './router'

// naive-ui 组件经 unplugin-vue-components + NaiveUiResolver 按需引入，
// 不做全量 app.use(naive)（会把整个组件库钉进单 chunk，tree-shaking 失效）
createApp(App).use(router).mount('#app')
