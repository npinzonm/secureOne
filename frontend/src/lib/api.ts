// Cliente de la API de SecureOne.
// - El access token vive SOLO en memoria (DD-07 / PD-18): nunca en localStorage ni cookies JS.
// - El refresh viaja en cookie HttpOnly (Path=/api/v1/auth) gestionada por el navegador.
// - Ante 401 SESSION_ENDED se intenta UNA renovación y se reintenta la petición.
// La autorización real ocurre en el backend; ocultar controles aquí no es un control de seguridad.

export const API = "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

let accessToken: string | null = null;
let refreshTimer: ReturnType<typeof setTimeout> | null = null;
let onSessionEnded: (() => void) | null = null;

export function setSessionEndedHandler(fn: () => void) {
  onSessionEnded = fn;
}

export function setAccessToken(token: string | null, expiresIn?: number) {
  accessToken = token;
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = null;
  // Renovación proactiva 30 s antes de expirar. El refresh NO cuenta como actividad
  // (no extiende la ventana de inactividad del servidor).
  if (token && expiresIn) {
    refreshTimer = setTimeout(() => {
      void refresh().catch(() => onSessionEnded?.());
    }, Math.max(5, expiresIn - 30) * 1000);
  }
}

export function hasToken() {
  return accessToken !== null;
}

export type TokenOut = {
  access_token: string;
  expires_in: number;
  debe_cambiar_contrasena: boolean;
};

let refreshing: Promise<TokenOut> | null = null;

export async function refresh(): Promise<TokenOut> {
  if (!refreshing) {
    refreshing = (async () => {
      const res = await fetch(`${API}/auth/refresh`, { method: "POST", credentials: "same-origin" });
      if (!res.ok) {
        setAccessToken(null);
        throw await toError(res);
      }
      const data = (await res.json()) as TokenOut;
      setAccessToken(data.access_token, data.expires_in);
      return data;
    })().finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

async function toError(res: Response): Promise<ApiError> {
  try {
    const body = await res.json();
    const e = body?.error ?? {};
    return new ApiError(res.status, e.code ?? "ERROR", e.message ?? res.statusText, e.details);
  } catch {
    return new ApiError(res.status, "ERROR", res.statusText || "Error de comunicación.");
  }
}

type Options = {
  method?: string;
  body?: unknown;
  form?: FormData;
  query?: Record<string, string | number | boolean | null | undefined>;
  raw?: boolean;
  retry?: boolean;
};

export async function api<T = unknown>(path: string, opts: Options = {}): Promise<T> {
  const qs = opts.query
    ? "?" +
      Object.entries(opts.query)
        .filter(([, v]) => v !== null && v !== undefined && v !== "")
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join("&")
    : "";
  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(`${API}${path}${qs}`, {
    method: opts.method ?? (body ? "POST" : "GET"),
    headers,
    body,
    credentials: "same-origin",
    cache: "no-store",
  });
  if (res.status === 401 && opts.retry !== false && accessToken) {
    const err = await toError(res.clone());
    if (err.code === "SESSION_ENDED") {
      try {
        await refresh();
        return api<T>(path, { ...opts, retry: false });
      } catch {
        onSessionEnded?.();
        throw err;
      }
    }
  }
  if (!res.ok) {
    const err = await toError(res);
    // Solo una sesión existente "termina"; un login fallido no dispara el cierre.
    if (res.status === 401 && accessToken) onSessionEnded?.();
    throw err;
  }
  if (opts.raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function download(path: string, body: unknown, filename: string) {
  const res = await api<Response>(path, { method: "POST", body, raw: true });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
  return res.headers.get("X-Export-Truncated") === "true";
}

export const fmtDate = (v?: string | null) =>
  v ? new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeStyle: "short" }).format(new Date(v)) : "—";
