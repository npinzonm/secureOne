"use client";

import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { ErrorBox, Field, Modal, useAction } from "./ui";

/** Alta genérica de perfil/rol/permiso/módulo/dominio. Campos según `fields`. */
export function CatalogCreate({ title, path, fields, onClose, onDone }: {
  title: string; path: string; onClose: () => void; onDone: () => void;
  fields: { key: string; label: string; hint?: string; required?: boolean; options?: string[] }[];
}) {
  const [v, setV] = useState<Record<string, string>>({});
  const act = useAction();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body = Object.fromEntries(Object.entries(v).filter(([, x]) => x !== ""));
    void act.run(async () => { await api(path, { body }); onDone(); });
  };
  return (
    <Modal title={title} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <ErrorBox error={act.error} />
        {fields.map((f) => (
          <Field key={f.key} label={f.label} hint={f.hint}>
            {f.options ? (
              <select value={v[f.key] ?? ""} onChange={(e) => setV({ ...v, [f.key]: e.target.value })} required={f.required}>
                <option value="">—</option>{f.options.map((o) => <option key={o}>{o}</option>)}
              </select>
            ) : (
              <input value={v[f.key] ?? ""} onChange={(e) => setV({ ...v, [f.key]: e.target.value })} required={f.required} />
            )}
          </Field>
        ))}
        <div className="row"><span className="spacer" /><button type="button" className="btn" onClick={onClose}>Cancelar</button>
          <button className="btn primary" disabled={act.busy}>Crear</button></div>
      </form>
    </Modal>
  );
}
