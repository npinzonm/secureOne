"use client";

import { useState } from "react";
import { CatalogCreate } from "@/components/CatalogCreate";
import { Badge, Empty, ErrorBox, PageHeader, useAction, useLoad } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

type Dom = { id: string; codigo: string; nombre: string; descripcion: string | null; modulo: string | null; estado: string };

export default function DomainsPage() {
  const { can } = useSession();
  const { data, error, reload } = useLoad(() => api<Dom[]>("/admin/domains"), []);
  const act = useAction();
  const [create, setCreate] = useState(false);
  return (
    <div className="stack">
      <PageHeader title="Dominios" subtitle="Clasificación informativa: no concede ni restringe acceso."
        actions={can("ADM.DOMINIO.CREACION") ? <button className="btn primary" onClick={() => setCreate(true)}>Nuevo dominio</button> : null} />
      <ErrorBox error={error ?? act.error} />
      <div className="table-wrap"><table>
        <thead><tr><th>Código</th><th>Nombre</th><th>Módulo</th><th>Estado</th><th></th></tr></thead>
        <tbody>{data?.map((d) => (
          <tr key={d.id}><td className="mono">{d.codigo}</td><td>{d.nombre}<div className="small muted">{d.descripcion}</div></td><td>{d.modulo ?? "—"}</td><td><Badge value={d.estado} /></td>
            <td>{can("ADM.DOMINIO.ELIMINACION") ? <button className="btn sm" disabled={act.busy} onClick={() => void act.run(async () => {
              await api(`/admin/domains/${d.id}/status`, { body: { estado: d.estado === "ACTIVO" ? "INACTIVO" : "ACTIVO" } }); await reload();
            })}>{d.estado === "ACTIVO" ? "Inactivar" : "Activar"}</button> : null}</td></tr>
        ))}</tbody>
      </table>{data && data.length === 0 ? <Empty /> : null}</div>
      {create ? (
        <CatalogCreate title="Nuevo dominio" path="/admin/domains" onClose={() => setCreate(false)} onDone={() => { setCreate(false); void reload(); }}
          fields={[{ key: "codigo", label: "Código", required: true }, { key: "nombre", label: "Nombre", required: true },
                   { key: "modulo", label: "Módulo (código, opcional)" }, { key: "descripcion", label: "Descripción" }]} />
      ) : null}
    </div>
  );
}
