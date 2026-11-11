// E2E de SecureOne (Fase 10). Datos y credenciales de PRUEBA los prepara scripts/test-e2e.sh
// en un ambiente efímero; nunca se usan credenciales reales.
import { expect, test, type Page } from "@playwright/test";

const ADMIN = process.env.E2E_USER ?? "";
const ADMIN_PWD = process.env.E2E_PASSWORD ?? "";
const TEMP_USER = process.env.E2E_TEMP_USER ?? "";
const TEMP_PWD = process.env.E2E_TEMP_PASSWORD ?? "";
const NEW_PWD = process.env.E2E_NEW_PASSWORD ?? "";

async function login(page: Page, user: string, pwd: string) {
  await page.goto("/login");
  await page.getByLabel("Usuario de red").fill(user);
  await page.getByLabel("Contraseña").fill(pwd);
  await page.getByRole("button", { name: "Ingresar" }).click();
}

/** Login exitoso: espera al dashboard (sesión establecida y cookie de refresh emitida). */
async function loginOk(page: Page, user = ADMIN, pwd = ADMIN_PWD) {
  // Nginx limita /auth/login a 10/min por IP (ráfaga 5): la suite hace más logins que eso,
  // así que ante un 429 se espera y se reintenta (el límite es un control esperado).
  for (let attempt = 0; attempt < 4; attempt++) {
    const resp = page.waitForResponse((r) => r.url().endsWith("/api/v1/auth/login"));
    await login(page, user, pwd);
    if ((await resp).status() !== 429) break;
    await page.waitForTimeout(7_000);
  }
  await expect(page.getByRole("heading", { name: /Hola,/ })).toBeVisible();
}

/** Petición desde el navegador (mismo origen y cookies que la aplicación). */
async function browserFetch(page: Page, path: string, method = "GET") {
  return page.evaluate(async ([p, m]) => {
    const r = await fetch(p, { method: m, credentials: "same-origin" });
    return { status: r.status, csp: r.headers.get("content-security-policy") ?? "" };
  }, [path, method] as const);
}

test("login fallido muestra el mensaje genérico (PD-17) y no conserva la contraseña", async ({ page }) => {
  await login(page, ADMIN, "Incorrecta#2026x");
  await expect(page.locator(".alert.error")).toHaveText("Usuario o contraseña inválidos.");
  await expect(page.getByLabel("Contraseña")).toHaveValue("");
});

test("contraseña temporal obliga a cambiarla y luego da acceso", async ({ page }) => {
  await login(page, TEMP_USER, TEMP_PWD);
  await expect(page).toHaveURL(/\/cambio-contrasena$/);
  await expect(page.getByText("Debe establecer una nueva contraseña")).toBeVisible();
  await page.getByLabel("Contraseña actual").fill(TEMP_PWD);
  await page.getByLabel("Nueva contraseña", { exact: true }).fill(NEW_PWD);
  await page.getByLabel("Confirmar nueva contraseña").fill(NEW_PWD);
  await page.getByRole("button", { name: "Cambiar contraseña" }).click();
  await expect(page.getByText("Contraseña actualizada")).toBeVisible();
  await login(page, TEMP_USER, NEW_PWD);
  await expect(page.getByRole("heading", { name: /Hola,/ })).toBeVisible();
});

test("la sesión sobrevive a una recarga (token en memoria + refresh HttpOnly)", async ({ page, context }) => {
  await loginOk(page);
  const cookies = await context.cookies();
  const refresh = cookies.find((c) => c.name === "so_refresh");
  expect(refresh?.httpOnly).toBe(true);
  expect(refresh?.sameSite).toBe("Strict");
  // El token de acceso nunca se guarda en almacenamiento del navegador.
  const storage = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
  expect(storage).not.toContain("ey");
  await page.reload();
  await expect(page.getByRole("heading", { name: /Hola,/ })).toBeVisible();
});

test("alta desde Talento Humano: decisión, autoaprobación y temporal de una sola vez", async ({ page }) => {
  await loginOk(page);
  await page.goto("/administracion/talento-humano");
  await page.getByRole("button", { name: "Propuestas" }).click();
  const row = page.getByRole("row").filter({ hasText: "CC-2001" });
  await row.getByRole("button", { name: "Decidir alta" }).click();
  await page.getByLabel("Perfil").selectOption("ANALISTA_E2E");
  await page.getByText("Indicium Insight").click();
  await page.getByRole("button", { name: "Crear solicitud de alta" }).click();
  await expect(page.getByText(/Solicitud de alta #\d+ creada/)).toBeVisible();

  await page.goto("/administracion/solicitudes");
  await page.getByRole("row").filter({ hasText: "ALTA USUARIO" }).first().click();
  await page.getByRole("button", { name: "Aprobar y aplicar" }).click();
  const dialog = page.getByRole("dialog", { name: "Contraseña temporal" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("una sola vez")).toBeVisible();
  await dialog.getByRole("button", { name: "Entendido" }).click();
  await expect(page.getByText("APROBADA")).toBeVisible();
});

test("perfil de sistema protegido y menú filtrado por permisos", async ({ page }) => {
  await loginOk(page);
  await page.goto("/administracion/perfiles");
  const sys = page.getByRole("row").filter({ hasText: "ADMINISTRADOR" }).first();
  await expect(sys.getByText("sistema", { exact: true })).toBeVisible();
  await expect(sys.getByRole("button")).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Administración" }).getByRole("link")).toHaveCount(12);
});

test("aviso de inactividad 60 s antes del cierre y 'Seguir conectado'", async ({ page }) => {
  await loginOk(page);
  // Se simula que el servidor reporta 45 s restantes (la expiración real se probó en Fase 3).
  await page.route("**/api/v1/auth/session", (r) =>
    r.fulfill({ json: { restringida: false, segundos_restantes_inactividad: 45 } }));
  await page.reload();
  const dlg = page.getByRole("dialog", { name: "¿Sigue ahí?" });
  await expect(dlg).toBeVisible({ timeout: 25_000 });
  await page.unroute("**/api/v1/auth/session");
  const me = page.waitForResponse((r) => r.url().endsWith("/api/v1/me") && r.status() === 200);
  await dlg.getByRole("button", { name: "Seguir conectado" }).click();
  await me; // petición real: cuenta como actividad en el servidor
  await expect(dlg).toBeHidden();
});

test("logout invalida la sesión y las rutas protegidas redirigen al login", async ({ page }) => {
  await loginOk(page);
  await page.getByRole("button", { name: "Salir" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/administracion/usuarios");
  await expect(page).toHaveURL(/\/login$/);
  expect((await browserFetch(page, "/api/v1/auth/refresh", "POST")).status).toBe(401);
});

test("la CSP no reporta violaciones en las pantallas principales", async ({ page }) => {
  const violations: string[] = [];
  page.on("console", (m) => { if (/Content Security Policy/i.test(m.text())) violations.push(m.text()); });
  await loginOk(page);
  for (const p of ["/", "/administracion/usuarios", "/administracion/auditoria", "/notificaciones"]) {
    await page.goto(p);
    await page.waitForLoadState("networkidle");
  }
  expect(violations).toEqual([]);
  const res = await browserFetch(page, "/");
  expect(res.csp).toContain("script-src 'self'");
  expect(res.csp).toContain("frame-ancestors 'none'");
});
