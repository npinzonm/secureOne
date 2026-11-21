"""Recorrido de las rutas de la API para las meta-pruebas de seguridad (T-SEC-00).

FastAPI ≥ 0.16x guarda los routers incluidos como objetos `_IncludedRouter` (las rutas ya no
se copian a `app.routes`); `iter_route_contexts` devuelve cada ruta con su path completo.
Se mantiene compatibilidad con versiones anteriores.
"""

from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute

MIN_EXPECTED_ROUTES = 60  # evita que una meta-prueba pase "en vacío" si cambia el framework


def api_routes(app: FastAPI) -> Iterator[tuple[str, set[str], Any]]:
    """(path completo, métodos, dependant) de cada APIRoute."""
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:  # FastAPI anterior
        for r in app.routes:
            if isinstance(r, APIRoute):
                yield r.path, set(r.methods), r.dependant
        return
    for ctx in iter_route_contexts(app.router.routes):
        if isinstance(ctx.route, APIRoute):
            yield ctx.path, set(ctx.methods or ctx.route.methods), ctx.route.dependant
