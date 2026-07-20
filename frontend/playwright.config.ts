import { defineConfig } from '@playwright/test';

// E2E against the live stack (backend + fixture LLM). Runs in CI where the
// services are up; not part of the local unit gate. `webServer` boots the built
// SPA; the backend is expected on :8000 (compose or CI service).
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  use: {
    baseURL: process.env.SPIDEY_E2E_BASE_URL ?? 'http://localhost:4173',
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'npm run preview -- --port 4173',
    url: 'http://localhost:4173',
    reuseExistingServer: !process.env.CI,
  },
});
