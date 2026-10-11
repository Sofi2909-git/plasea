"""Elementos web comunes: cabeceras de seguridad, páginas de error y filtros Jinja2."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Optional

from flask import Flask, Response, g, render_template
from flask_wtf.csrf import CSRFError

registro = logging.getLogger(__name__)

# Sin recursos externos (RNF: sin CDN). 'data:' cubre los íconos SVG de Bootstrap.
POLITICA_CONTENIDO = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'; "
    "object-src 'none'"
)


def formato_fecha_hora(valor: Optional[dt.datetime]) -> str:
    """Formatea fecha y hora como dd/mm/aaaa hh:mm (formato colombiano)."""
    # Responsable: Sofi Celmar Galvis (base común)
    # RNF-02
    return valor.strftime("%d/%m/%Y %H:%M") if valor else ""


def agregar_cabeceras(respuesta: Response) -> Response:
    """Agrega cabeceras de seguridad; las páginas con sesión no se guardan en caché.

    Sin caché, el botón "atrás" no muestra datos protegidos tras cerrar sesión (RF-03).
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-03
    respuesta.headers.setdefault("Content-Security-Policy", POLITICA_CONTENIDO)
    respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
    respuesta.headers.setdefault("X-Frame-Options", "DENY")
    respuesta.headers.setdefault("Referrer-Policy", "no-referrer")
    if g.get("usuario") is not None or respuesta.mimetype == "text/html":
        respuesta.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        respuesta.headers["Pragma"] = "no-cache"
        respuesta.headers["Expires"] = "0"
    return respuesta


def registrar(app: Flask) -> None:
    """Registra cabeceras, filtros y manejadores de error en la aplicación."""
    # Responsable: Sofi Celmar Galvis (base común)
    # RF-02 / RNF-01
    app.after_request(agregar_cabeceras)
    app.add_template_filter(formato_fecha_hora, "fecha_hora")

    @app.errorhandler(403)
    def acceso_denegado(_error: Any) -> tuple[str, int]:
        # Responsable: Islender Arturo Alfonso
        # RF-02
        return render_template("errores/403.html"), 403

    @app.errorhandler(404)
    def no_encontrado(_error: Any) -> tuple[str, int]:
        # Responsable: Islender Arturo Alfonso
        # RF-02
        return render_template("errores/404.html"), 404

    @app.errorhandler(CSRFError)
    def error_csrf(_error: CSRFError) -> tuple[str, int]:
        # Responsable: Islender Arturo Alfonso
        # RNF-01
        return render_template("errores/400.html"), 400

    @app.errorhandler(500)
    def error_interno(error: Any) -> tuple[str, int]:
        # Responsable: Islender Arturo Alfonso
        # RNF-01
        registro.error("Error interno: %s", error)
        return render_template("errores/500.html"), 500
