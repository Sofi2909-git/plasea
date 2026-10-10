"""Utilidades comunes de la capa de servicios: hora oficial y errores de negocio."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

ZONA_BOGOTA = ZoneInfo("America/Bogota")


class ErrorNegocio(Exception):
    """Regla de negocio incumplida. El mensaje es apto para mostrarse al usuario."""

    def __init__(self, mensaje: str) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje


def ahora() -> dt.datetime:
    """Devuelve la fecha y hora actual de Colombia sin zona (formato de la BD).

    La base de datos guarda DATETIME en hora de Colombia (UTC-5), por eso toda
    comparación de fechas en la aplicación usa esta función.
    """
    # Responsable: Sofi Celmar Galvis (base común)
    # RF-04 / RF-05
    return dt.datetime.now(ZONA_BOGOTA).replace(tzinfo=None, microsecond=0)
