import { defineConfig, devices } from '@playwright/test';

// Critical user journeys (Ch. 16.6.2). Run against a seeded stack: npm run test:e2e
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  use: { baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173', trace: 'on-first-retry', screenshot: 'only-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }, { name: 'firefox', use: { ...devices['Desktop Firefox'] } }],
});
