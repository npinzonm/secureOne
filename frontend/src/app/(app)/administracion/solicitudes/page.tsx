"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Empty, ErrorBox, Field, PageHeader, useLoad } from "@/components/ui";
import { api, fmtDate } from "@/lib/api";

type S = { id: string; numero: number; tipo: string; origen: string; estado: string; creada_en: string;
  solicitante: string | null; usuario_objetivo: string | null };

export default function RequestsPage() {
  const router = useRouter();
  const [estado, setEstado] = useState("PENDIENTE");
  const [origen, setOrigen] = useState("");
  const { data, error } = useLoad(
    () => api<{ items: S[]; total: number }>("/admin/requests", { query: { estado, origen, page_size: 100 } }),
    [estado, origen]);
  return (
    <div className="stack">
      <PageHeader title="Solicitudes"
        subtitle="Una sola aprobación; cualquiera de los administradores puede aprobar, incluido el solicitante." />
      <div className="card form-grid">
        <Field label="Estado">
          <select value={estado} onChange={(e) => setEstado(e.target.value)}>
            <option value="">Todos</option>
            {["PENDIENTE", "APROBADA", "RECHAZADA", "CANCELADA", "SUPERADA"].map((x) => <option key={x}>{x}</option>)}
          </select>
        </Field>
        <Field label="Origen">
          <select value={origen} onChange={(e) => setOrigen(e.target.value)}>
            <option value="">Todos</option><option>MANUAL</option><option>TH</option>
          </select>
        </Field>
      </div>
      <ErrorBox error={error} />
      <div className="table-wrap"><table>
        <thead><tr><th>#</th><th>Tipo</th><th>Usuario</th><th>Origen</th><th>Solicitante</th><th>Creada</th><th>Estado</th></tr></thead>
        <tbody>{data?.items.map((s) => (
          <tr key={s.id} className="clickable" onClick={() => router.push(`/administracion/solicitudes/${s.id}`)}>
            <td>{s.numero}</td><td>{s.tipo.replaceAll("_", " ")}</td><td className="mono">{s.usuario_objetivo ?? "—"}</td>
            <td>{s.origen}</td><td>{s.solicitante ?? "Talento Humano"}</td><td className="small">{fmtDate(s.creada_en)}</td>
            <td><Badge value={s.estado} /></td>
          </tr>
        ))}</tbody>
      </table>{data && data.items.length === 0 ? <Empty /> : null}</div>
    </div>
  );
}
