"use client";

import { useState } from "react";
import { Badge, Empty, ErrorBox, Field, Json, PageHeader, useAction, useLoad } from "@/components/ui";
import { api, fmtDate } from "@/lib/api";
import { useSession } from "@/lib/session";

type Err = { id: string; ocurrido_en: string; categoria: string; componente: string; tipo: string; severidad: string;
  descripcion: string; diagnostico: unknown; estado_atencion: string; correlation_id: string | null };

export default function ErrorsPage() {
  const { can } = useSession();
  const [estado, setEstado] = useState("ABIERTO");
  const { data, error, reload } = useLoad(() => api<{ items: Err[]; total: number }>("/admin/errors", { query: { estado, page_size: 100 } }), [estado]);
  const act = useAction();
  return (
    <div className="stack">
      <PageHeader title="Registro de errores" subtitle="Errores técnicos y funcionales, separados de la auditoría. No se borran: se atienden." />
      <div className="card form-grid"><Field label="Estado de atención">
        <select value={estado} onChange={(e) => setEstado(e.target.value)}><option value="">Todos</option><option>ABIERTO</option><option>EN_ATENCION</option><option>CERRADO</option></select>
      </Field></div>
      <ErrorBox error={error ?? act.error} />
      <div className="table-wrap"><table>
        <thead><tr><th>Fecha</th><th>Categoría</th><th>Tipo</th><th>Severidad</th><th>Descripción</th><th>Estado</th><th></th></tr></thead>
        <tbody>{data?.items.map((e) => (
          <tr key={e.id}>
            <td className="small">{fmtDate(e.ocurrido_en)}</td><td>{e.categoria}<div className="small muted">{e.componente}</div></td>
            <td className="small">{e.tipo}</td><td><Badge value={e.severidad} /></td>
            <td className="small">{e.descripcion}<details><summary className="muted">diagnóstico</summary><Json value={e.diagnostico} /><div className="mono">{e.correlation_id}</div></details></td>
            <td><Badge value={e.estado_atencion} /></td>
            <td>{can("ADM.ERROR.EDICION") ? (
              <select aria-label="Cambiar estado" value={e.estado_atencion} disabled={act.busy} onChange={(ev) => void act.run(async () => {
                await api(`/admin/errors/${e.id}`, { method: "PATCH", body: { estado_atencion: ev.target.value } }); await reload();
              })}><option>ABIERTO</option><option>EN_ATENCION</option><option>CERRADO</option></select>
            ) : null}</td>
          </tr>
        ))}</tbody>
      </table>{data && data.items.length === 0 ? <Empty /> : null}</div>
    </div>
  );
}
