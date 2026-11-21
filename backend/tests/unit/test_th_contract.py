"""Unitarias del contrato de archivos TH (DD-03)."""

import io
import zipfile
from datetime import datetime

import pytest
from openpyxl import Workbook

from app.modules.th.domain.contract import StructuralError, normalize_header, parse

ACTIVA = ["Identificación", "Nombres", "PRIMER APELLIDO", "codigo_gerencia", "GERENCIA",
          "CODIGO_AREA", "AREA", "CODIGO_CARGO", "CARGO", "EMPRESA", "COLUMNA_EXTRA"]


def xlsx(headers, rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_header_normalization():
    assert normalize_header("  Identificación ") == "IDENTIFICACION"
    assert normalize_header("Primer apellido") == "PRIMER_APELLIDO"


def test_activa_rows_errors_duplicates_and_empresa_never_read():
    content = xlsx(ACTIVA, [
        ["ID-1", "Ana", "Pérez", "G1", "Gerencia 1", "A1", "Área 1", 10, "Analista",
         "ACME S.A.", "x"],
        ["ID-2", "Luis", None, "G1", "Gerencia 1", "A1", "Área 1", "abc", "Analista", "ACME", ""],
        ["ID-3", "Eva", "Ruiz", "G1", "Gerencia 1", "A1", "Área 1", 11, "Líder", "ACME", ""],
        ["ID-3", "Eva", "Ruiz", "G1", "Gerencia 1", "A1", "Área 1", 11, "Líder", "ACME", ""],
        [None, None, None, None, None, None, None, None, None, None, None],  # vacía: se ignora
    ])
    p = parse(content, "ACTIVA")
    assert p.unknown_columns == ["COLUMNA_EXTRA"]
    assert [r.fila for r in p.rows] == [2, 3, 4, 5]
    assert p.rows[0].ok and p.rows[0].data["CODIGO_CARGO"] == 10
    assert set(p.rows[1].errors) == {"PRIMER_APELLIDO_OBLIGATORIO", "CODIGO_CARGO_FORMATO"}
    assert p.rows[2].errors == ["IDENTIFICACION_DUPLICADA"] == p.rows[3].errors
    assert all("EMPRESA" not in r.data and "ACME" not in str(r.data) for r in p.rows)


def test_retirados_dates_and_username():
    content = xlsx(["IDENTIFICACION", "FECHA_RETIRO", "USUARIO_RED"], [
        ["ID-1", datetime(2026, 11, 1), "A1B2C3D4"],
        ["ID-2", "2026-11-02", None],
        ["ID-3", "02/11/2026", "mal"],
    ])
    p = parse(content, "RETIRADOS")
    assert p.rows[0].ok and p.rows[0].data == {"IDENTIFICACION": "ID-1",
                                              "USUARIO_RED": "a1b2c3d4",
                                              "FECHA_RETIRO": "2026-11-01"}
    assert p.rows[1].ok
    assert set(p.rows[2].errors) == {"FECHA_RETIRO_FORMATO", "USUARIO_RED_FORMATO"}


@pytest.mark.parametrize("content, msg", [
    (b"", "vacío"),
    (b"no es un zip", "no es un archivo"),
    (xlsx(["IDENTIFICACION", "NOMBRES"], [["1", "a"]]), "faltan columnas obligatorias"),
])
def test_structural_errors(content, msg):
    with pytest.raises(StructuralError, match=msg):
        parse(content, "ACTIVA")


def test_macros_are_rejected():
    base = xlsx(ACTIVA, [])
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base)) as src, zipfile.ZipFile(buf, "w") as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        dst.writestr("xl/vbaProject.bin", b"macro")
    with pytest.raises(StructuralError, match="macros"):
        parse(buf.getvalue(), "ACTIVA")
