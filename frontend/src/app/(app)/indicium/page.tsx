"use client";
// Indicium Insight: SOLO shell (REQ-IND-01). Reglas de negocio APLAZADAS (D-IND-001).

import Link from "next/link";
import { useSession } from "@/lib/session";

export default function IndiciumPage() {
  const { modules } = useSession();
  const assigned = modules.some((m) => m.codigo === "IND");
  return (
    <main className="content stack">
      <h1>Indicium Insight</h1>
      {assigned ? (
        <div className="card stack">
          <div className="alert info">
            Módulo en levantamiento funcional. La gestión de KPI/KGI, captura, validación, aprobación de
            resultados, tableros y reportes se construirá cuando se apruebe su especificación.
          </div>
        </div>
      ) : (
        <div className="alert error">No tiene asignado este módulo.</div>
      )}
      <Link href="/">← Volver al inicio</Link>
    </main>
  );
}
