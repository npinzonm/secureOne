"use client";
// Dashboard posterior al login (REQ-IAM-12/13): solo módulos asignados y activos, en el orden
// global; sin módulos → mensaje informativo (el usuario igual se autentica).

import Link from "next/link";
import { fmtDate } from "@/lib/api";
import { useSession } from "@/lib/session";

const ROUTES: Record<string, string> = { ADM: "/administracion", IND: "/indicium" };

export default function Dashboard() {
  const { me, modules, modulesMessage } = useSession();
  return (
    <main className="content stack">
      <div>
        <h1>Hola, {me?.nombre}</h1>
        <div className="muted small">Último ingreso: {fmtDate(me?.ultimo_ingreso)}</div>
      </div>
      {modulesMessage ? <div className="alert info">{modulesMessage}</div> : null}
      <div className="grid">
        {modules.map((m) => (
          <Link key={m.codigo} href={ROUTES[m.codigo] ?? m.ruta_frontend} className="card"
                style={{ textDecoration: "none", color: "inherit" }}>
            <h3 style={{ marginTop: 0 }}>{m.nombre}</h3>
            <div className="muted small">{m.descripcion}</div>
          </Link>
        ))}
      </div>
      <div className="small">
        <Link href="/cambio-contrasena">Cambiar mi contraseña</Link>
      </div>
    </main>
  );
}
