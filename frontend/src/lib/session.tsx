"use client";
// Estado de sesión del cliente (DD-07). La fuente de verdad es el servidor:
// - sesión única, 15 min de inactividad, bloqueo, etc. se aplican en el backend.
// - Aquí solo se presenta: perfil propio, módulos y permisos efectivos (para mostrar/ocultar).

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, refresh, setAccessToken, setSessionEndedHandler, type TokenOut } from "./api";

export type Me = {
  usuario_red: string;
  nombre: string;
  primer_apellido: string;
  segundo_apellido: string | null;
  correo: string;
  perfil_codigo: string;
  perfil_nombre: string;
  ultimo_ingreso: string | null;
};
export type Modulo = { codigo: string; nombre: string; descripcion: string | null; ruta_frontend: string; orden: number };

type State = {
  status: "loading" | "anonymous" | "restricted" | "ready";
  me: Me | null;
  modules: Modulo[];
  modulesMessage: string | null;
  permissions: Set<string>;
};

type Ctx = State & {
  login: (usuario: string, password: string) => Promise<TokenOut>;
  logout: () => Promise<void>;
  reload: () => Promise<void>;
  can: (perm: string) => boolean;
  endSession: (msg?: string) => void;
  notice: string | null;
  clearNotice: () => void;
};

const SessionContext = createContext<Ctx | null>(null);
const EMPTY: State = { status: "loading", me: null, modules: [], modulesMessage: null, permissions: new Set() };

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>(EMPTY);
  const [notice, setNotice] = useState<string | null>(null);
  const router = useRouter();

  const load = useCallback(async () => {
    const [me, mods, perms] = await Promise.all([
      api<Me>("/me"),
      api<{ modulos: Modulo[]; mensaje: string | null }>("/me/modules"),
      api<string[]>("/me/permissions"),
    ]);
    setState({ status: "ready", me, modules: mods.modulos, modulesMessage: mods.mensaje, permissions: new Set(perms) });
  }, []);

  const endSession = useCallback(
    (msg = "Su sesión finalizó. Inicie sesión nuevamente.") => {
      setAccessToken(null);
      setState({ ...EMPTY, status: "anonymous" });
      setNotice(msg);
      router.replace("/login");
    },
    [router],
  );

  useEffect(() => {
    setSessionEndedHandler(() => endSession());
    // Recarga de página: el token en memoria se perdió; se intenta renovar con la cookie.
    refresh()
      .then(() => load())
      .catch(() => setState({ ...EMPTY, status: "anonymous" }));
  }, [endSession, load]);

  const login = useCallback(
    async (usuario: string, password: string) => {
      const t = await api<TokenOut>("/auth/login", { body: { usuario_red: usuario, password }, retry: false });
      setAccessToken(t.access_token, t.expires_in);
      setNotice(null);
      if (t.debe_cambiar_contrasena) setState({ ...EMPTY, status: "restricted" });
      else await load();
      return t;
    },
    [load],
  );

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST", retry: false });
    } catch {
      /* la sesión puede haber expirado ya */
    }
    setAccessToken(null);
    setState({ ...EMPTY, status: "anonymous" });
    router.replace("/login");
  }, [router]);

  const value = useMemo<Ctx>(
    () => ({
      ...state,
      login,
      logout,
      reload: load,
      can: (p: string) => state.permissions.has(p),
      endSession,
      notice,
      clearNotice: () => setNotice(null),
    }),
    [state, login, logout, load, endSession, notice],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("SessionProvider ausente");
  return ctx;
}
