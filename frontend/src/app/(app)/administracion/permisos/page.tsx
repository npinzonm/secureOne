"use client";

import { useState } from "react";
import { CatalogCreate } from "@/components/CatalogCreate";
import { ImpactConfirm } from "@/components/Impact";
import { Badge, ErrorBox, PageHeader, useLoad } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

type Permiso = { id: string; codigo: string; nombre: string; modulo: string; categoria: string; estado: string; es_sistema: boolean };

export default function PermissionsPage() {
  const { can } = useSession();
  const { data, error, reload } = useLoad(() => api<Permiso[]>("/admin/permissions"), []);
  const [create, setCreate] = useState(false);
  const [toggle, setToggle] = useState<Permiso | null>(null);
  return (
    <div className="stack">
      <PageHeader title="Permisos" subtitle="Cada permiso pertenece a un módulo y tiene una categoría (código MÓDULO.RECURSO.CATEGORÍA)."
        actions={can("ADM.PERMISO.CREACION") ? <button className="btn primary" onClick={() => setCreate(true)}>Nuevo permiso</button> : null} />
      <ErrorBox error={error} />
      <div className="table-wrap"><table>
        <thead><tr><th>Código</th><th>Nombre</th><th>Módulo</th><th>Categoría</th><th>Estado</th><th></th></tr></thead>
        <tbody>{data?.map((p) => (
          <tr key={p.id}>
            <td className="mono">{p.codigo}</td><td>{p.nombre}</td><td>{p.modulo}</td><td>{p.categoria}</td><td><Badge value={p.estado} /></td>
            <td>{!p.es_sistema && can("ADM.PERMISO.ELIMINACION") ? (
              <button className="btn sm" onClick={() => setToggle(p)}>{p.estado === "ACTIVO" ? "Inactivar" : "Activar"}</button>
            ) : p.es_sistema ? <span className="badge accent">sistema</span> : null}</td>
          </tr>
        ))}</tbody>
      </table></div>
      {create ? (
        <CatalogCreate title="Nuevo permiso" path="/admin/permissions" onClose={() => setCreate(false)} onDone={() => { setCreate(false); void reload(); }}
          fields={[{ key: "codigo", label: "Código", hint: "p. ej. IND.INDICADOR.CONSULTA", required: true },
                   { key: "nombre", label: "Nombre", required: true }, { key: "descripcion", label: "Descripción" }]} />
      ) : null}
      {toggle ? (
        <ImpactConfirm title={`${toggle.estado === "ACTIVO" ? "Inactivar" : "Activar"} ${toggle.codigo}`}
          impactPath={`/admin/permissions/${toggle.id}/status/impact`} applyPath={`/admin/permissions/${toggle.id}/status`}
          applyMethod="POST" body={{ estado: toggle.estado === "ACTIVO" ? "INACTIVO" : "ACTIVO" }}
          onClose={() => setToggle(null)} onDone={() => { setToggle(null); void reload(); }} />
      ) : null}
    </div>
  );
}
