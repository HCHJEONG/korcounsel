import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './tests/e2e', fullyParallel: false,
  use: { baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure' },
  webServer: [
    { command: 'pnpm dev', url: 'http://127.0.0.1:5173', reuseExistingServer: false },
    { command: 'backend/.venv/bin/uvicorn klegal_gold.web.app:app --app-dir backend/src --host 127.0.0.1 --port 8000', url: 'http://127.0.0.1:8000/api/health', reuseExistingServer: false },
  ],
  projects: [ { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } } ],
})
