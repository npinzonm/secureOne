"use client";

import { useState } from "react";
import { CatalogCreate } from "@/components/CatalogCreate";
import { Badge, ErrorBox, Modal, PageHeader, useAction, useLoad } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

type Mod = { id: string; codigo: string; nombre: string; estado: string; orden: number; ruta_frontend: string; usuarios_asignados: number };
type Asig = { usuario_red: string; asignacion: string; usuario: string };

export default function ModulesPage() {
  const { can, reload: reloadSession } = useSession();
  const { data, error, reload } = useLoad(() => api<Mod[]>("/admin/modules"), []);
  const act = useAction();
  const [create, setCreate] = useState(false);
  const [review, setReview] = useState<Asig[] | null>(null);

  const move = (i: number, d: -1 | 1) => {
    if (!data) return;
    const codes = data.map((m) => m.codigo);
    [codes[i], codes[i + d]] = [codes[i + d], codes[i]];
    void act.run(async () => { await api("/admin/modules/order", { method: "PUT", body: { codigos: codes } }); await reload(); await reloadSession(); });
  };
  return (
    <div className="stack">
      <PageHeader title="Módulos" subtitle="El orden es el mismo para todos los usuarios. Inactivar un módulo revoca el acceso."
        actions={can("ADM.MODULO.CREACION") ? <button className="btn primary" onClick={() => setCreate(true)}>Nuevo módulo</button> : null} />
      <ErrorBox error={error ?? act.error} />
      <div className="table-wrap"><table>
        <thead><tr><th>Orden</th><th>Código</th><th>Nombre</th><th>Usuarios</th><th>Estado</th><th></th></tr></thead>
        <tbody>{data?.map((m, i) => (
          <tr key={m.id}>
            <td className="row">{m.orden}{can("ADM.MODULO.EDICION") ? (<>
              <button className="btn sm" aria-label="Subir" disabled={i === 0 || act.busy} onClick={() => move(i, -1)}>↑</button>
              <button className="btn sm" aria-label="Bajar" disabled={i === data.length - 1 || act.busy} onClick={() => move(i, 1)}>↓</button></>) : null}</td>
            <td className="mono">{m.codigo}</td><td>{m.nombre}</td><td>{m.usuarios_asignados}</td><td><Badge value={m.estado} /></td>
            <td>{can("ADM.MODULO.ELIMINACION") && m.codigo !== "ADM" ? (
              <button className="btn sm" disabled={act.busy} onClick={() => void act.run(async () => {
                const r = await api<{ asignaciones_a_revisar: Asig[] }>(`/admin/modules/${m.id}/status`, { body: { estado: m.estado === "ACTIVO" ? "INACTIVO" : "ACTIVO" } });
                if (r.asignaciones_a_revisar.length) setReview(r.asignaciones_a_revisar);
                await reload();
              })}>{m.estado === "ACTIVO" ? "Inactivar" : "Activar"}</button>
            ) : null}</td>
          </tr>
        ))}</tbody>
      </table></div>
      {create ? (
        <CatalogCreate title="Nuevo módulo" path="/admin/modules" onClose={() => setCreate(false)} onDone={() => { setCreate(false); void reload(); }}
          fields={[{ key: "codigo", label: "Código", hint: "2–16 letras mayúsculas", required: true }, { key: "nombre", label: "Nombre", required: true },
                   { key: "ruta_frontend", label: "Ruta", hint: "p. ej. /riesgos", required: true }, { key: "descripcion", label: "Descripción" }]} />
      ) : null}
      {review ? (
        <Modal title="Asignaciones históricas a revisar" onClose={() => setReview(null)}>
          <p className="small muted">El módulo se reactivó. Las asignaciones se mantienen como estaban; revíselas por usuario.</p>
          <div className="table-wrap"><table><thead><tr><th>Usuario</th><th>Asignación</th><th>Estado usuario</th></tr></thead>
            <tbody>{review.map((a) => <tr key={a.usuario_red}><td className="mono">{a.usuario_red}</td><td><Badge value={a.asignacion} /></td><td><Badge value={a.usuario} /></td></tr>)}</tbody></table></div>
        </Modal>
      ) : null}
    </div>
  );
}
