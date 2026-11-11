"use client";
// Formulario de alta / modificación de usuario. Gerencia filtra áreas (REQ-USER-06).
// Sin campo Empresa (REQ-USER-03).

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Field } from "./ui";

export type Catalogo = { id: string; codigo: string; nombre: string; estado: string };
export type Area = Catalogo & { gerencia_id: string };
export type Cargo = { id: string; codigo_cargo: number; nombre: string; estado: string };

export function useOrg() {
  const [gerencias, setG] = useState<Catalogo[]>([]);
  const [cargos, setC] = useState<Cargo[]>([]);
  const [perfiles, setP] = useState<{ codigo: string; nombre: string; estado: string }[]>([]);
  const [modulos, setM] = useState<{ codigo: string; nombre: string; estado: string }[]>([]);
  useEffect(() => {
    void api<Catalogo[]>("/admin/org/managements", { query: { estado: "ACTIVO" } }).then(setG).catch(() => undefined);
    void api<Cargo[]>("/admin/org/positions", { query: { estado: "ACTIVO" } }).then(setC).catch(() => undefined);
    void api<typeof perfiles>("/admin/profiles").then((p) => setP(p.filter((x) => x.estado === "ACTIVO"))).catch(() => undefined);
    void api<typeof modulos>("/admin/modules").then((m) => setM(m.filter((x) => x.estado === "ACTIVO"))).catch(() => undefined);
  }, []);
  return { gerencias, cargos, perfiles, modulos };
}

export function useAreas(gerenciaId: string) {
  const [areas, setAreas] = useState<Area[]>([]);
  useEffect(() => {
    if (!gerenciaId) {
      setAreas([]);
      return;
    }
    void api<Area[]>("/admin/org/areas", { query: { management_id: gerenciaId, estado: "ACTIVO" } })
      .then(setAreas)
      .catch(() => setAreas([]));
  }, [gerenciaId]);
  return areas;
}

export type UserValues = Record<string, string>;

export function OrgFields({ values, set }: { values: UserValues; set: (k: string, v: string) => void }) {
  const { gerencias, cargos } = useOrg();
  const areas = useAreas(values.gerencia_id ?? "");
  return (
    <>
      <Field label="Gerencia">
        <select value={values.gerencia_id ?? ""} onChange={(e) => { set("gerencia_id", e.target.value); set("area_id", ""); }} required>
          <option value="">— Seleccione —</option>
          {gerencias.map((g) => <option key={g.id} value={g.id}>{g.nombre}</option>)}
        </select>
      </Field>
      <Field label="Área">
        <select value={values.area_id ?? ""} onChange={(e) => set("area_id", e.target.value)} required disabled={!values.gerencia_id}>
          <option value="">— Seleccione —</option>
          {areas.map((a) => <option key={a.id} value={a.id}>{a.nombre}</option>)}
        </select>
      </Field>
      <Field label="Cargo (código)">
        <select value={values.cargo_id ?? ""} onChange={(e) => set("cargo_id", e.target.value)} required>
          <option value="">— Seleccione —</option>
          {cargos.map((c) => <option key={c.id} value={c.id}>{c.codigo_cargo} · {c.nombre}</option>)}
        </select>
      </Field>
      {gerencias.length === 0 ? (
        <div className="alert warn small" style={{ gridColumn: "1 / -1" }}>
          No hay catálogos organizacionales: se cargan solo desde Talento Humano (planta activa).
        </div>
      ) : null}
    </>
  );
}
