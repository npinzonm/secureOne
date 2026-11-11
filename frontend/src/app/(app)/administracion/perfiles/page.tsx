"use client";

import { useState } from "react";
import { CatalogCreate } from "@/components/CatalogCreate";
import { CodePicker, ImpactConfirm } from "@/components/Impact";
import { Badge, ErrorBox, Modal, PageHeader, useAction, useLoad } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

type Perfil = { id: string; codigo: string; nombre: string; descripcion: string | null; estado: string; es_sistema: boolean; roles: string[]; usuarios_activos: number };

export default function ProfilesPage() {
  const { can } = useSession();
  const { data, error, reload } = useLoad(() => api<Perfil[]>("/admin/profiles"), []);
  const roles = useLoad(() => api<{ codigo: string; nombre: string; estado: string }[]>("/admin/roles"), []);
  const act = useAction();
  const [create, setCreate] = useState(false);
  const [editRoles, setEditRoles] = useState<Perfil | null>(null);
  const [pick, setPick] = useState<string[]>([]);
  const [confirm, setConfirm] = useState(false);

  return (
    <div className="stack">
      <PageHeader title="Perfiles" subtitle="Usuario → Perfil → Roles → Permisos. Cada usuario tiene exactamente un perfil."
        actions={can("ADM.PERFIL.CREACION") ? <button className="btn primary" onClick={() => setCreate(true)}>Nuevo perfil</button> : null} />
      <ErrorBox error={error ?? act.error} />
      <div className="table-wrap"><table>
        <thead><tr><th>Código</th><th>Nombre</th><th>Roles</th><th>Usuarios activos</th><th>Estado</th><th></th></tr></thead>
        <tbody>{data?.map((p) => (
          <tr key={p.id}>
            <td className="mono">{p.codigo}{p.es_sistema ? <span className="badge accent" style={{ marginLeft: 6 }}>sistema</span> : null}</td>
            <td>{p.nombre}<div className="small muted">{p.descripcion}</div></td>
            <td className="small mono">{p.roles.join(", ") || "—"}</td>
            <td>{p.usuarios_activos}</td>
            <td><Badge value={p.estado} /></td>
            <td className="row">
              {!p.es_sistema && can("ADM.PERFIL.EDICION") ? <button className="btn sm" onClick={() => { setEditRoles(p); setPick(p.roles); }}>Roles</button> : null}
              {!p.es_sistema && can("ADM.PERFIL.ELIMINACION") ? (
                <button className="btn sm" disabled={act.busy} onClick={() => void act.run(async () => {
                  await api(`/admin/profiles/${p.id}/status`, { body: { estado: p.estado === "ACTIVO" ? "INACTIVO" : "ACTIVO" } });
                  await reload();
                })}>{p.estado === "ACTIVO" ? "Inactivar" : "Activar"}</button>
              ) : null}
            </td>
          </tr>
        ))}</tbody>
      </table></div>
      {create ? (
        <CatalogCreate title="Nuevo perfil" path="/admin/profiles" onClose={() => setCreate(false)}
          onDone={() => { setCreate(false); void reload(); }}
          fields={[{ key: "codigo", label: "Código", hint: "MAYÚSCULAS y _", required: true },
                   { key: "nombre", label: "Nombre", required: true }, { key: "descripcion", label: "Descripción" }]} />
      ) : null}
      {editRoles && !confirm ? (
        <Modal title={`Roles del perfil ${editRoles.codigo}`} onClose={() => setEditRoles(null)}>
          <div className="stack">
            <CodePicker options={(roles.data ?? []).filter((r) => r.estado === "ACTIVO")} value={pick} onChange={setPick} />
            <div className="row"><span className="spacer" /><button className="btn" onClick={() => setEditRoles(null)}>Cancelar</button>
              <button className="btn primary" onClick={() => setConfirm(true)}>Continuar</button></div>
          </div>
        </Modal>
      ) : null}
      {editRoles && confirm ? (
        <ImpactConfirm title={`Confirmar roles de ${editRoles.codigo}`}
          impactPath={`/admin/profiles/${editRoles.id}/roles/impact`} applyPath={`/admin/profiles/${editRoles.id}/roles`}
          applyMethod="PUT" body={{ codigos: pick }}
          onClose={() => { setConfirm(false); setEditRoles(null); }}
          onDone={() => { setConfirm(false); setEditRoles(null); void reload(); }} />
      ) : null}
    </div>
  );
}
