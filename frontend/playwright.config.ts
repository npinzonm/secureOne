import { defineConfig, devices } from "@playwright/test";

// E2E contra el ambiente de PRUEBAS (scripts/test-e2e.sh). El navegador resuelve
// "localhost" hacia el contenedor nginx: así el origen es un contexto seguro y la cookie de
// refresh con atributo Secure funciona igual que para un usuario en http://127.0.0.1.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:8080",
    locale: "es-CO",
    trace: "retain-on-failure",
    launchOptions: { args: [`--host-resolver-rules=MAP localhost ${process.env.E2E_HOST ?? "nginx"}`] },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
