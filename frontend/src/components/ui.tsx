"use client";
// Componentes mínimos reutilizables (DD-07): sin librerías de UI.

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ApiError } from "@/lib/api";

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const e = error as ApiError;
  const details = e?.details as Record<string, unknown> | undefined;
  return (
    <div className="alert error" role="alert">
      {e?.message ?? "Error"}
      {details ? <pre className="json small">{JSON.stringify(details, null, 2)}</pre> : null}
    </div>
  );
}

export function Badge({ value }: { value?: string | null }) {
  const v = value ?? "—";
  const tone =
    ["ACTIVO", "APROBADA", "ENVIADA", "COMPLETADA", "OK", "EXITO", "CERRADO"].includes(v) ? "ok"
    : ["INACTIVO", "RECHAZADA", "FALLIDA", "AGOTADA", "ERROR", "DENEGADO", "FALLO", "RECHAZADA"].includes(v) ? "danger"
    : ["PENDIENTE", "PENDIENTE_ALTA", "PARCIAL", "OMITIDA", "ABIERTA", "EN_ATENCION", "ABIERTO", "SUPERADA"].includes(v) ? "warn"
    : "";
  return <span className={`badge ${tone}`}>{v.replaceAll("_", " ")}</span>;
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="modal-back" role="dialog" aria-modal="true" aria-label={title} onMouseDown={onClose}>
      <div className="modal" onMouseDown={(e) => e.stopPropagation()}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

/** Diálogo para secretos mostrados una sola vez (contraseñas temporales). Nunca se persisten. */
export function SecretDialog({ secret, onClose }: { secret: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <Modal title="Contraseña temporal" onClose={onClose}>
      <div className="stack">
        <div className="alert warn">
          Se muestra <strong>una sola vez</strong>. Entréguela por un canal seguro; el usuario deberá cambiarla
          en su primer inicio de sesión.
        </div>
        <div className="card mono" style={{ fontSize: "1.1rem", textAlign: "center" }}>{secret}</div>
        <div className="row">
          <button
            className="btn"
            onClick={() => navigator.clipboard?.writeText(secret).then(() => setCopied(true))}
          >
            {copied ? "Copiada" : "Copiar"}
          </button>
          <span className="spacer" />
          <button className="btn primary" onClick={onClose}>Entendido</button>
        </div>
      </div>
    </Modal>
  );
}

export function Field(props: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="field">
      <span>{props.label}</span>
      {props.children}
      {props.hint ? <small className="muted">{props.hint}</small> : null}
    </label>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle ? <div className="muted small">{subtitle}</div> : null}
      </div>
      <div className="row">{actions}</div>
    </div>
  );
}

export function Empty({ children = "Sin resultados." }: { children?: ReactNode }) {
  return <div className="muted" style={{ padding: "1rem" }}>{children}</div>;
}

/** Carga de datos con estado de error y recarga. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fn());
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { data, error, loading, reload, setData };
}

/** Ejecuta una acción y expone su error/estado. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e);
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, run, setError };
}

export function Json({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  return <pre className="json">{typeof value === "string" ? value : JSON.stringify(value, null, 2)}</pre>;
}
