"use client";

import { Empty, ErrorBox, PageHeader, useLoad } from "@/components/ui";
import { api, fmtDate } from "@/lib/api";

type Item = { id: string; asunto: string; cuerpo: string; evento: string; recibida_en: string; leida: boolean };

export default function InboxPage() {
  const { data, error, reload } = useLoad(
    () => api<{ items: Item[]; no_leidas: number }>("/notifications"), []);
  const read = async (id: string) => {
    await api(`/notifications/${id}/read`, { method: "POST" });
    await reload();
  };
  return (
    <main className="content stack">
      <PageHeader title="Notificaciones" subtitle={data ? `${data.no_leidas} sin leer` : undefined} />
      <ErrorBox error={error} />
      {data && data.items.length === 0 ? <Empty>No tiene notificaciones.</Empty> : null}
      {data?.items.map((n) => (
        <div key={n.id} className="card" style={{ opacity: n.leida ? 0.7 : 1 }}>
          <div className="row">
            <strong>{n.asunto}</strong>
            <span className="spacer" />
            <span className="small muted">{fmtDate(n.recibida_en)}</span>
          </div>
          <p style={{ margin: ".5rem 0" }}>{n.cuerpo}</p>
          {!n.leida ? <button className="btn sm" onClick={() => void read(n.id)}>Marcar como leída</button> : null}
        </div>
      ))}
    </main>
  );
}
