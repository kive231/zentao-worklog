import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/browser', fullyParallel: false, workers: 1, timeout: 30000,
  use: { channel: process.env.PLAYWRIGHT_CHANNEL || undefined, baseURL: process.env.WORKLOG_E2E_BASE_URL || 'http://127.0.0.1:8766', viewport: { width: 1440, height: 1000 }, screenshot: 'only-on-failure' },
  webServer: process.env.WORKLOG_E2E_BASE_URL ? undefined : { command: `"${process.env.WORKLOG_TEST_PYTHON || '.venv\\Scripts\\python.exe'}" -m uvicorn backend.app:app --host 127.0.0.1 --port 8766`, url: 'http://127.0.0.1:8766/api/health', reuseExistingServer: false },
});
