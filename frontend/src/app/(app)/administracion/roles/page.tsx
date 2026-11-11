"use client";

import { useState } from "react";
import { CatalogCreate } from "@/components/CatalogCreate";
import { CodePicker, ImpactConfirm } from "@/components/Impact";
import { Badge, ErrorBox, Modal, PageHeader, useLoad } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

type Rol = { id: string; codigo: string; nombre: string; descripcion: string | null; estado: string; es_sistema: boolean; permisos: string[] };

export default function RolesPage() {
  const { can } = useSession();
  const { data, error, reload } = useLoad(() => api<Rol[]>("/admin/roles"), []);
  const perms = useLoad(() => api<{ codigo: string; nombre: string; estado: string }[]>("/admin/permissions"), []);
  const [create, setCreate] = useState(false);
  const [edit, setEdit] = useState<Rol | null>(null);
  const [pick, setPick] = useState<string[]>([]);
  const [confirm, setConfirm] = useState<null | "perms" | "status">(null);

  const close = () => { setConfirm(null); setEdit(null); };
  return (
    <div className="stack">
      <PageHeader title="Roles" subtitle="Un rol agrupa permisos. Los cambios muestran su impacto antes de aplicarse."
        actions={can("ADM.ROL.CREACION") ? <button className="btn primary" onClick={() => setCreate(true)}>Nuevo rol</button> : null} />
      <ErrorBox error={error} />
      <div className="table-wrap"><table>
        <thead><tr><th>Código</th><th>Nombre</th><th>Permisos</th><th>Estado</th><th></th></tr></thead>
        <tbody>{data?.map((r) => (
          <tr key={r.id}>
            <td className="mono">{r.codigo}{r.es_sistema ? <span className="badge accent" style={{ marginLeft: 6 }}>sistema</span> : null}</td>
            <td>{r.nombre}</td>
            <td className="small mono">{r.permisos.length > 6 ? `${r.permisos.length} permisos` : r.permisos.join(", ") || "—"}</td>
            <td><Badge value={r.estado} /></td>
            <td className="row">
              {!r.es_sistema && can("ADM.ROL.EDICION") ? <button className="btn sm" onClick={() => { setEdit(r); setPick(r.permisos); }}>Permisos</button> : null}
              {!r.es_sistema && can("ADM.ROL.ELIMINACION") ? <button className="btn sm" onClick={() => { setEdit(r); setConfirm("status"); }}>{r.estado === "ACTIVO" ? "Inactivar" : "Activar"}</button> : null}
            </td>
          </tr>
        ))}</tbody>
      </table></div>
      {create ? (
        <CatalogCreate title="Nuevo rol" path="/admin/roles" onClose={() => setCreate(false)} onDone={() => { setCreate(false); void reload(); }}
          fields={[{ key: "codigo", label: "Código", required: true }, { key: "nombre", label: "Nombre", required: true }, { key: "descripcion", label: "Descripción" }]} />
      ) : null}
      {edit && !confirm ? (
        <Modal title={`Permisos del rol ${edit.codigo}`} onClose={close}>
          <div className="stack">
            <CodePicker options={(perms.data ?? []).filter((p) => p.estado === "ACTIVO")} value={pick} onChange={setPick} />
            <div className="row"><span className="spacer" /><button className="btn" onClick={close}>Cancelar</button>
              <button className="btn primary" onClick={() => setConfirm("perms")}>Continuar</button></div>
          </div>
        </Modal>
      ) : null}
      {edit && confirm === "perms" ? (
        <ImpactConfirm title={`Confirmar permisos de ${edit.codigo}`} impactPath={`/admin/roles/${edit.id}/permissions/impact`}
          applyPath={`/admin/roles/${edit.id}/permissions`} applyMethod="PUT" body={{ codigos: pick }}
          onClose={close} onDone={() => { close(); void reload(); }} />
      ) : null}
      {edit && confirm === "status" ? (
        <ImpactConfirm title={`${edit.estado === "ACTIVO" ? "Inactivar" : "Activar"} ${edit.codigo}`}
          impactPath={`/admin/roles/${edit.id}/status/impact`} applyPath={`/admin/roles/${edit.id}/status`} applyMethod="POST"
          body={{ estado: edit.estado === "ACTIVO" ? "INACTIVO" : "ACTIVO" }}
          onClose={close} onDone={() => { close(); void reload(); }} />
      ) : null}
    </div>
  );
}
