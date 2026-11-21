"use client";
// Bitácora inmutable: consulta, exportación y verificación (todas auditadas en el backend).

import { Fragment, useState, type FormEvent } from "react";
import { Badge, Empty, ErrorBox, Field, Json, PageHeader, useAction } from "@/components/ui";
import { api, download, fmtDate } from "@/lib/api";
import { useSession } from "@/lib/session";

type Ev = { seq: number; ocurrido_en: string; actor_usuario_red: string | null; actor_tipo: string; categoria: string;
  accion: string; entidad: string | null; entidad_id: string | null; resultado: string; motivo: string | null;
  ip_origen: string | null; valor_anterior: unknown; valor_nuevo: unknown; detalle: unknown };
const FIELDS = ["actor", "categoria", "accion", "modulo", "entidad", "entidad_id", "correlation_id"] as const;

export default function AuditPage() {
  const { can } = useSession();
  const [f, setF] = useState<Record<string, string>>({});
  const [data, setData] = useState<{ items: Ev[]; total: number } | null>(null);
  const [verify, setVerify] = useState<{ integra: boolean; total_eventos: number; primer_seq_invalido: number | null } | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const act = useAction();
  const filters = () => Object.fromEntries(Object.entries(f).filter(([, v]) => v));

  const search = (e?: FormEvent) => {
    e?.preventDefault();
    void act.run(async () => setData(await api("/admin/audit/events", { query: { ...filters(), page_size: 100 } })));
  };
  return (
    <div className="stack">
      <PageHeader title="Auditoría" subtitle="Registro inmutable con cadena de integridad. Cada consulta y exportación queda auditada."
        actions={<>
          <button className="btn" disabled={act.busy} onClick={() => void act.run(async () => setVerify(await api("/admin/audit/verify")))}>Verificar integridad</button>
          {can("ADM.AUDITORIA.EXPORTACION") ? <button className="btn" disabled={act.busy} onClick={() => void act.run(() => download("/admin/audit/events/export", filters(), "secureone-auditoria.xlsx"))}>Exportar</button> : null}
        </>} />
      {verify ? (
        <div className={`alert ${verify.integra ? "ok" : "error"}`}>
          {verify.integra ? `Cadena íntegra: ${verify.total_eventos} eventos.` : `Cadena ALTERADA desde el evento #${verify.primer_seq_invalido}.`}
        </div>
      ) : null}
      <form className="card form-grid" onSubmit={search}>
        {FIELDS.map((k) => (
          <Field key={k} label={k.replace("_", " ")}><input value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></Field>
        ))}
        <Field label="Resultado"><select value={f.resultado ?? ""} onChange={(e) => setF({ ...f, resultado: e.target.value })}>
          <option value="">Todos</option><option>EXITO</option><option>FALLO</option><option>DENEGADO</option></select></Field>
        <Field label="Desde"><input type="datetime-local" value={f.desde ?? ""} onChange={(e) => setF({ ...f, desde: e.target.value })} /></Field>
        <Field label="Hasta"><input type="datetime-local" value={f.hasta ?? ""} onChange={(e) => setF({ ...f, hasta: e.target.value })} /></Field>
        <div style={{ alignSelf: "end" }}><button className="btn primary" disabled={act.busy}>Consultar</button></div>
      </form>
      <ErrorBox error={act.error} />
      {data ? (
        <div className="table-wrap"><table>
          <thead><tr><th>#</th><th>Fecha</th><th>Actor</th><th>Acción</th><th>Entidad</th><th>Resultado</th></tr></thead>
          <tbody>{data.items.map((e) => (
            <Fragment key={e.seq}>
              <tr className="clickable" onClick={() => setOpen(open === e.seq ? null : e.seq)}>
                <td>{e.seq}</td><td className="small">{fmtDate(e.ocurrido_en)}</td>
                <td className="mono">{e.actor_usuario_red ?? e.actor_tipo}</td><td>{e.accion}<div className="small muted">{e.categoria}</div></td>
                <td className="small">{e.entidad ?? "—"}</td><td><Badge value={e.resultado} /></td>
              </tr>
              {open === e.seq ? (
                <tr><td colSpan={6}>
                  <div className="form-grid small">
                    <div><strong>Anterior</strong><Json value={e.valor_anterior} /></div>
                    <div><strong>Nuevo</strong><Json value={e.valor_nuevo} /></div>
                    <div><strong>Detalle</strong><Json value={e.detalle} /></div>
                    <div><strong>Motivo</strong><div>{e.motivo ?? "—"}</div><strong>IP</strong><div className="mono">{e.ip_origen ?? "—"}</div></div>
                  </div>
                </td></tr>
              ) : null}
            </Fragment>
          ))}</tbody>
        </table>{data.items.length === 0 ? <Empty /> : null}<div className="small muted" style={{ padding: ".5rem" }}>{data.total} evento(s)</div></div>
      ) : <div className="muted small">Indique filtros y consulte. La consulta queda registrada en la auditoría.</div>}
    </div>
  );
}
