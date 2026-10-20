import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  workers: 1,
  timeout: 45000,
  use: { baseURL: 'http://127.0.0.1:5174', reducedMotion: 'reduce', trace: 'off' },
  webServer: [
    {
      command: 'uv run --locked python scripts/e2e_server.py', cwd: '../investiq-be',
      url: 'http://127.0.0.1:8081/api/v1/health/ready',
      reuseExistingServer: false, gracefulShutdown: { signal: 'SIGTERM', timeout: 10000 },
    },
    {
      command: 'npm run dev -- --port 5174', url: 'http://127.0.0.1:5174',
      env: { API_PROXY_TARGET: 'http://127.0.0.1:8081' },
      reuseExistingServer: false, gracefulShutdown: { signal: 'SIGTERM', timeout: 5000 },
    },
  ],
});
