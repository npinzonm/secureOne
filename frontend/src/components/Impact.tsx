"use client";
// Flujo de impacto previo (REQ-IAM-09): 1) consultar impacto, 2) confirmar con el token.
// Si el impacto cambió entre ambos pasos, el backend responde 409 y se vuelve a consultar.

import { useState } from "react";
import { api } from "@/lib/api";
import { ErrorBox, Modal, useAction } from "./ui";

type ImpactOut = {
  perfiles_afectados: string[]; usuarios_afectados: number; usuarios: string[];
  agregados?: string[]; quitados?: string[]; confirm_impact_token: string;
};

export function ImpactConfirm({ title, impactPath, applyPath, applyMethod, body, onClose, onDone }: {
  title: string; impactPath: string; applyPath: string; applyMethod: "PUT" | "POST";
  body: Record<string, unknown>; onClose: () => void; onDone: () => void;
}) {
  const [impact, setImpact] = useState<ImpactOut | null>(null);
  const act = useAction();
  const load = () => void act.run(async () => setImpact(await api<ImpactOut>(impactPath, { body })));
  return (
    <Modal title={title} onClose={onClose}>
      <div className="stack">
        <ErrorBox error={act.error} />
        {!impact ? (
          <>
            <p>Antes de aplicar el cambio se mostrará su impacto en perfiles y usuarios.</p>
            <div className="row"><span className="spacer" /><button className="btn" onClick={onClose}>Cancelar</button>
              <button className="btn primary" disabled={act.busy} onClick={load}>Ver impacto</button></div>
          </>
        ) : (
          <>
            {impact.agregados?.length ? <div><strong>Se agregan:</strong> {impact.agregados.join(", ")}</div> : null}
            {impact.quitados?.length ? <div><strong>Se quitan:</strong> {impact.quitados.join(", ")}</div> : null}
            <div className="alert warn">
              Afecta a <strong>{impact.perfiles_afectados.length}</strong> perfil(es)
              {impact.perfiles_afectados.length ? ` (${impact.perfiles_afectados.join(", ")})` : ""} y a{" "}
              <strong>{impact.usuarios_afectados}</strong> usuario(s) activo(s).
            </div>
            {impact.usuarios.length ? <div className="small mono">{impact.usuarios.join(", ")}</div> : null}
            <div className="row"><span className="spacer" /><button className="btn" onClick={onClose}>Cancelar</button>
              <button className="btn primary" disabled={act.busy} onClick={() => void act.run(async () => {
                await api(applyPath, { method: applyMethod, body: { ...body, confirm_impact_token: impact.confirm_impact_token } });
                onDone();
              })}>Confirmar cambio</button></div>
          </>
        )}
      </div>
    </Modal>
  );
}

/** Selector múltiple simple de códigos. */
export function CodePicker({ options, value, onChange }: {
  options: { codigo: string; nombre?: string }[]; value: string[]; onChange: (v: string[]) => void;
}) {
  return (
    <div style={{ maxHeight: 320, overflow: "auto" }} className="card">
      {options.map((o) => (
        <label key={o.codigo} className="row small">
          <input type="checkbox" style={{ width: "auto" }} checked={value.includes(o.codigo)}
                 onChange={(e) => onChange(e.target.checked ? [...value, o.codigo] : value.filter((x) => x !== o.codigo))} />
          <span className="mono">{o.codigo}</span>{o.nombre ? <span className="muted">· {o.nombre}</span> : null}
        </label>
      ))}
    </div>
  );
}
