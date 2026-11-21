"""Contrato de archivos de Talento Humano (DD-03, definido por delegación 2026-11-10).

Lectura y validación PURAS (sin BD):
  - Error estructural → StructuralError (la ejecución se rechaza completa).
  - Error de fila → la fila se excluye; el resto se procesa (procesamiento parcial).
La columna EMPRESA nunca se lee (REQ-TH-12): se descarta al normalizar encabezados.
"""

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from openpyxl import load_workbook

from app.modules.users.domain.identifiers import (
    is_valid_email,
    is_valid_identificacion,
    is_valid_usuario_red,
    normalize_usuario_red,
)

Tipo = Literal["ACTIVA", "RETIRADOS"]
MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 100_000
NEVER_READ = {"EMPRESA"}

REQUIRED: dict[str, tuple[str, ...]] = {
    "ACTIVA": ("IDENTIFICACION", "NOMBRES", "PRIMER_APELLIDO", "CODIGO_GERENCIA", "GERENCIA",
               "CODIGO_AREA", "AREA", "CODIGO_CARGO", "CARGO"),
    "RETIRADOS": ("IDENTIFICACION", "FECHA_RETIRO"),
}
OPTIONAL: dict[str, tuple[str, ...]] = {
    "ACTIVA": ("SEGUNDO_APELLIDO", "CORREO", "USUARIO_RED"),
    "RETIRADOS": ("USUARIO_RED", "NOMBRES", "PRIMER_APELLIDO"),
}
_CODE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")


class StructuralError(Exception):
    """Error que impide identificar registros: se rechaza toda la ejecución."""


@dataclass
class Row:
    fila: int
    data: dict[str, Any]
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def identificacion(self) -> str | None:
        v = self.data.get("IDENTIFICACION")
        return v if isinstance(v, str) and v else None


@dataclass
class ParsedFile:
    tipo: Tipo
    rows: list[Row]
    unknown_columns: list[str]


def normalize_header(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", "_", text.strip().upper())


def _text(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s or None


def check_container(content: bytes) -> None:
    if not content:
        raise StructuralError("archivo vacío")
    if len(content) > MAX_BYTES:
        raise StructuralError("el archivo supera 10 MB")
    if not content.startswith(b"PK\x03\x04"):
        raise StructuralError("no es un archivo .xlsx válido")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = z.namelist()
    except zipfile.BadZipFile as exc:
        raise StructuralError("no es un archivo .xlsx válido") from exc
    if any(n.lower().endswith("vbaproject.bin") for n in names):
        raise StructuralError("el archivo contiene macros")
    if "xl/workbook.xml" not in names:
        raise StructuralError("no es un libro de Excel")


def parse(content: bytes, tipo: Tipo) -> ParsedFile:
    check_container(content)
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - cualquier fallo de lectura es estructural
        raise StructuralError("no se pudo leer el libro") from exc
    try:
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        try:
            header = next(it)
        except StopIteration as exc:
            raise StructuralError("la hoja está vacía") from exc
        cols = [normalize_header(h) for h in header]
        missing = [c for c in REQUIRED[tipo] if c not in cols]
        if missing:
            raise StructuralError(f"faltan columnas obligatorias: {', '.join(missing)}")
        known = set(REQUIRED[tipo]) | set(OPTIONAL[tipo])
        unknown = sorted({c for c in cols if c and c not in known and c not in NEVER_READ})
        index = {c: i for i, c in enumerate(cols) if c in known}  # EMPRESA nunca se indexa
        rows: list[Row] = []
        for n, values in enumerate(it, start=2):
            if values is None or all(v is None or str(v).strip() == "" for v in values):
                continue
            if len(rows) >= MAX_ROWS:
                raise StructuralError(f"el archivo supera {MAX_ROWS} filas")
            raw = {c: (values[i] if i < len(values) else None) for c, i in index.items()}
            rows.append(_validate(tipo, n, raw))
    finally:
        wb.close()
    _mark_duplicates(rows)
    return ParsedFile(tipo, rows, unknown)


def _validate(tipo: Tipo, fila: int, raw: dict[str, Any]) -> Row:
    errors: list[str] = []
    data: dict[str, Any] = {}

    def req(col: str, max_len: int) -> str | None:
        v = _text(raw.get(col))
        if v is None:
            errors.append(f"{col}_OBLIGATORIO")
        elif len(v) > max_len:
            errors.append(f"{col}_LONGITUD")
        return v

    def opt(col: str, max_len: int) -> str | None:
        v = _text(raw.get(col))
        if v is not None and len(v) > max_len:
            errors.append(f"{col}_LONGITUD")
        return v

    ident = req("IDENTIFICACION", 20)
    if ident and not is_valid_identificacion(ident):
        errors.append("IDENTIFICACION_FORMATO")
    data["IDENTIFICACION"] = ident
    red = _text(raw.get("USUARIO_RED"))
    if red is not None:
        red = normalize_usuario_red(red)
        if not is_valid_usuario_red(red):
            errors.append("USUARIO_RED_FORMATO")
    data["USUARIO_RED"] = red

    if tipo == "ACTIVA":
        data["NOMBRES"] = req("NOMBRES", 100)
        data["PRIMER_APELLIDO"] = req("PRIMER_APELLIDO", 50)
        data["SEGUNDO_APELLIDO"] = opt("SEGUNDO_APELLIDO", 50)
        correo = opt("CORREO", 150)
        if correo and not is_valid_email(correo):
            errors.append("CORREO_FORMATO")
        data["CORREO"] = correo
        for code_col, name_col in (("CODIGO_GERENCIA", "GERENCIA"), ("CODIGO_AREA", "AREA")):
            code = req(code_col, 40)
            if code and not _CODE_RE.match(code):
                errors.append(f"{code_col}_FORMATO")
            data[code_col] = code
            data[name_col] = req(name_col, 150)
        cc = _text(raw.get("CODIGO_CARGO"))
        if cc is None:
            errors.append("CODIGO_CARGO_OBLIGATORIO")
        elif not cc.isdigit() or int(cc) <= 0:
            errors.append("CODIGO_CARGO_FORMATO")
        data["CODIGO_CARGO"] = int(cc) if cc and cc.isdigit() else None
        data["CARGO"] = req("CARGO", 150)
    else:
        fr = raw.get("FECHA_RETIRO")
        parsed: date | None = None
        if isinstance(fr, datetime):
            parsed = fr.date()
        elif isinstance(fr, date):
            parsed = fr
        elif _text(fr):
            try:
                parsed = date.fromisoformat(_text(fr) or "")
            except ValueError:
                errors.append("FECHA_RETIRO_FORMATO")
        else:
            errors.append("FECHA_RETIRO_OBLIGATORIO")
        data["FECHA_RETIRO"] = parsed.isoformat() if parsed else None
    return Row(fila, data, errors)


def _mark_duplicates(rows: list[Row]) -> None:
    seen: dict[str, list[Row]] = {}
    for r in rows:
        if r.identificacion:
            seen.setdefault(r.identificacion.upper(), []).append(r)
    for dup in (v for v in seen.values() if len(v) > 1):
        for r in dup:
            r.errors.append("IDENTIFICACION_DUPLICADA")
