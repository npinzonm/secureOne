"use client";
// Integración TH (DD-03/04/05): carga manual, ejecuciones con resultados, propuestas versionadas
// (decisión NORMAL/EXCEPCIONAL de nuevos funcionarios) y alertas.

import { useState, type FormEvent } from "react";
import { useOrg } from "@/components/UserForm";
import { Badge, Empty, ErrorBox, Field, Json, Modal, PageHeader, useAction, useLoad } from "@/components/ui";
import { api, fmtDate } from "@/lib/api";
import { useSession } from "@/lib/session";

type Ex = { id: string; numero: number; tipo: string; nombre_archivo: string; recibido_en: string; cargado_por: string | null;
  estado: string; intentos: number; estadisticas: Record<string, unknown> | null; error: string | null; reproceso_de: number | null;
  archivo_eliminado_en: string | null };
type Prop = { id: string; tipo: string; identificacion: string; estado: string; motivo_cierre: string | null; actualizada_en: string;
  versiones: { version: number; vigente: boolean; contenido: Record<string, string>; ejecucion: number; solicitud: number | null }[] };
type Alert = { id: string; tipo: string; usuario_red: string | null; abierta_en: string; cerrada_en: string | null; ejecucion: number | null };

export default function ThPage() {
  const { can } = useSession();
  const [tab, setTab] = useState<"ejecuciones" | "propuestas" | "alertas">("ejecuciones");
  const ex = useLoad(() => api<Ex[]>("/admin/th/executions"), []);
  const props = useLoad(() => api<Prop[]>("/admin/th/proposals"), []);
  const alerts = useLoad(() => api<Alert[]>("/admin/th/alerts"), []);
  const [rows, setRows] = useState<Ex | null>(null);
  const [decide, setDecide] = useState<Prop | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const reloadAll = () => { void ex.reload(); void props.reload(); void alerts.reload(); };

  return (
    <div className="stack">
      <PageHeader title="Talento Humano" subtitle="Plantas activa (diaria) y de retirados (semanal). Los archivos se eliminan tras procesarse." />
      {can("ADM.TH.CREACION") ? <Upload onDone={(n) => { setMsg(`Ejecución #${n} recibida; se procesará en segundos.`); setTimeout(reloadAll, 3000); }} /> : null}
      {msg ? <div className="alert ok">{msg}</div> : null}
      <div className="row">
        {(["ejecuciones", "propuestas", "alertas"] as const).map((t) => (
          <button key={t} className={`btn sm ${tab === t ? "primary" : ""}`} onClick={() => setTab(t)}>{t[0].toUpperCase() + t.slice(1)}</button>
        ))}
        <span className="spacer" /><button className="btn sm" onClick={reloadAll}>Actualizar</button>
      </div>

      {tab === "ejecuciones" ? (
        <>
          <ErrorBox error={ex.error} />
          <div className="table-wrap"><table>
            <thead><tr><th>#</th><th>Tipo</th><th>Archivo</th><th>Recibido</th><th>Estado</th><th>Resultado</th></tr></thead>
            <tbody>{ex.data?.map((e) => {
              const s = e.estadisticas as Record<string, number> | null;
              return (
                <tr key={e.id} className="clickable" onClick={() => setRows(e)}>
                  <td>{e.numero}{e.reproceso_de ? <div className="small muted">reproceso de #{e.reproceso_de}</div> : null}</td>
                  <td>{e.tipo}</td><td className="small">{e.nombre_archivo}</td><td className="small">{fmtDate(e.recibido_en)}<div className="muted">{e.cargado_por}</div></td>
                  <td><Badge value={e.estado} />{e.intentos ? <div className="small muted">{e.intentos} intento(s)</div> : null}</td>
                  <td className="small">{s ? `${s.ok} OK · ${s.errores} con error · ${s.omitidas} omitidas · ${s.solicitudes} solicitudes` : e.error ?? "—"}</td>
                </tr>
              );
            })}</tbody>
          </table>{ex.data && ex.data.length === 0 ? <Empty /> : null}</div>
        </>
      ) : null}

      {tab === "propuestas" ? (
        <>
          <ErrorBox error={props.error} />
          <div className="table-wrap"><table>
            <thead><tr><th>Tipo</th><th>Identificación</th><th>Versión vigente</th><th>Solicitud</th><th></th></tr></thead>
            <tbody>{props.data?.map((p) => {
              const v = p.versiones.find((x) => x.vigente) ?? p.versiones[0];
              return (
                <tr key={p.id}>
                  <td>{p.tipo.replaceAll("_", " ")}</td><td className="mono">{p.identificacion}</td>
                  <td className="small">v{v?.version} (ejecución #{v?.ejecucion})<Json value={v?.contenido} /></td>
                  <td>{v?.solicitud ? `#${v.solicitud}` : "—"}</td>
                  <td>{p.tipo === "NUEVO_FUNCIONARIO" && can("ADM.USUARIO.CREACION") ? <button className="btn sm primary" onClick={() => setDecide(p)}>Decidir alta</button> : null}</td>
                </tr>
              );
            })}</tbody>
          </table>{props.data && props.data.length === 0 ? <Empty>No hay propuestas abiertas.</Empty> : null}</div>
        </>
      ) : null}

      {tab === "alertas" ? (
        <>
          <ErrorBox error={alerts.error} />
          <div className="table-wrap"><table>
            <thead><tr><th>Tipo</th><th>Usuario</th><th>Abierta</th><th>Ejecución</th></tr></thead>
            <tbody>{alerts.data?.map((a) => (
              <tr key={a.id}><td><Badge value={a.tipo} /></td><td className="mono">{a.usuario_red ?? "—"}</td><td>{fmtDate(a.abierta_en)}</td><td>{a.ejecucion ? `#${a.ejecucion}` : "—"}</td></tr>
            ))}</tbody>
          </table>{alerts.data && alerts.data.length === 0 ? <Empty>No hay alertas abiertas.</Empty> : null}</div>
        </>
      ) : null}

      {rows ? <RowsModal ex={rows} onClose={() => setRows(null)} /> : null}
      {decide ? <DecideModal prop={decide} onClose={() => setDecide(null)} onDone={(n) => { setDecide(null); setMsg(`Solicitud de alta #${n} creada.`); reloadAll(); }} /> : null}
    </div>
  );
}

function Upload({ onDone }: { onDone: (numero: number) => void }) {
  const [tipo, setTipo] = useState("ACTIVA");
  const [file, setFile] = useState<File | null>(null);
  const act = useAction();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append("tipo", tipo);
    form.append("archivo", file);
    void act.run(async () => {
      const r = await api<{ numero: number }>("/admin/th/files", { method: "POST", form });
      setFile(null);
      (e.target as HTMLFormElement).reset();
      onDone(r.numero);
    });
  };
  return (
    <form className="card form-grid" onSubmit={submit}>
      <Field label="Tipo de planta">
        <select value={tipo} onChange={(e) => setTipo(e.target.value)}><option value="ACTIVA">Activa (diaria)</option><option value="RETIRADOS">Retirados (semanal)</option></select>
      </Field>
      <Field label="Archivo .xlsx (máx. 10 MB, sin macros)">
        <input type="file" accept=".xlsx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
      </Field>
      <div style={{ alignSelf: "end" }}><button className="btn primary" disabled={act.busy || !file}>Cargar</button></div>
      <div style={{ gridColumn: "1 / -1" }}><ErrorBox error={act.error} /></div>
    </form>
  );
}

function RowsModal({ ex, onClose }: { ex: Ex; onClose: () => void }) {
  const { data, error } = useLoad(() => api<{ fila: number; identificacion: string | null; resultado: string; accion: string | null; detalle: unknown }[]>(
    `/admin/th/executions/${ex.id}/rows`), [ex.id]);
  return (
    <Modal title={`Ejecución #${ex.numero} · ${ex.tipo}`} onClose={onClose}>
      <ErrorBox error={error} />
      {ex.error ? <div className="alert error">{ex.error}</div> : null}
      <Json value={ex.estadisticas} />
      <div className="table-wrap" style={{ marginTop: ".75rem" }}><table>
        <thead><tr><th>Fila</th><th>Identificación</th><th>Resultado</th><th>Acción / detalle</th></tr></thead>
        <tbody>{data?.map((r) => (
          <tr key={r.fila}><td>{r.fila}</td><td className="mono">{r.identificacion ?? "—"}</td><td><Badge value={r.resultado} /></td>
            <td className="small">{r.accion}<Json value={r.detalle} /></td></tr>
        ))}</tbody>
      </table></div>
    </Modal>
  );
}

function DecideModal({ prop, onClose, onDone }: { prop: Prop; onClose: () => void; onDone: (n: number) => void }) {
  const { perfiles, modulos } = useOrg();
  const v = prop.versiones.find((x) => x.vigente)?.contenido ?? {};
  const [form, setForm] = useState<Record<string, string>>({ tipo_alta: "NORMAL", usuario_red: v.usuario_red ?? "", correo: v.correo ?? "" });
  const [mods, setMods] = useState<string[]>([]);
  const act = useAction();
  const set = (k: string, val: string) => setForm((f) => ({ ...f, [k]: val }));
  return (
    <Modal title={`Nuevo funcionario ${prop.identificacion}`} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); void act.run(async () => {
        const r = await api<{ numero: number }>(`/admin/th/proposals/${prop.id}/decide`, { body: { ...form, motivo: form.motivo || null, modulos: mods } });
        onDone(r.numero);
      }); }}>
        <ErrorBox error={act.error} />
        <div className="small">{v.nombres} {v.primer_apellido} · {v.codigo_gerencia} / {v.codigo_area} / cargo {v.codigo_cargo}</div>
        <div className="form-grid">
          <Field label="Tipo de alta"><select value={form.tipo_alta} onChange={(e) => set("tipo_alta", e.target.value)}><option>NORMAL</option><option>EXCEPCIONAL</option></select></Field>
          <Field label="Perfil"><select value={form.perfil ?? ""} onChange={(e) => set("perfil", e.target.value)} required>
            <option value="">—</option>{perfiles.map((p) => <option key={p.codigo} value={p.codigo}>{p.nombre}</option>)}</select></Field>
          <Field label="Usuario de red"><input value={form.usuario_red} onChange={(e) => set("usuario_red", e.target.value)} required /></Field>
          <Field label="Correo"><input type="email" value={form.correo} onChange={(e) => set("correo", e.target.value)} required /></Field>
        </div>
        <div className="row">{modulos.map((m) => (
          <label key={m.codigo} className="row small"><input type="checkbox" style={{ width: "auto" }} checked={mods.includes(m.codigo)}
            onChange={(e) => setMods(e.target.checked ? [...mods, m.codigo] : mods.filter((x) => x !== m.codigo))} />{m.nombre}</label>
        ))}</div>
        <Field label="Motivo (obligatorio si es EXCEPCIONAL)"><textarea value={form.motivo ?? ""} onChange={(e) => set("motivo", e.target.value)} /></Field>
        <div className="row"><span className="spacer" /><button type="button" className="btn" onClick={onClose}>Cancelar</button>
          <button className="btn primary" disabled={act.busy}>Crear solicitud de alta</button></div>
      </form>
    </Modal>
  );
}
