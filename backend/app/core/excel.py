"""Exportación a Excel (.xlsx) segura.

- Neutraliza inyección de fórmulas (CSV/Excel injection): un texto que empieza por
  = + - @ (o tabulador/retorno) se prefija con un apóstrofo.
- Tope de filas por exportación (PROPUESTO): no se fijan métricas de rendimiento aprobadas;
  el tope evita agotar memoria en el prototipo y se informa en la respuesta.
"""

import io
import json
import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from fastapi.responses import Response
from openpyxl import Workbook

MAX_EXPORT_ROWS = 50_000
_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def safe_cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict | list):
        value = json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, bool | int | float):
        return value
    text = str(value)
    return "'" + text if text.startswith(_DANGEROUS) else text


def build_xlsx(sheet: str, headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> bytes:
    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title=sheet[:31])
    ws.append(list(headers))
    for row in rows:
        ws.append([safe_cell(v) for v in row])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def xlsx_response(content: bytes, filename: str, truncated: bool) -> Response:
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
        "X-Export-Truncated": "true" if truncated else "false",
    }
    return Response(content=content, media_type=XLSX, headers=headers)
