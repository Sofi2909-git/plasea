"""Umbrales de alerta configurables con histórico (RF-20).

Cada cambio agrega una fila nueva en ``configuraciones_alerta``; la vigente es la
más reciente. Las alertas guardan la versión con la que se calcularon, por eso un
cambio no recalcula las alertas de cortes ya cerrados.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from plasea.modelos import ConfiguracionAlerta, db
from plasea.servicios import bitacora
from plasea.servicios.comunes import ErrorNegocio, ahora

NOTA_MINIMA, NOTA_MAXIMA = Decimal("1.0"), Decimal("5.0")
UN_DECIMAL = Decimal("0.1")
DOS_DECIMALES = Decimal("0.01")


@dataclass(frozen=True)
class DatosUmbrales:
    """Valores configurables de RF-20."""

    nota_aprobacion: Decimal
    limite_perdida_inasistencia: Decimal
    umbral_amarillo_inasistencia: Decimal
    nota_amarilla_minima: Decimal
    nota_amarilla_maxima: Decimal


def configuracion_vigente() -> Optional[ConfiguracionAlerta]:
    """Devuelve la configuración de umbrales vigente (la más reciente)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-20
    return db.session.scalar(
        select(ConfiguracionAlerta)
        .order_by(
            ConfiguracionAlerta.vigente_desde.desc(), ConfiguracionAlerta.id.desc()
        )
        .limit(1)
    )


def historial_configuraciones(limite: int = 50) -> list[ConfiguracionAlerta]:
    """Versiones anteriores de los umbrales, de la más reciente a la más antigua."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-20
    return list(
        db.session.scalars(
            select(ConfiguracionAlerta)
            .options(joinedload(ConfiguracionAlerta.creado_por))
            .order_by(
                ConfiguracionAlerta.vigente_desde.desc(), ConfiguracionAlerta.id.desc()
            )
            .limit(limite)
        )
    )


def _con_escala(valor: Decimal, escala: Decimal, nombre: str) -> Decimal:
    """Verifica que el valor no tenga más decimales de los permitidos."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-20
    if valor != valor.quantize(escala):
        decimales = "un decimal" if escala == UN_DECIMAL else "dos decimales"
        raise ErrorNegocio(f"{nombre} admite como máximo {decimales}.")
    return valor.quantize(escala)


def validar_umbrales(datos: DatosUmbrales) -> DatosUmbrales:
    """Valida los umbrales con las mismas reglas que la base de datos.

    Raises:
        ErrorNegocio: si algún valor está fuera de rango o es incoherente.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-20
    nota = _con_escala(datos.nota_aprobacion, UN_DECIMAL, "La nota de aprobación")
    limite = _con_escala(
        datos.limite_perdida_inasistencia, DOS_DECIMALES, "El límite de inasistencia"
    )
    amarillo = _con_escala(
        datos.umbral_amarillo_inasistencia, DOS_DECIMALES, "El umbral amarillo"
    )
    minima = _con_escala(
        datos.nota_amarilla_minima, UN_DECIMAL, "La nota amarilla mínima"
    )
    maxima = _con_escala(
        datos.nota_amarilla_maxima, UN_DECIMAL, "La nota amarilla máxima"
    )
    for valor, nombre in (
        (nota, "La nota de aprobación"),
        (minima, "La nota amarilla mínima"),
        (maxima, "La nota amarilla máxima"),
    ):
        if not NOTA_MINIMA <= valor <= NOTA_MAXIMA:
            raise ErrorNegocio(f"{nombre} debe estar entre 1,0 y 5,0.")
    if minima > maxima:
        raise ErrorNegocio(
            "En el rango amarillo, la nota mínima no puede superar la máxima."
        )
    if not Decimal("0") < amarillo < limite <= Decimal("100"):
        raise ErrorNegocio(
            "El umbral amarillo de inasistencia debe ser mayor que 0 % y menor que el "
            "límite de pérdida, y el límite no puede superar 100 %."
        )
    return DatosUmbrales(nota, limite, amarillo, minima, maxima)


def guardar_umbrales(datos: DatosUmbrales, actor_id: int) -> ConfiguracionAlerta:
    """Registra una nueva versión de los umbrales (RF-20). La anterior se conserva."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-20
    try:
        datos = validar_umbrales(datos)
        vigente = configuracion_vigente()
        if vigente is not None and (
            vigente.nota_aprobacion,
            vigente.limite_perdida_inasistencia,
            vigente.umbral_amarillo_inasistencia,
            vigente.nota_amarilla_minima,
            vigente.nota_amarilla_maxima,
        ) == tuple(datos.__dict__.values()):
            raise ErrorNegocio(
                "Los valores son iguales a los vigentes; no hay cambios."
            )
        configuracion = ConfiguracionAlerta(
            **datos.__dict__, vigente_desde=ahora(), creado_por_usuario_id=actor_id
        )
        db.session.add(configuracion)
        db.session.flush()
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="configuraciones_alerta",
            entidad_id=configuracion.id,
            detalle="Nueva versión de los umbrales de alerta",
        )
        db.session.commit()
        return configuracion
    except Exception:
        db.session.rollback()
        raise
