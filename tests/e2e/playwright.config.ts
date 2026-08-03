import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  timeout: 30_000,
  retries: 0,
  reporter: "line",
  use: { baseURL: "http://localhost:3000", trace: "retain-on-failure" },
  webServer: [
    { command: "node ../../scripts/start-api-e2e.mjs", url: "http://127.0.0.1:8000/health", reuseExistingServer: false },
    { command: "npm --prefix ../.. run dev:web", url: "http://localhost:3000", reuseExistingServer: false },
  ],
});
