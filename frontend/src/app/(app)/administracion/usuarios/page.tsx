"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { OrgFields, useOrg, type UserValues } from "@/components/UserForm";
import { Badge, Empty, ErrorBox, Field, Modal, PageHeader, useAction, useLoad } from "@/components/ui";
import { api, download, fmtDate } from "@/lib/api";
import { useSession } from "@/lib/session";

type U = {
  id: string; usuario_red: string; identificacion: string; nombre: string; primer_apellido: string;
  segundo_apellido: string | null; correo: string; perfil_nombre: string; gerencia: string | null;
  area: string | null; cargo: string | null; tipo_alta: string | null; estado: string; ultimo_ingreso: string | null;
};

const FILTERS = ["nombre", "usuario_red", "identificacion", "correo", "estado", "tipo_alta"] as const;

export default function UsersPage() {
  const { can } = useSession();
  const router = useRouter();
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [applied, setApplied] = useState<Record<string, string>>({});
  const [page, setPage] = useState(1);
  const [alta, setAlta] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const exp = useAction();
  const { data, error } = useLoad(
    () => api<{ items: U[]; total: number }>("/admin/users", { query: { ...applied, page, page_size: 25 } }),
    [applied, page]);

  const apply = (e: FormEvent) => {
    e.preventDefault();
    setPage(1);
    setApplied(Object.fromEntries(Object.entries(filters).filter(([, v]) => v)));
  };

  return (
    <div className="stack">
      <PageHeader
        title="Usuarios"
        subtitle="Consulta central. Las altas y cambios generan solicitudes que requieren aprobación."
        actions={
          <>
            {can("ADM.USUARIO.EXPORTACION") ? (
              <button className="btn" disabled={exp.busy} onClick={() => void exp.run(async () => {
                const truncated = await download("/admin/users/export", applied, "secureone-usuarios.xlsx");
                setMsg(truncated ? "La exportación se truncó al máximo permitido." : "Exportación generada (auditada).");
              })}>Exportar a Excel</button>
            ) : null}
            {can("ADM.USUARIO.CREACION") ? <button className="btn primary" onClick={() => setAlta(true)}>Nuevo usuario</button> : null}
          </>
        }
      />
      {msg ? <div className="alert ok">{msg}</div> : null}
      <ErrorBox error={exp.error} />
      <form className="card form-grid" onSubmit={apply}>
        {FILTERS.map((f) => (
          <Field key={f} label={f.replace("_", " ")}>
            {f === "estado" ? (
              <select value={filters[f] ?? ""} onChange={(e) => setFilters({ ...filters, [f]: e.target.value })}>
                <option value="">Todos</option><option>ACTIVO</option><option>INACTIVO</option><option>PENDIENTE_ALTA</option>
              </select>
            ) : f === "tipo_alta" ? (
              <select value={filters[f] ?? ""} onChange={(e) => setFilters({ ...filters, [f]: e.target.value })}>
                <option value="">Todos</option><option>NORMAL</option><option>EXCEPCIONAL</option>
              </select>
            ) : (
              <input value={filters[f] ?? ""} onChange={(e) => setFilters({ ...filters, [f]: e.target.value })} />
            )}
          </Field>
        ))}
        <div className="row" style={{ alignSelf: "end" }}><button className="btn primary" type="submit">Buscar</button></div>
      </form>
      <ErrorBox error={error} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>Usuario de red</th><th>Nombre</th><th>Perfil</th><th>Gerencia / Área</th><th>Tipo</th><th>Estado</th><th>Último ingreso</th></tr></thead>
          <tbody>
            {data?.items.map((u) => (
              <tr key={u.id} className="clickable" onClick={() => router.push(`/administracion/usuarios/${u.id}`)}>
                <td className="mono">{u.usuario_red}</td>
                <td>{u.nombre} {u.primer_apellido} {u.segundo_apellido ?? ""}<div className="small muted">{u.correo}</div></td>
                <td>{u.perfil_nombre}</td>
                <td>{u.gerencia ?? "—"}<div className="small muted">{u.area ?? ""}</div></td>
                <td>{u.tipo_alta ?? "—"}</td>
                <td><Badge value={u.estado} /></td>
                <td className="small">{fmtDate(u.ultimo_ingreso)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && data.items.length === 0 ? <Empty /> : null}
      </div>
      {data ? (
        <div className="row small">
          <span className="muted">{data.total} usuario(s)</span><span className="spacer" />
          <button className="btn sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Anterior</button>
          <span>Página {page}</span>
          <button className="btn sm" disabled={page * 25 >= data.total} onClick={() => setPage(page + 1)}>Siguiente</button>
        </div>
      ) : null}
      {alta ? <AltaModal onClose={() => setAlta(false)} onDone={(n) => { setAlta(false); setMsg(`Solicitud de alta #${n} creada. Debe aprobarse para que el usuario quede activo.`); }} /> : null}
    </div>
  );
}

function AltaModal({ onClose, onDone }: { onClose: () => void; onDone: (numero: number) => void }) {
  const { perfiles, modulos } = useOrg();
  const [v, setV] = useState<UserValues>({ tipo_alta: "NORMAL" });
  const [mods, setMods] = useState<string[]>([]);
  const act = useAction();
  const set = (k: string, val: string) => setV((p) => ({ ...p, [k]: val }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void act.run(async () => {
      const r = await api<{ numero: number }>("/admin/users", {
        body: { ...v, segundo_apellido: v.segundo_apellido || null, motivo: v.motivo || null, modulos: mods },
      });
      onDone(r.numero);
    });
  };
  return (
    <Modal title="Solicitud de alta de usuario" onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <ErrorBox error={act.error} />
        <div className="form-grid">
          <Field label="Usuario de red" hint="8 caracteres alternando letra y número">
            <input value={v.usuario_red ?? ""} onChange={(e) => set("usuario_red", e.target.value)} required maxLength={16} />
          </Field>
          <Field label="Identificación"><input value={v.identificacion ?? ""} onChange={(e) => set("identificacion", e.target.value)} required maxLength={20} /></Field>
          <Field label="Nombre"><input value={v.nombre ?? ""} onChange={(e) => set("nombre", e.target.value)} required maxLength={100} /></Field>
          <Field label="Primer apellido"><input value={v.primer_apellido ?? ""} onChange={(e) => set("primer_apellido", e.target.value)} required maxLength={50} /></Field>
          <Field label="Segundo apellido"><input value={v.segundo_apellido ?? ""} onChange={(e) => set("segundo_apellido", e.target.value)} maxLength={50} /></Field>
          <Field label="Correo"><input type="email" value={v.correo ?? ""} onChange={(e) => set("correo", e.target.value)} required maxLength={150} /></Field>
          <Field label="Perfil">
            <select value={v.perfil ?? ""} onChange={(e) => set("perfil", e.target.value)} required>
              <option value="">— Seleccione —</option>
              {perfiles.map((p) => <option key={p.codigo} value={p.codigo}>{p.nombre}</option>)}
            </select>
          </Field>
          <OrgFields values={v} set={set} />
          <Field label="Tipo de alta" hint="EXCEPCIONAL: no figura en la planta de TH; requiere motivo">
            <select value={v.tipo_alta} onChange={(e) => set("tipo_alta", e.target.value)}>
              <option>NORMAL</option><option>EXCEPCIONAL</option>
            </select>
          </Field>
        </div>
        <fieldset className="card">
          <legend className="small muted">Módulos</legend>
          <div className="row">
            {modulos.map((m) => (
              <label key={m.codigo} className="row small">
                <input type="checkbox" style={{ width: "auto" }} checked={mods.includes(m.codigo)}
                       onChange={(e) => setMods(e.target.checked ? [...mods, m.codigo] : mods.filter((x) => x !== m.codigo))} />
                {m.nombre}
              </label>
            ))}
          </div>
        </fieldset>
        <Field label="Motivo"><textarea value={v.motivo ?? ""} onChange={(e) => set("motivo", e.target.value)} maxLength={1000} /></Field>
        <div className="row"><span className="spacer" />
          <button type="button" className="btn" onClick={onClose}>Cancelar</button>
          <button type="submit" className="btn primary" disabled={act.busy}>Crear solicitud</button>
        </div>
      </form>
    </Modal>
  );
}
