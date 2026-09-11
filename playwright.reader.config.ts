import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './tests/e2e', testMatch: ['reader.spec.ts', 'site-auth.spec.ts'], fullyParallel: false, workers: 1,
  timeout: 90000, use: { baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure' },
  webServer: [
    { command: 'pnpm dev', url: 'http://127.0.0.1:5173', reuseExistingServer: false },
    { command: 'backend/.venv-reader/bin/python scripts/reader_test_server.py', url: 'http://127.0.0.1:8000/api/health', reuseExistingServer: false },
  ],
  projects: [{ name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } }],
})

