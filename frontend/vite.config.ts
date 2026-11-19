import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 构建产物直接丢给 FastAPI 托管（backend/static），不需要单独部署前端
export default defineConfig({
  // FastAPI 把 backend/static 挂在 /static 下，资源前缀必须跟着改，
  // 否则 index.html 里引用的 /assets/*.js 会 404
  base: '/static/',
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      // 开发时把 /api 转发到后端
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
