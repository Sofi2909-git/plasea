"""Correo de resumen al cerrarse un corte con alertas nuevas (RF-57).

Al cerrarse un corte (manual, RF-36, o automático, RF-37) se envía a cada
Auditor académico con cuenta activa un resumen con el número de alertas
amarillas, rojas y de riesgo alto del corte, y el enlace a la lista de RF-44.

- Una sola vez por corte: el corte se "reclama" con una actualización
  condicionada (``aviso_resumen_enviado_en IS NULL``) antes de enviar, así dos
  procesos simultáneos no envían dos correos.
- Alertas nuevas: alerta amarilla o roja de una inscripción que en el corte
  anterior estaba en verde o no tenía alerta. En el corte 1 todas son nuevas.
  Si el corte cierra sin alertas nuevas, se marca como revisado y no se envía.
- Un fallo de envío no rompe el cierre: queda en el log (``servicios/correo``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from flask import current_app, render_template
from sqlalchemy import func, select, update
from sqlalchemy.orm import aliased

from plasea.modelos import Alerta, Corte, Rol, Usuario, db
from plasea.servicios import alertas
from plasea.servicios.comunes import ahora
from plasea.servicios.correo import enviar_correo
from plasea.servicios.cuentas import ESTADO_ACTIVA, ROL_AUDITOR

registro_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResumenCierre:
    """Cifras del correo de un corte cerrado (RF-57)."""

    corte: Corte
    amarillas: int
    rojas: int
    riesgo_alto: int
    nuevas: int


def alertas_nuevas(corte: Corte) -> int:
    """Alertas amarillas o rojas del corte que no lo eran en el corte anterior."""
    # Responsable: Andrés Camilo Anaya García
    # RF-57
    anterior = next(
        (c for c in corte.periodo_academico.cortes if c.numero == corte.numero - 1),
        None,
    )
    consulta = select(func.count(Alerta.id)).where(
        Alerta.corte_id == corte.id, Alerta.estado_alerta.in_(alertas.TIPOS)
    )
    if anterior is not None:
        previa = aliased(Alerta)
        consulta = consulta.where(
            ~select(previa.id)
            .where(
                previa.inscripcion_id == Alerta.inscripcion_id,
                previa.corte_id == anterior.id,
                previa.estado_alerta.in_(alertas.TIPOS),
            )
            .exists()
        )
    return int(db.session.scalar(consulta) or 0)


def resumen_cierre(corte: Corte) -> ResumenCierre:
    """Cifras del correo: las mismas de la franja de RF-44 más las nuevas."""
    # Responsable: Andrés Camilo Anaya García
    # RF-57
    resumen = alertas.resumen_corte(corte)
    return ResumenCierre(
        corte,
        amarillas=resumen["amarilla"],
        rojas=resumen["roja"],
        riesgo_alto=resumen["riesgo_alto"],
        nuevas=alertas_nuevas(corte),
    )


def destinatarios() -> list[Usuario]:
    """Auditores académicos con cuenta activa."""
    # Responsable: Andrés Camilo Anaya García
    # RF-57
    return list(
        db.session.scalars(
            select(Usuario)
            .join(Rol, Rol.id == Usuario.rol_id)
            .where(Rol.codigo == ROL_AUDITOR, Usuario.estado_cuenta == ESTADO_ACTIVA)
            .order_by(Usuario.id)
        )
    )


def enlace_alertas(corte: Corte) -> str:
    """URL absoluta de la lista de alertas del corte (RF-44).

    Se arma con el mapa de rutas para que funcione también fuera de una
    petición (planificador diario o comando de consola).
    """
    # Responsable: Andrés Camilo Anaya García
    # RF-57
    base = current_app.config["URL_BASE_ENLACES"].rstrip("/")
    ruta = current_app.url_map.bind("localhost").build(
        "alertas_analitica.lista",
        {"periodo": corte.periodo_academico_id, "corte": corte.numero},
    )
    return base + ruta


def _reclamar(corte_id: int) -> bool:
    """Marca el aviso del corte como atendido si nadie lo hizo antes."""
    # Responsable: Andrés Camilo Anaya García
    # RF-57
    resultado = db.session.execute(
        update(Corte)
        .where(
            Corte.id == corte_id,
            Corte.cerrado_en.is_not(None),
            Corte.aviso_resumen_enviado_en.is_(None),
        )
        .values(aviso_resumen_enviado_en=ahora())
        .execution_options(synchronize_session=False)
    )
    db.session.commit()
    return resultado.rowcount == 1


def enviar_resumen(corte: Corte) -> bool:
    """Envía el resumen de un corte cerrado si tiene alertas nuevas.

    Returns:
        ``True`` si se envió el correo.
    """
    # Responsable: Andrés Camilo Anaya García
    # RF-57
    if not _reclamar(corte.id):
        return False
    db.session.refresh(corte)
    resumen = resumen_cierre(corte)
    if resumen.nuevas == 0:
        registro_log.info(
            "Corte %s cerrado sin alertas nuevas: no se envía resumen.", corte.id
        )
        return False
    lista = destinatarios()
    if not lista:
        registro_log.warning("No hay auditores activos para el resumen de RF-57.")
        return False
    periodo = corte.periodo_academico.identificador
    asunto = f"PLASEA: cierre del corte {corte.numero} de {periodo}"
    enlace = enlace_alertas(corte)
    for usuario in lista:
        cuerpo = render_template(
            "correos/resumen_cierre_corte.txt",
            nombre=usuario.nombre_completo,
            resumen=resumen,
            periodo=periodo,
            enlace=enlace,
        )
        enviar_correo(usuario.correo, asunto, cuerpo)
    return True


def enviar_resumenes_pendientes() -> list[str]:
    """Envía los resúmenes de los cortes cerrados que aún no lo tienen (RF-57).

    Es idempotente: se llama tras cada cierre, al arrancar y en la revisión
    diaria. Un fallo en un corte no impide los demás.

    Returns:
        Descripción de los cortes cuyo resumen se envió.
    """
    # Responsable: Andrés Camilo Anaya García
    # RF-57
    pendientes = db.session.scalars(
        select(Corte)
        .where(Corte.cerrado_en.is_not(None), Corte.aviso_resumen_enviado_en.is_(None))
        .order_by(Corte.cerrado_en)
    ).all()
    enviados: list[str] = []
    for corte in pendientes:
        try:
            if enviar_resumen(corte):
                enviados.append(
                    f"{corte.periodo_academico.identificador} corte {corte.numero}"
                )
        except Exception:
            db.session.rollback()
            registro_log.exception(
                "No se pudo enviar el resumen del corte %s", corte.id
            )
    return enviados
