"""Blueprint de la épica E12: Ayuda e información (RF-62 y RF-63)."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, render_template

from plasea.autorizacion import login_requerido

blueprint = Blueprint("ayuda_informacion", __name__)


@blueprint.get("/acerca")
@login_requerido
def acerca() -> Any:
    """Información general y alcance de PLASEA para usuarios autenticados (RF-62)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-62
    return render_template("ayuda/acerca.html")


@blueprint.get("/politicas")
def politicas() -> Any:
    """Políticas de datos y de uso, visibles sin iniciar sesión (RF-63)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-63
    return render_template("ayuda/politicas.html")
