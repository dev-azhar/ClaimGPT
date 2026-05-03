import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  timeout: 120_000,
  retries: 0,
  reporter: "list",
  workers: 1,
  use: {
    headless: true,
    viewport: { width: 1920, height: 1080 },
    video: {
      mode: "on",
      size: { width: 1920, height: 1080 },
    },
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
});
