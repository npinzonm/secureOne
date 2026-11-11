"use client";
// Cambio de contraseña (obligatorio con temporal o voluntario). Tras cambiarla el servidor
// cierra la sesión (decisión PROPUESTA de la Fase 3) y se vuelve a iniciar sesión.

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { ErrorBox, Field } from "@/components/ui";
import { api, setAccessToken } from "@/lib/api";
import { useSession } from "@/lib/session";

const RULES = [
  "Mínimo 12 caracteres",
  "Al menos una mayúscula, una minúscula, un número y un carácter especial",
  "No puede contener su usuario de red",
  "No puede repetir ninguna de sus últimas 5 contraseñas",
];

export default function ChangePasswordPage() {
  const { status } = useSession();
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (status === "anonymous" && !done) router.replace("/login");
  }, [status, router, done]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (next !== confirm) {
      setError({ message: "La confirmación no coincide con la nueva contraseña." });
      return;
    }
    try {
      await api("/auth/password/change", {
        body: { current_password: current, new_password: next },
        retry: false,
      });
      setAccessToken(null);
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setCurrent("");
      setNext("");
      setConfirm("");
    }
  };

  if (done) {
    return (
      <main className="center-page">
        <div className="card auth-card stack">
          <div className="alert ok">Contraseña actualizada. Inicie sesión con su nueva contraseña.</div>
          <button className="btn primary" onClick={() => window.location.assign("/login")}>
            Ir al inicio de sesión
          </button>
        </div>
      </main>
    );
  }
  return (
    <main className="center-page">
      <form className="card auth-card stack" onSubmit={submit}>
        <h1>Cambiar contraseña</h1>
        {status === "restricted" ? (
          <div className="alert warn">Debe establecer una nueva contraseña para continuar.</div>
        ) : null}
        <ul className="small muted">{RULES.map((r) => <li key={r}>{r}</li>)}</ul>
        <ErrorBox error={error} />
        <Field label="Contraseña actual">
          <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)}
                 autoComplete="current-password" required />
        </Field>
        <Field label="Nueva contraseña">
          <input type="password" value={next} onChange={(e) => setNext(e.target.value)}
                 autoComplete="new-password" required minLength={12} />
        </Field>
        <Field label="Confirmar nueva contraseña">
          <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)}
                 autoComplete="new-password" required minLength={12} />
        </Field>
        <button className="btn primary" type="submit">Cambiar contraseña</button>
      </form>
    </main>
  );
}
