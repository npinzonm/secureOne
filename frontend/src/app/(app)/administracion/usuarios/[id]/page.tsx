"use client";
// Ficha de usuario (consulta auditada), actividad, historial y acciones según la matriz PD-05:
// directas (temporal, revocar sesión) y con aprobación (modificar, módulos, inhabilitar, reactivar).

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { OrgFields, useOrg, type UserValues } from "@/components/UserForm";
import { ReasonModal } from "@/components/ReasonModal";
import { Badge, ErrorBox, Field, Json, Modal, PageHeader, SecretDialog, useAction, useLoad } from "@/components/ui";
import { api, fmtDate } from "@/lib/api";
import { useSession } from "@/lib/session";

type Detail = Record<string, string | number | null> & { modulos: string[] };
type Activity = {
  ultimo_ingreso: string | null; ultima_actividad: string | null; intentos_fallidos: number;
  bloqueado_hasta: string | null; sesion_activa: boolean;
  sesiones: { iniciada_en: string; finalizada_en: string | null; motivo_fin: string | null; ip: string | null }[];
};
type History = {
  solicitudes: { numero: number; tipo: string; estado: string; creada_en: string; solicitante: string | null;
    resuelta_por: string | null; motivo: string | null; motivo_resolucion: string | null; solicitud_vinculada: number | null;
    items: { atributo: string; valor_anterior: unknown; valor_nuevo: unknown }[] }[];
  estados: { estado_anterior: string | null; estado_nuevo: string; motivo: string; actor: string | null; ocurrido_en: string }[];
};

export default function UserDetail() {
  const { id } = useParams<{ id: string }>();
  const { can } = useSession();
  const user = useLoad(() => api<Detail>(`/admin/users/${id}`), [id]);
  const act = useLoad(() => api<Activity>(`/admin/users/${id}/activity`), [id]);
  const hist = useLoad(() => api<History>(`/admin/users/${id}/history`), [id]);
  const action = useAction();
  const [modal, setModal] = useState<null | "edit" | "modules" | "deactivate" | "reactivate">(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const u = user.data;

  const refreshAll = () => { void user.reload(); void act.reload(); void hist.reload(); };
  const requestDone = (n: number) => { setModal(null); setMsg(`Solicitud #${n} creada; queda pendiente de aprobación.`); refreshAll(); };

  return (
    <div className="stack">
      <Link href="/administracion/usuarios" className="small">← Usuarios</Link>
      <ErrorBox error={user.error} />
      {u ? (
        <>
          <PageHeader
            title={`${u.nombre} ${u.primer_apellido} ${u.segundo_apellido ?? ""}`}
            subtitle={`${u.usuario_red} · ${u.perfil_nombre}`}
            actions={<Badge value={String(u.estado)} />}
          />
          {msg ? <div className="alert ok">{msg}</div> : null}
          <ErrorBox error={action.error} />
          <div className="row">
            {can("ADM.USUARIO.EDICION") && u.estado === "ACTIVO" ? (
              <>
                <button className="btn" onClick={() => setModal("edit")}>Modificar datos</button>
                <button className="btn" onClick={() => setModal("modules")}>Módulos</button>
                <button className="btn" disabled={action.busy} onClick={() => void action.run(async () => {
                  const r = await api<{ contrasena_temporal: string }>(`/admin/users/${id}/password-reset`, { method: "POST" });
                  setSecret(r.contrasena_temporal);
                  refreshAll();
                })}>Generar contraseña temporal</button>
                <button className="btn" disabled={action.busy} onClick={() => void action.run(async () => {
                  const r = await api<{ revocada: boolean }>(`/admin/users/${id}/sessions/revoke`, { method: "POST" });
                  setMsg(r.revocada ? "Sesión revocada." : "El usuario no tenía una sesión activa.");
                  refreshAll();
                })}>Revocar sesión</button>
              </>
            ) : null}
            {can("ADM.USUARIO.ELIMINACION") && u.estado === "ACTIVO" ? (
              <button className="btn danger" onClick={() => setModal("deactivate")}>Inhabilitar</button>
            ) : null}
            {can("ADM.USUARIO.EDICION") && u.estado === "INACTIVO" ? (
              <button className="btn" onClick={() => setModal("reactivate")}>Reactivar</button>
            ) : null}
          </div>
          <div className="card">
            <dl className="kv">
              <dt>Identificación</dt><dd>{u.identificacion}</dd>
              <dt>Correo</dt><dd>{u.correo}</dd>
              <dt>Gerencia / Área</dt><dd>{u.gerencia ?? "—"} / {u.area ?? "—"}</dd>
              <dt>Cargo</dt><dd>{u.codigo_cargo ? `${u.codigo_cargo} · ${u.cargo}` : "—"}</dd>
              <dt>Tipo de alta</dt><dd>{u.tipo_alta ?? "—"}</dd>
              <dt>Módulos</dt><dd>{u.modulos.join(", ") || "—"}</dd>
            </dl>
          </div>
        </>
      ) : null}

      <h2>Actividad</h2>
      <ErrorBox error={act.error} />
      {act.data ? (
        <div className="card stack">
          <dl className="kv">
            <dt>Último ingreso</dt><dd>{fmtDate(act.data.ultimo_ingreso)}</dd>
            <dt>Última actividad</dt><dd>{fmtDate(act.data.ultima_actividad)}</dd>
            <dt>Intentos fallidos</dt><dd>{act.data.intentos_fallidos}</dd>
            <dt>Bloqueado hasta</dt><dd>{fmtDate(act.data.bloqueado_hasta)}</dd>
            <dt>Sesión activa</dt><dd>{act.data.sesion_activa ? "Sí" : "No"}</dd>
          </dl>
          <div className="table-wrap"><table>
            <thead><tr><th>Inicio</th><th>Fin</th><th>Motivo</th><th>IP</th></tr></thead>
            <tbody>{act.data.sesiones.map((s, i) => (
              <tr key={i}><td>{fmtDate(s.iniciada_en)}</td><td>{fmtDate(s.finalizada_en)}</td><td>{s.motivo_fin ?? "Abierta"}</td><td className="mono">{s.ip ?? "—"}</td></tr>
            ))}</tbody>
          </table></div>
        </div>
      ) : null}

      <h2>Historial</h2>
      <ErrorBox error={hist.error} />
      {hist.data?.solicitudes.map((s) => (
        <div key={s.numero} className="card stack">
          <div className="row">
            <Link href={`/administracion/solicitudes?numero=${s.numero}`}><strong>#{s.numero}</strong></Link>
            <span>{s.tipo.replaceAll("_", " ")}</span><Badge value={s.estado} />
            {s.solicitud_vinculada ? <span className="small muted">vinculada a #{s.solicitud_vinculada}</span> : null}
            <span className="spacer" /><span className="small muted">{fmtDate(s.creada_en)} · {s.solicitante ?? "Talento Humano"}</span>
          </div>
          <div className="table-wrap"><table>
            <thead><tr><th>Atributo</th><th>Anterior</th><th>Nuevo</th></tr></thead>
            <tbody>{s.items.map((it) => (
              <tr key={it.atributo}><td>{it.atributo}</td><td><Json value={it.valor_anterior} /></td><td><Json value={it.valor_nuevo} /></td></tr>
            ))}</tbody>
          </table></div>
          {s.motivo_resolucion ? <div className="small muted">Resolución ({s.resuelta_por ?? "sistema"}): {s.motivo_resolucion}</div> : null}
        </div>
      ))}
      {hist.data && hist.data.estados.length > 0 ? (
        <div className="table-wrap"><table>
          <thead><tr><th>Fecha</th><th>Estado</th><th>Motivo</th><th>Actor</th></tr></thead>
          <tbody>{hist.data.estados.map((e, i) => (
            <tr key={i}><td>{fmtDate(e.ocurrido_en)}</td><td>{e.estado_anterior ?? "—"} → {e.estado_nuevo}</td><td>{e.motivo}</td><td>{e.actor ?? "sistema"}</td></tr>
          ))}</tbody>
        </table></div>
      ) : null}

      {modal === "edit" && u ? <EditModal id={id} user={u} onClose={() => setModal(null)} onDone={requestDone} /> : null}
      {modal === "modules" && u ? <ModulesModal id={id} current={u.modulos} onClose={() => setModal(null)} onDone={requestDone} /> : null}
      {modal === "deactivate" || modal === "reactivate" ? (
        <ReasonModal
          title={modal === "deactivate" ? "Solicitar inhabilitación" : "Solicitar reactivación"}
          path={`/admin/users/${id}/${modal}`}
          onClose={() => setModal(null)} onDone={requestDone}
        />
      ) : null}
      {secret ? <SecretDialog secret={secret} onClose={() => setSecret(null)} /> : null}
    </div>
  );
}

function EditModal({ id, user, onClose, onDone }: { id: string; user: Detail; onClose: () => void; onDone: (n: number) => void }) {
  const { perfiles } = useOrg();
  const keys = ["identificacion", "nombre", "primer_apellido", "segundo_apellido", "correo", "gerencia_id", "area_id", "cargo_id"];
  const initial: UserValues = Object.fromEntries(keys.map((k) => [k, String(user[k] ?? "")]));
  initial.perfil = String(user.perfil_codigo ?? "");
  const [v, setV] = useState<UserValues>(initial);
  const act = useAction();
  const set = (k: string, val: string) => setV((p) => ({ ...p, [k]: val }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const changes = Object.fromEntries(Object.entries(v).filter(([k, val]) => val !== initial[k] && k !== "motivo"));
    void act.run(async () => {
      const r = await api<{ numero: number }>(`/admin/users/${id}`, { method: "PATCH", body: { ...changes, motivo: v.motivo || null } });
      onDone(r.numero);
    });
  };
  return (
    <Modal title="Modificar datos (cambios agrupados en una solicitud)" onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <ErrorBox error={act.error} />
        <div className="form-grid">
          {["identificacion", "nombre", "primer_apellido", "segundo_apellido", "correo"].map((k) => (
            <Field key={k} label={k.replace("_", " ")}><input value={v[k]} onChange={(e) => set(k, e.target.value)} /></Field>
          ))}
          <Field label="Perfil">
            <select value={v.perfil} onChange={(e) => set("perfil", e.target.value)}>
              {perfiles.map((p) => <option key={p.codigo} value={p.codigo}>{p.nombre}</option>)}
            </select>
          </Field>
          <OrgFields values={v} set={set} />
        </div>
        <Field label="Motivo"><textarea value={v.motivo ?? ""} onChange={(e) => set("motivo", e.target.value)} /></Field>
        <div className="row"><span className="spacer" /><button type="button" className="btn" onClick={onClose}>Cancelar</button>
          <button className="btn primary" disabled={act.busy}>Crear solicitud</button></div>
      </form>
    </Modal>
  );
}

function ModulesModal({ id, current, onClose, onDone }: { id: string; current: string[]; onClose: () => void; onDone: (n: number) => void }) {
  const { modulos } = useOrg();
  const [sel, setSel] = useState<string[]>(current);
  const act = useAction();
  return (
    <Modal title="Asignación de módulos" onClose={onClose}>
      <div className="stack">
        <ErrorBox error={act.error} />
        <div className="alert info small">La asignación habilita el acceso al módulo; los permisos llegan por el perfil.</div>
        {modulos.map((m) => (
          <label key={m.codigo} className="row">
            <input type="checkbox" style={{ width: "auto" }} checked={sel.includes(m.codigo)}
                   onChange={(e) => setSel(e.target.checked ? [...sel, m.codigo] : sel.filter((x) => x !== m.codigo))} />
            {m.nombre}
          </label>
        ))}
        <div className="row"><span className="spacer" /><button className="btn" onClick={onClose}>Cancelar</button>
          <button className="btn primary" disabled={act.busy} onClick={() => void act.run(async () => {
            const r = await api<{ numero: number }>(`/admin/users/${id}/modules`, { method: "PUT", body: { modulos: sel } });
            onDone(r.numero);
          })}>Crear solicitud</button></div>
      </div>
    </Modal>
  );
}
