import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";
const receipts =
  process.env.PURCHASE_RECEIPTS ||
  join(tmpdir(), "greeneat-purchase-web-receipts");
export default defineConfig({
  testDir: "./browser",
  testMatch: "*.spec.mjs",
  workers: 1,
  fullyParallel: false,
  timeout: 20000,
  retries: 0,
  outputDir: `${receipts}/browser-artifacts`,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:4175", trace: "retain-on-failure" },
  webServer: {
    command: "npm run build && npm run preview -- --host 127.0.0.1 --port 4175 --strictPort",
    url: "http://127.0.0.1:4175",
    reuseExistingServer: false,
    env: {
      VITE_SUPABASE_URL: "http://127.0.0.1:4175/auth-fixture",
      VITE_SUPABASE_ANON_KEY: "public-fixture-only",
      VITE_API_BASE_URL: "http://127.0.0.1:4175/api-fixture",
    },
  },
});
