import { defineConfig } from "@playwright/test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(webRoot, "../..");

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://127.0.0.1:4173", browserName: "chromium" },
  webServer: [
    {
      command: "python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000",
      cwd: repoRoot,
      port: 8000,
      reuseExistingServer: !process.env.CI,
      env: { DATABASE_URL: "sqlite:///./lifeline-e2e.sqlite3" },
    },
    {
      command: "npm run build && npm run preview -- --host 127.0.0.1 --port 4173",
      cwd: webRoot,
      port: 4173,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
