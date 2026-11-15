import { defineConfig } from "vite";

// 开发时把 /api 代理到本地 FastAPI（8000），这样前端代码里不需要写死后端地址。
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
