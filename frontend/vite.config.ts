/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 产物输出到 ../static/app（入库）：FastAPI StaticFiles 与 Vercel 都按静态文件直接服务，部署零构建。
// 用 hash 路由（#/deals/1），无需服务端重写规则。
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: {
    outDir: "../static/app",
    emptyOutDir: true,
    sourcemap: false,
    target: "es2022",
    chunkSizeWarningLimit: 300,
  },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8100" } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: { provider: "v8", include: ["src/**/*.{ts,tsx}"], exclude: ["src/**/*.test.*", "src/test/**", "src/api/schema.d.ts", "src/main.tsx"], thresholds: { lines: 80, statements: 80, functions: 75, branches: 70 } },
  },
});
