import { defineConfig } from "@playwright/test";

// 端到端：起一个隔离库的真实后端（uvicorn），浏览器用环境自带 Chromium。
const PORT = 8123;
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
  },
  webServer: {
    command: `cd .. && rm -f e2e.db && DEALDESK_DB=e2e.db ${process.env.PYTHON ?? ".venv/bin/python"} -m uvicorn app.main:app --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/v2/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
