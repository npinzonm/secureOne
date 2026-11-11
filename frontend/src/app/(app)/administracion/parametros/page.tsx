"use client";

import { useState } from "react";
import { ErrorBox, PageHeader, useAction, useLoad } from "@/components/ui";
import { api, fmtDate } from "@/lib/api";
import { useSession } from "@/lib/session";

type P = { clave: string; valor: string | null; tipo: string; descripcion: string; minimo: number | null; maximo: number | null; modificado_en: string | null };

export default function ParamsPage() {
  const { can } = useSession();
  const { data, error, reload } = useLoad(() => api<P[]>("/admin/parameters"), []);
  const [edit, setEdit] = useState<Record<string, string>>({});
  const act = useAction();
  return (
    <div className="stack">
      <PageHeader title="Parámetros" subtitle="Cambios directos y auditados." />
      <ErrorBox error={error ?? act.error} />
      <div className="table-wrap"><table>
        <thead><tr><th>Clave</th><th>Descripción</th><th>Valor</th><th>Modificado</th></tr></thead>
        <tbody>{data?.map((p) => (
          <tr key={p.clave}>
            <td className="mono">{p.clave}</td><td className="small">{p.descripcion}</td>
            <td>{can("ADM.PARAMETRO.EDICION") ? (
              <form className="row" onSubmit={(e) => { e.preventDefault(); void act.run(async () => {
                await api(`/admin/parameters/${p.clave}`, { method: "PATCH", body: { valor: edit[p.clave] } }); await reload();
              }); }}>
                <input style={{ width: 140 }} placeholder={p.tipo === "HORA" ? "HH:MM" : p.tipo}
                       value={edit[p.clave] ?? p.valor ?? ""} onChange={(e) => setEdit({ ...edit, [p.clave]: e.target.value })} />
                <button className="btn sm" disabled={act.busy}>Guardar</button>
              </form>
            ) : (p.valor ?? "—")}</td>
            <td className="small">{fmtDate(p.modificado_en)}</td>
          </tr>
        ))}</tbody>
      </table></div>
    </div>
  );
}
