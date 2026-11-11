"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Badge, ErrorBox, Field, Json, Modal, PageHeader, SecretDialog, useAction, useLoad } from "@/components/ui";
import { api, fmtDate } from "@/lib/api";
import { useSession } from "@/lib/session";

type Detail = {
  id: string; numero: number; tipo: string; origen: string; entidad_id: string; estado: string; motivo: string | null;
  creada_en: string; resuelta_en: string | null; motivo_resolucion: string | null; solicitante: string | null;
  resuelta_por: string | null; usuario_objetivo: string | null;
  items: { atributo: string; valor_anterior: unknown; valor_nuevo: unknown }[];
};

export default function RequestDetail() {
  const { id } = useParams<{ id: string }>();
  const { can } = useSession();
  const { data, error, reload } = useLoad(() => api<Detail>(`/admin/requests/${id}`), [id]);
  const act = useAction();
  const [secret, setSecret] = useState<string | null>(null);
  const [resolve, setResolve] = useState<null | "reject" | "cancel">(null);
  const [motivo, setMotivo] = useState("");

  const approve = () => void act.run(async () => {
    const r = await api<{ contrasena_temporal: string | null }>(`/admin/requests/${id}/approve`, { method: "POST" });
    if (r.contrasena_temporal) setSecret(r.contrasena_temporal);
    await reload();
  });

  return (
    <div className="stack">
      <Link href="/administracion/solicitudes" className="small">← Solicitudes</Link>
      <ErrorBox error={error} />
      {data ? (
        <>
          <PageHeader title={`Solicitud #${data.numero}`} subtitle={`${data.tipo.replaceAll("_", " ")} · origen ${data.origen}`}
                      actions={<Badge value={data.estado} />} />
          <ErrorBox error={act.error} />
          <div className="card">
            <dl className="kv">
              <dt>Usuario</dt><dd><Link href={`/administracion/usuarios/${data.entidad_id}`} className="mono">{data.usuario_objetivo ?? data.entidad_id}</Link></dd>
              <dt>Solicitante</dt><dd>{data.solicitante ?? "Talento Humano"} · {fmtDate(data.creada_en)}</dd>
              <dt>Motivo</dt><dd>{data.motivo ?? "—"}</dd>
              {data.resuelta_en ? (<><dt>Resolución</dt><dd>{data.resuelta_por ?? "sistema"} · {fmtDate(data.resuelta_en)}<div className="small muted">{data.motivo_resolucion}</div></dd></>) : null}
            </dl>
          </div>
          <div className="table-wrap"><table>
            <thead><tr><th>Atributo</th><th>Valor anterior</th><th>Valor nuevo</th></tr></thead>
            <tbody>{data.items.map((i) => (
              <tr key={i.atributo}><td>{i.atributo}</td><td><Json value={i.valor_anterior} /></td><td><Json value={i.valor_nuevo} /></td></tr>
            ))}</tbody>
          </table></div>
          {data.estado === "PENDIENTE" ? (
            <div className="row">
              {can("ADM.SOLICITUD.CREACION") ? <button className="btn" onClick={() => setResolve("cancel")}>Cancelar</button> : null}
              <span className="spacer" />
              {can("ADM.SOLICITUD.APROBACION") ? (
                <>
                  <button className="btn danger" onClick={() => setResolve("reject")}>Rechazar</button>
                  <button className="btn primary" disabled={act.busy} onClick={approve}>Aprobar y aplicar</button>
                </>
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}
      {resolve ? (
        <Modal title={resolve === "reject" ? "Rechazar solicitud" : "Cancelar solicitud"} onClose={() => setResolve(null)}>
          <form className="stack" onSubmit={(e) => { e.preventDefault(); void act.run(async () => {
            await api(`/admin/requests/${id}/${resolve}`, { body: { motivo } });
            setResolve(null); setMotivo(""); await reload();
          }); }}>
            <ErrorBox error={act.error} />
            {resolve === "cancel" ? <div className="alert info small">Para corregir, cancele y cree una nueva solicitud vinculada.</div> : null}
            <Field label="Motivo (mín. 10 caracteres)"><textarea value={motivo} onChange={(e) => setMotivo(e.target.value)} required minLength={10} /></Field>
            <div className="row"><span className="spacer" /><button type="button" className="btn" onClick={() => setResolve(null)}>Volver</button>
              <button className="btn primary" disabled={act.busy}>Confirmar</button></div>
          </form>
        </Modal>
      ) : null}
      {secret ? <SecretDialog secret={secret} onClose={() => setSecret(null)} /> : null}
    </div>
  );
}
