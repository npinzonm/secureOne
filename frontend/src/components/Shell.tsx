"use client";
// Estructura de la aplicación autenticada: barra superior, campana, aviso de inactividad y
// protección de rutas (solo presentación; el backend autoriza cada operación).

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Modal } from "./ui";

const WARN_SECONDS = 60; // DD-07: aviso 60 s antes del cierre por inactividad

function IdleWarning() {
  const { endSession, logout } = useSession();
  const [remaining, setRemaining] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        // /auth/session NO extiende la sesión (touch=False en el backend).
        const s = await api<{ segundos_restantes_inactividad: number }>("/auth/session");
        if (alive) setRemaining(s.segundos_restantes_inactividad);
      } catch {
        /* el manejador global cierra la sesión si ya terminó */
      }
    };
    void poll();
    const id = setInterval(poll, 20_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (remaining === null || remaining > WARN_SECONDS) return;
    if (remaining <= 0) {
      endSession("Su sesión se cerró por 15 minutos de inactividad.");
      return;
    }
    const id = setTimeout(() => setRemaining((r) => (r === null ? r : r - 1)), 1000);
    return () => clearTimeout(id);
  }, [remaining, endSession]);

  if (remaining === null || remaining > WARN_SECONDS) return null;
  return (
    <Modal title="¿Sigue ahí?" onClose={() => undefined}>
      <p>Su sesión se cerrará por inactividad en <strong>{remaining}</strong> segundos.</p>
      <div className="row">
        <button className="btn" onClick={() => void logout()}>Cerrar sesión</button>
        <span className="spacer" />
        <button
          className="btn primary"
          onClick={async () => {
            await api("/me"); // una petición real sí cuenta como actividad
            setRemaining(15 * 60);
          }}
        >
          Seguir conectado
        </button>
      </div>
    </Modal>
  );
}

function Bell() {
  const [count, setCount] = useState(0);
  useEffect(() => {
    const load = () =>
      api<{ no_leidas: number }>("/notifications/count")
        .then((r) => setCount(r.no_leidas))
        .catch(() => undefined);
    void load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);
  return (
    <Link href="/notificaciones" className="btn sm bell" aria-label={`Notificaciones: ${count} sin leer`}>
      🔔{count > 0 ? <span className="count">{count}</span> : null}
    </Link>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { status, me, logout } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
    if (status === "restricted") router.replace("/cambio-contrasena");
  }, [status, router]);

  if (status !== "ready" || !me) {
    return <div className="center-page muted">Cargando…</div>;
  }
  return (
    <>
      <header className="topbar">
        <Link href="/" className="brand">Secure<span>One</span></Link>
        <span className="spacer" />
        <Bell />
        <span className="small muted">
          {me.nombre} {me.primer_apellido} · {me.perfil_nombre}
        </span>
        <button className="btn sm" onClick={() => void logout()}>Salir</button>
      </header>
      <IdleWarning />
      {children}
    </>
  );
}

const ADMIN_NAV: { href: string; label: string; perm: string }[] = [
  { href: "/administracion/usuarios", label: "Usuarios", perm: "ADM.USUARIO.CONSULTA" },
  { href: "/administracion/solicitudes", label: "Solicitudes", perm: "ADM.SOLICITUD.CONSULTA" },
  { href: "/administracion/perfiles", label: "Perfiles", perm: "ADM.PERFIL.CONSULTA" },
  { href: "/administracion/roles", label: "Roles", perm: "ADM.ROL.CONSULTA" },
  { href: "/administracion/permisos", label: "Permisos", perm: "ADM.PERMISO.CONSULTA" },
  { href: "/administracion/modulos", label: "Módulos", perm: "ADM.MODULO.CONSULTA" },
  { href: "/administracion/dominios", label: "Dominios", perm: "ADM.DOMINIO.CONSULTA" },
  { href: "/administracion/talento-humano", label: "Talento Humano", perm: "ADM.TH.CONSULTA" },
  { href: "/administracion/auditoria", label: "Auditoría", perm: "ADM.AUDITORIA.CONSULTA" },
  { href: "/administracion/errores", label: "Errores", perm: "ADM.ERROR.CONSULTA" },
  { href: "/administracion/entregas", label: "Entregas de notificaciones", perm: "ADM.NOTIFICACION.CONSULTA" },
  { href: "/administracion/parametros", label: "Parámetros", perm: "ADM.PARAMETRO.CONSULTA" },
];

export function AdminLayout({ children }: { children: ReactNode }) {
  const { can, modules } = useSession();
  const path = usePathname();
  if (!modules.some((m) => m.codigo === "ADM")) {
    return <div className="content"><div className="alert error">No tiene asignado el módulo de Administración.</div></div>;
  }
  return (
    <div className="layout">
      <nav className="sidebar" aria-label="Administración">
        {ADMIN_NAV.filter((n) => can(n.perm)).map((n) => (
          <Link key={n.href} href={n.href} className={path.startsWith(n.href) ? "active" : ""}>
            {n.label}
          </Link>
        ))}
      </nav>
      <main className="content">{children}</main>
    </div>
  );
}
