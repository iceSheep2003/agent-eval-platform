import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// 展示平台默认跑在 5174，与控制台（frontend-pro，默认 5173）分开。
const PORT = Number(process.env.PORT ?? 5174);
const BACKEND = process.env.EVAL_LOOM_BACKEND ?? 'http://127.0.0.1:8787';

export default defineConfig({
  plugins: [react()],
  server: {
    port: PORT,
    // 走代理而不是直连后端：同源，cookie 与 SSE 都不用处理 CORS。
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/v1': { target: BACKEND, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});
