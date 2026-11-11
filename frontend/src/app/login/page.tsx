"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { ErrorBox, Field } from "@/components/ui";
import { useSession } from "@/lib/session";

export default function LoginPage() {
  const { login, status, notice, clearNotice } = useSession();
  const router = useRouter();
  const [usuario, setUsuario] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (status === "ready") router.replace("/");
    if (status === "restricted") router.replace("/cambio-contrasena");
  }, [status, router]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    clearNotice();
    try {
      await login(usuario.trim(), password);
    } catch (err) {
      setError(err);
    } finally {
      setPassword(""); // nunca se conserva la contraseña en el estado
      setBusy(false);
    }
  };

  return (
    <main className="center-page">
      <form className="card auth-card stack" onSubmit={submit} aria-label="Inicio de sesión">
        <div>
          <h1>Secure<span style={{ color: "var(--accent)" }}>One</span></h1>
          <div className="muted small">Seguridad de la Información y Ciberseguridad</div>
        </div>
        {notice ? <div className="alert info">{notice}</div> : null}
        <ErrorBox error={error} />
        <Field label="Usuario de red">
          <input value={usuario} onChange={(e) => setUsuario(e.target.value)} autoComplete="username"
                 required maxLength={16} autoFocus />
        </Field>
        <Field label="Contraseña">
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 autoComplete="current-password" required maxLength={256} />
        </Field>
        <button className="btn primary" disabled={busy} type="submit">
          {busy ? "Ingresando…" : "Ingresar"}
        </button>
      </form>
    </main>
  );
}
