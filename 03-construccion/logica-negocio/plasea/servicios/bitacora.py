"""Registro de eventos en la bitácora (RF-61).

La bitácora es de solo inserción: la base de datos tiene triggers que impiden
modificarla o eliminarla. El evento se agrega a la transacción en curso, de modo
que queda guardado solo si la operación que lo origina se confirma.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from plasea.modelos import Bitacora, TipoEventoBitacora, db

# Códigos del catálogo tipos_evento_bitacora (bd_datos_iniciales.sql).
EVENTO_INICIO_SESION = "inicio_sesion"
EVENTO_CIERRE_SESION = "cierre_sesion"
EVENTO_INTENTO_FALLIDO = "intento_fallido"
EVENTO_CAMBIO_ADMINISTRATIVO = "cambio_administrativo"

_LONGITUD_DETALLE = 1000


def registrar_evento(
    codigo_evento: str,
    usuario_id: Optional[int] = None,
    entidad: Optional[str] = None,
    entidad_id: Optional[int] = None,
    detalle: Optional[str] = None,
) -> None:
    """Agrega un evento a la bitácora dentro de la transacción actual.

    Args:
        codigo_evento: código del catálogo ``tipos_evento_bitacora``.
        usuario_id: usuario que origina el evento; ``None`` = el Sistema o un
            intento con correo no registrado.
        entidad: nombre de la tabla afectada.
        entidad_id: identificador del registro afectado.
        detalle: texto breve. Nunca contraseñas, tokens ni datos sensibles.

    Raises:
        LookupError: si el código no existe en el catálogo.
    """
    # Responsable: Sofi Celmar Galvis
    # RF-61
    tipo_id = db.session.scalar(
        select(TipoEventoBitacora.id).where(TipoEventoBitacora.codigo == codigo_evento)
    )
    if tipo_id is None:
        raise LookupError(f"Tipo de evento de bitácora no registrado: {codigo_evento}")
    db.session.add(
        Bitacora(
            tipo_evento_id=tipo_id,
            usuario_id=usuario_id,
            entidad=entidad,
            entidad_id=entidad_id,
            detalle=detalle[:_LONGITUD_DETALLE] if detalle else None,
        )
    )
