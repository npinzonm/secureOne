"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { ErrorBox, Field, Modal, useAction } from "./ui";

export function ReasonModal({ title, path, onClose, onDone, label = "Motivo (mín. 10 caracteres)", extra }: {
  title: string; path: string; onClose: () => void; onDone: (n: number) => void; label?: string; extra?: Record<string, unknown>;
}) {
  const [motivo, setMotivo] = useState("");
  const act = useAction();
  return (
    <Modal title={title} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); void act.run(async () => {
        const r = await api<{ numero: number }>(path, { body: { motivo, ...(extra ?? {}) } });
        onDone(r.numero);
      }); }}>
        <ErrorBox error={act.error} />
        <Field label={label}><textarea value={motivo} onChange={(e) => setMotivo(e.target.value)} required minLength={10} /></Field>
        <div className="row"><span className="spacer" /><button type="button" className="btn" onClick={onClose}>Cancelar</button>
          <button className="btn primary" disabled={act.busy}>Confirmar</button></div>
      </form>
    </Modal>
  );
}
