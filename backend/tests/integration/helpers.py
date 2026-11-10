"""Utilidades compartidas por las pruebas de integración (datos creados como owner)."""

import secrets
import string
import uuid

from fastapi.testclient import TestClient

from app.core.ids import uuid7
from app.modules.auth.infrastructure.hashing import hash_password

PWD = "Inicial#2026abcd"


def rand_red() -> str:
    return "".join(secrets.choice(string.ascii_lowercase) + secrets.choice(string.digits)
                   for _ in range(4))


def ensure_profile(owner, codigo: str, roles: tuple[str, ...] = ()) -> None:
    owner.execute("INSERT INTO app.perfil (codigo, nombre) VALUES (%s, %s) "
                  "ON CONFLICT (codigo) DO NOTHING", (codigo, codigo.title()))
    for rol in roles:
        owner.execute(
            "INSERT INTO app.perfil_rol (perfil_id, rol_id) SELECT pf.id, r.id FROM app.perfil pf, "
            "app.rol r WHERE pf.codigo = %s AND r.codigo = %s ON CONFLICT DO NOTHING",
            (codigo, rol),
        )


def ensure_role(owner, codigo: str, permisos: tuple[str, ...]) -> None:
    owner.execute("INSERT INTO app.rol (codigo, nombre) VALUES (%s, %s) "
                  "ON CONFLICT (codigo) DO NOTHING", (codigo, codigo.title()))
    for perm in permisos:
        owner.execute(
            "INSERT INTO app.rol_permiso (rol_id, permiso_id) SELECT r.id, p.id FROM app.rol r, "
            "app.permiso p WHERE r.codigo = %s AND p.codigo = %s ON CONFLICT DO NOTHING",
            (codigo, perm),
        )


def make_user(owner, *, perfil: str = "PRUEBA_FUNCIONAL", modulos: tuple[str, ...] = (),
              password: str = PWD, must_change: bool = False,
              estado: str = "ACTIVO") -> tuple[uuid.UUID, str]:
    ensure_profile(owner, perfil)
    uid, red = uuid7(), rand_red()
    h = hash_password(password)
    owner.execute(
        "INSERT INTO app.usuario (id, usuario_red, identificacion, nombre, primer_apellido, correo,"
        " perfil_id, estado) SELECT %s, %s, %s, 'Test', 'User', 't@x.co', id, %s "
        "FROM app.perfil WHERE codigo = %s",
        (uid, red, f"ID-{uuid.uuid4().hex[:10]}", estado, perfil),
    )
    owner.execute("INSERT INTO app.credencial (usuario_id, password_hash, debe_cambiar) "
                  "VALUES (%s, %s, %s)", (uid, h, must_change))
    owner.execute("INSERT INTO app.historial_contrasena (id, usuario_id, password_hash) "
                  "VALUES (%s, %s, %s)", (uuid7(), uid, h))
    for m in modulos:
        owner.execute("INSERT INTO app.usuario_modulo (usuario_id, modulo_id) "
                      "SELECT %s, id FROM app.modulo WHERE codigo = %s", (uid, m))
    return uid, red


def make_admin(owner, **kw) -> tuple[uuid.UUID, str]:
    """Administrador de prueba. Inactiva a los demás para respetar el máximo de 2."""
    owner.execute("UPDATE app.usuario SET estado = 'INACTIVO' WHERE estado = 'ACTIVO' AND "
                  "perfil_id = (SELECT id FROM app.perfil WHERE codigo = 'ADMINISTRADOR')")
    return make_user(owner, perfil="ADMINISTRADOR", modulos=("ADM",), **kw)


def login(c: TestClient, red: str, password: str = PWD):
    return c.post("/api/v1/auth/login", json={"usuario_red": red, "password": password})


def token(c: TestClient, red: str, password: str = PWD) -> str:
    r = login(c, red, password)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def bearer(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}
