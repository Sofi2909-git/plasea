"""Blueprint de la épica E9: Notificaciones por correo (RF-57).

El correo de resumen no tiene pantalla: se envía tras el cierre de un corte
(rutas de E5 y revisión diaria). Este módulo agrega el comando de consola
``flask enviar-resumenes-cortes`` para reintentar los pendientes.
"""

from __future__ import annotations

import click
from flask import Blueprint

from plasea.servicios import notificaciones

blueprint = Blueprint("notificaciones_correo", __name__, cli_group=None)


@blueprint.cli.command("enviar-resumenes-cortes")
def comando_enviar_resumenes() -> None:
    """Envía el resumen de los cortes cerrados que aún no lo tienen (RF-57)."""
    # Responsable: Andrés Camilo Anaya García
    # RF-57
    enviados = notificaciones.enviar_resumenes_pendientes()
    click.echo(
        "Resumen enviado: " + ", ".join(enviados)
        if enviados
        else "No hay resúmenes pendientes con alertas nuevas."
    )
