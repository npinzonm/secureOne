#!/usr/bin/env python3
"""Genera docs/trazabilidad.csv (REQ-RNF-11, campos de M §24) desde docs/01-matriz-requisitos.md.

Campos: identificador, descripción, clasificación, módulo, prioridad, estado del requisito,
estado de implementación, casos de prueba asociados, evidencia de validación y versión.
Uso: python3 scripts/generate-trazabilidad.py
"""

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.0-rc (Fases 1–10)"

# Área → (módulo, pruebas asociadas). Las rutas son relativas al repositorio.
AREAS = {
    "GEN": ("Plataforma", "scripts/smoke.sh; backend/tests/api/test_health.py"),
    "AUTH": ("Autenticación", "backend/tests/integration/test_auth_fase3.py; "
             "backend/tests/unit/test_auth_security.py; frontend/e2e/secureone.spec.ts"),
    "USER": ("Administración · Usuarios", "backend/tests/integration/test_admin_fase5.py; "
             "backend/tests/integration/test_requests_fase6.py; backend/tests/integration/test_iam_fase4.py"),
    "IAM": ("Administración · IAM", "backend/tests/integration/test_iam_fase4.py; "
            "backend/tests/integration/test_admin_fase5.py; backend/tests/unit/test_authz_routes.py"),
    "APR": ("Administración · Solicitudes", "backend/tests/integration/test_admin_fase5.py; "
            "backend/tests/integration/test_requests_fase6.py; frontend/e2e/secureone.spec.ts"),
    "TH": ("Integración Talento Humano", "backend/tests/integration/test_th_fase8.py; "
           "backend/tests/unit/test_th_contract.py"),
    "AUD": ("Auditoría", "backend/tests/integration/test_database_fase2.py; "
            "backend/tests/integration/test_fase7.py"),
    "ERR": ("Registro de errores", "backend/tests/integration/test_database_fase2.py; "
            "backend/tests/integration/test_fase7.py"),
    "NOT": ("Notificaciones", "backend/tests/integration/test_fase7.py; backend/tests/unit/test_fase7_units.py"),
    "IND": ("Indicium Insight", "backend/tests/unit/test_authz_routes.py (shell)"),
    "RNF": ("Transversal", "scripts/test-backups.sh; scripts/test-e2e.sh; .github/workflows/ci.yml"),
}
DELEGATED = {"REQ-AUTH-21": "DD-*", "REQ-USER-15": "DD-02", "REQ-IAM-17": "PROPUESTO",
             "REQ-TH-14": "DD-03/04/05", "REQ-NOT-09": "DD-06", "REQ-RNF-13": "DD-07",
             "REQ-AUD-09": "PROPUESTO PD-03/PD-04"}
PARTIAL = {"REQ-GEN-02": "PARCIAL (Indicium Insight solo como shell; D-IND-001)",
           "REQ-GEN-03": "PARCIAL (componente Indicadores aplazado; D-IND-001)"}


def implementation(req_id: str, estado: str) -> str:
    e = estado.replace("**", "").upper()
    if req_id in PARTIAL:
        return PARTIAL[req_id]
    if e.startswith("APLAZADO"):
        return "NO APLICA (APLAZADO)"
    if e.startswith("EXCLUIDO"):
        return "NO APLICA (EXCLUIDO)"
    if req_id in DELEGATED:
        return f"IMPLEMENTADO (definición {DELEGATED[req_id]})"
    if e.startswith("PENDIENTE"):
        return "PENDIENTE"
    return "IMPLEMENTADO"


def main() -> None:
    rows = []
    text = (ROOT / "docs/01-matriz-requisitos.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        m = re.match(r"^\| (REQ-([A-Z]+)-\d+) \| (.+?) \| (.+?) \| (.+?) \| (.+?) \| (.+?) \|$", line)
        if not m:
            continue
        req_id, area, desc, fuente, estado, prio, fase = m.groups()
        modulo, tests = AREAS.get(area, ("—", ""))
        impl = implementation(req_id, estado)
        fase_n = re.search(r"\d+", fase)
        done = impl.startswith(("IMPL", "PARCIAL"))
        evidence = f"docs/fases/FASE-{fase_n.group()}.md" if fase_n and done else "—"
        rows.append({
            "identificador": req_id,
            "descripcion": re.sub(r"\*\*|`", "", desc),
            "clasificacion": area,
            "modulo": modulo,
            "prioridad": prio if prio not in ("—", "") else "—",
            "estado_requisito": re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", estado.replace("**", "")),
            "estado_implementacion": impl,
            "casos_prueba": tests if done else "—",
            "evidencia_validacion": evidence,
            "fuente": fuente,
            "version_implementacion": VERSION if done else "—",
        })
    out = ROOT / "docs/trazabilidad.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    counts: dict[str, int] = {}
    for r in rows:
        k = r["estado_implementacion"].split(" ")[0]
        counts[k] = counts.get(k, 0) + 1
    print(f"{out.relative_to(ROOT)}: {len(rows)} requisitos · {counts}")


if __name__ == "__main__":
    main()
