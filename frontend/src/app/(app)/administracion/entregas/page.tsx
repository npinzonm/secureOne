"use client";

import { useState } from "react";
import { Badge, Empty, ErrorBox, Field, PageHeader, useLoad } from "@/components/ui";
import { api, fmtDate } from "@/lib/api";

type D = { id: string; asunto: string; evento: string; destinatario: string; canal: string; estado: string; intentos: number;
  ultimo_error: string | null; proximo_intento_en: string; enviada_en: string | null; creada_en: string };

export default function DeliveriesPage() {
  const [estado, setEstado] = useState("");
  const [canal, setCanal] = useState("");
  const { data, error } = useLoad(() => api<D[]>("/admin/notifications/deliveries", { query: { estado, canal } }), [estado, canal]);
  return (
    <div className="stack">
      <PageHeader title="Entregas de notificaciones"
        subtitle="Destinatarios obligatorios: administradores activos. Correo con reintentos (1, 5, 15, 60 min)." />
      <div className="card form-grid">
        <Field label="Estado"><select value={estado} onChange={(e) => setEstado(e.target.value)}><option value="">Todos</option><option>PENDIENTE</option><option>ENVIADA</option><option>AGOTADA</option></select></Field>
        <Field label="Canal"><select value={canal} onChange={(e) => setCanal(e.target.value)}><option value="">Todos</option><option>BANDEJA</option><option>CORREO</option></select></Field>
      </div>
      <ErrorBox error={error} />
      <div className="table-wrap"><table>
        <thead><tr><th>Creada</th><th>Asunto</th><th>Destinatario</th><th>Canal</th><th>Estado</th><th>Intentos</th></tr></thead>
        <tbody>{data?.map((d) => (
          <tr key={d.id}><td className="small">{fmtDate(d.creada_en)}</td><td>{d.asunto}<div className="small muted">{d.evento}</div></td>
            <td className="mono">{d.destinatario}</td><td>{d.canal}</td><td><Badge value={d.estado} /></td>
            <td className="small">{d.intentos}{d.ultimo_error ? <div className="muted">{d.ultimo_error}</div> : null}</td></tr>
        ))}</tbody>
      </table>{data && data.length === 0 ? <Empty /> : null}</div>
    </div>
  );
}
