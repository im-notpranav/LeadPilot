import { join } from "node:path";
import { defineConfig } from "@playwright/test";

// Starts its own backend (demo mode, in memory, short warm-up) and dashboard on spare ports,
// so E2E runs never touch a dev server or a real database.
const API_PORT = 8010;
const WEB_PORT = 5180;
// A second stack with authentication on, for e2e/auth.spec.ts. Tokens are signed with this test-only secret.
export const AUTH_API_PORT = 8011;
export const AUTH_WEB_PORT = 5181;
export const TEST_JWT_SECRET = "e2e-only-secret-never-used-outside-tests-0123456789";
export const TEST_SUPABASE_URL = "https://e2e-project.supabase.co";
const python = process.platform === "win32" ? join(".venv", "Scripts", "python.exe") : join(".venv", "bin", "python");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    headless: true,
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: "../backend",
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      env: { LEADPILOT_MODE: "demo", LEADPILOT_PERSIST: "0", LEADPILOT_WARMUP_DAYS: "3", LEADPILOT_AUTH: "off" },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `${python} -m uvicorn app.main:app --host 127.0.0.1 --port ${AUTH_API_PORT}`,
      cwd: "../backend",
      url: `http://127.0.0.1:${AUTH_API_PORT}/api/health`,
      env: { LEADPILOT_MODE: "demo", LEADPILOT_PERSIST: "0", LEADPILOT_WARMUP_DAYS: "3", LEADPILOT_AUTH: "on",
             SUPABASE_URL: TEST_SUPABASE_URL, SUPABASE_JWT_SECRET: TEST_JWT_SECRET,
             SUPABASE_ANON_KEY: "sb_publishable_e2e", LEADPILOT_ADMIN_EMAILS: "admin@e2e.test" },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${AUTH_WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${AUTH_WEB_PORT}`,
      env: { LEADPILOT_API: `http://127.0.0.1:${AUTH_API_PORT}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: { LEADPILOT_API: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
