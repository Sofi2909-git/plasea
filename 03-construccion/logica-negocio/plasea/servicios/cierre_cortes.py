"""Seguimiento y cierre de cortes, reaperturas excepcionales (RF-35 a RF-39).

- RF-35: cursos enviados y pendientes de un corte, con su profesor.
- RF-36: cierre manual del Auditor académico antes del límite de corrección.
- RF-37: cierre automático al vencer el límite de corrección (misma regla).
- RF-38: reapertura de un curso de un corte cerrado, con motivo obligatorio.
- RF-39: cierre manual de la reapertura.

Al cerrar: ningún profesor modifica el corte, los cursos enviados quedan
"cerrado", los no enviados "sin_registro" y las alertas pasan a definitivas.
El correo de resumen (RF-57) lo envía otro módulo: el cierre deja
``aviso_resumen_enviado_en`` vacío para que lo detecte.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.orm import aliased

from plasea.modelos import (
    Asignatura,
    Corte,
    Curso,
    PeriodoAcademico,
    ReaperturaCurso,
    RegistroCursoCorte,
    Usuario,
    db,
)
from plasea.servicios import alertas, bitacora
from plasea.servicios.comunes import ErrorNegocio, ahora

EVENTO_CIERRE = "cierre_corte"
EVENTO_REAPERTURA = "reapertura"
EVENTO_CIERRE_REAPERTURA = "cierre_reapertura"
SIN_REGISTRO = "sin_registro"
NOMBRES_ESTADO_REGISTRO = {
    "pendiente": "Pendiente",
    "enviado": "Enviado",
    "cerrado": "Cerrado",
    SIN_REGISTRO: "Sin registro",
}
MOTIVO_MINIMO, MOTIVO_MAXIMO = 10, 500

registro_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FilaSeguimiento:
    """Un curso en el seguimiento del corte (RF-35)."""

    curso: Curso
    asignatura: Asignatura
    profesor: str
    estado: str
    enviado_en: Optional[dt.datetime]
    registro_id: Optional[int]
    reapertura: Optional[ReaperturaCurso]

    @property
    def nombre_estado(self) -> str:
        """Nombre visible del estado del registro."""
        return NOMBRES_ESTADO_REGISTRO[self.estado]


def _hoy() -> dt.date:
    """Fecha actual de Colombia."""
    # Responsable: Islender Arturo Alfonso
    # RF-37
    return ahora().date()


def corte_actual(periodo: PeriodoAcademico) -> Optional[Corte]:
    """Corte que conviene mostrar: el abierto más antiguo, o el último cerrado."""
    # Responsable: Islender Arturo Alfonso
    # RF-35
    cortes = sorted(periodo.cortes, key=lambda c: c.numero)
    hoy = _hoy()
    for corte in cortes:
        if corte.cerrado_en is None and corte.fecha_inicio <= hoy:
            return corte
    cerrados = [c for c in cortes if c.cerrado_en is not None]
    return cerrados[-1] if cerrados else (cortes[0] if cortes else None)


def seguimiento(corte: Corte, solo_pendientes: bool = False) -> list[FilaSeguimiento]:
    """Cursos del período con el estado de su registro en el corte (RF-35).

    Una sola consulta con uniones externas al registro y a la reapertura
    vigente; ``solo_pendientes`` deja los que no se han enviado.
    """
    # Responsable: Islender Arturo Alfonso
    # RF-35
    profesor = aliased(Usuario)
    reapertura = aliased(ReaperturaCurso)
    consulta = (
        select(
            Curso, Asignatura, profesor.nombre_completo, RegistroCursoCorte, reapertura
        )
        .join(Asignatura, Asignatura.id == Curso.asignatura_id)
        .join(profesor, profesor.id == Curso.profesor_usuario_id)
        .outerjoin(
            RegistroCursoCorte,
            and_(
                RegistroCursoCorte.curso_id == Curso.id,
                RegistroCursoCorte.corte_id == corte.id,
            ),
        )
        .outerjoin(
            reapertura,
            and_(
                reapertura.registro_curso_corte_id == RegistroCursoCorte.id,
                reapertura.cerrada_en.is_(None),
            ),
        )
        .where(Curso.periodo_academico_id == corte.periodo_academico_id)
        .order_by(Asignatura.nombre, Curso.codigo)
    )
    filas: list[FilaSeguimiento] = []
    for curso, asignatura, nombre, registro, abierta in db.session.execute(consulta):
        estado = (
            registro.estado
            if registro
            else (SIN_REGISTRO if corte.cerrado_en else "pendiente")
        )
        if solo_pendientes and estado != "pendiente":
            continue
        filas.append(
            FilaSeguimiento(
                curso=curso,
                asignatura=asignatura,
                profesor=nombre,
                estado=estado,
                enviado_en=registro.enviado_en if registro else None,
                registro_id=registro.id if registro else None,
                reapertura=abierta,
            )
        )
    return filas


def resumen_seguimiento(corte: Corte) -> dict[str, int]:
    """Totales por estado del registro en el corte (RF-35)."""
    # Responsable: Islender Arturo Alfonso
    # RF-35
    totales = {estado: 0 for estado in NOMBRES_ESTADO_REGISTRO}
    for fila in seguimiento(corte):
        totales[fila.estado] += 1
    totales["total"] = sum(totales.values())
    return totales


def motivo_no_cierre(corte: Corte, hoy: dt.date) -> Optional[str]:
    """Por qué el Auditor no puede cerrar el corte ahora; ``None`` si puede."""
    # Responsable: Islender Arturo Alfonso
    # RF-36
    if corte.cerrado_en is not None:
        return f"El corte {corte.numero} ya está cerrado."
    if hoy < corte.fecha_fin:
        return (
            f"El corte {corte.numero} termina el {corte.fecha_fin:%d/%m/%Y}; se puede "
            "cerrar desde esa fecha."
        )
    return None


def _cerrar(corte: Corte, tipo: str, actor_id: Optional[int]) -> dict[str, int]:
    """Aplica la regla común de cierre de RF-36 y RF-37 (sin confirmar)."""
    # Responsable: Islender Arturo Alfonso
    # RF-36
    registros = {
        r.curso_id: r
        for r in db.session.scalars(
            select(RegistroCursoCorte).where(RegistroCursoCorte.corte_id == corte.id)
        )
    }
    cursos = db.session.scalars(
        select(Curso.id).where(Curso.periodo_academico_id == corte.periodo_academico_id)
    ).all()
    cerrados = sin_registro = 0
    for curso_id in cursos:
        registro = registros.get(curso_id)
        if registro is None:
            db.session.add(
                RegistroCursoCorte(
                    curso_id=curso_id, corte_id=corte.id, estado=SIN_REGISTRO
                )
            )
            sin_registro += 1
        elif registro.estado == "enviado":
            registro.estado = "cerrado"
            cerrados += 1
        elif registro.estado == "pendiente":
            registro.estado = SIN_REGISTRO
            sin_registro += 1
    corte.cerrado_en = ahora()
    corte.tipo_cierre = tipo
    corte.cerrado_por_usuario_id = actor_id
    db.session.flush()
    calculadas = alertas.recalcular(corte)
    bitacora.registrar_evento(
        EVENTO_CIERRE,
        usuario_id=actor_id,
        entidad="cortes",
        entidad_id=corte.id,
        detalle=(
            f"Cierre {tipo} del corte {corte.numero} de "
            f"{corte.periodo_academico.identificador}: {cerrados} enviados, "
            f"{sin_registro} sin registro, {calculadas} alertas definitivas"
        ),
    )
    return {"cerrados": cerrados, "sin_registro": sin_registro, "alertas": calculadas}


def cerrar_corte(corte_id: int, actor_id: int) -> dict[str, int]:
    """Cierre manual del corte por el Auditor académico (RF-36)."""
    # Responsable: Islender Arturo Alfonso
    # RF-36
    try:
        corte = db.session.get(Corte, corte_id)
        if corte is None:
            raise ErrorNegocio("El corte no existe.")
        motivo = motivo_no_cierre(corte, _hoy())
        if motivo:
            raise ErrorNegocio(motivo)
        resultado = _cerrar(corte, "manual", actor_id)
        db.session.commit()
        return resultado
    except Exception:
        db.session.rollback()
        raise


def cerrar_vencidos() -> list[str]:
    """Cierra los cortes con el límite de corrección vencido (RF-37).

    Es idempotente: un corte ya cerrado no se vuelve a cerrar. Cada corte se
    confirma por separado para que un fallo no deshaga los demás.

    Returns:
        Descripción de los cortes cerrados.
    """
    # Responsable: Islender Arturo Alfonso
    # RF-37
    vencidos = db.session.scalars(
        select(Corte)
        .where(Corte.cerrado_en.is_(None), Corte.limite_correccion < _hoy())
        .order_by(Corte.limite_correccion)
    ).all()
    cerrados: list[str] = []
    for corte in vencidos:
        try:
            _cerrar(corte, "automatico", None)
            db.session.commit()
        except Exception:
            db.session.rollback()
            registro_log.exception("No se pudo cerrar el corte %s", corte.id)
            continue
        cerrados.append(f"{corte.periodo_academico.identificador} corte {corte.numero}")
    return cerrados


# ---------------------------------------------------------------------------
# RF-38 y RF-39: reapertura excepcional
# ---------------------------------------------------------------------------


def obtener_registro(registro_id: int) -> RegistroCursoCorte:
    """Registro curso-corte con curso, asignatura y corte."""
    # Responsable: Islender Arturo Alfonso
    # RF-38
    registro = db.session.get(RegistroCursoCorte, registro_id)
    if registro is None:
        raise ErrorNegocio("El registro del curso no existe.")
    return registro


def reabrir(registro_id: int, motivo: str, actor_id: int) -> ReaperturaCurso:
    """Reabre un curso de un corte cerrado por falla técnica (RF-38)."""
    # Responsable: Islender Arturo Alfonso
    # RF-38
    try:
        registro = obtener_registro(registro_id)
        if registro.corte.cerrado_en is None:
            raise ErrorNegocio(
                "Solo se reabre un curso de un corte cerrado; mientras el corte esté "
                "abierto el profesor corrige con motivo."
            )
        limpio = " ".join((motivo or "").split())
        if not MOTIVO_MINIMO <= len(limpio) <= MOTIVO_MAXIMO:
            raise ErrorNegocio(
                "Escriba el motivo de la reapertura (10 a 500 caracteres)."
            )
        vigente = db.session.scalar(
            select(func.count(ReaperturaCurso.id)).where(
                ReaperturaCurso.registro_curso_corte_id == registro.id,
                ReaperturaCurso.cerrada_en.is_(None),
            )
        )
        if vigente:
            raise ErrorNegocio(
                "Este curso ya tiene una reapertura vigente en el corte."
            )
        reapertura = ReaperturaCurso(
            registro_curso_corte_id=registro.id,
            motivo=limpio,
            abierta_por_usuario_id=actor_id,
            abierta_en=ahora(),
        )
        db.session.add(reapertura)
        db.session.flush()
        bitacora.registrar_evento(
            EVENTO_REAPERTURA,
            usuario_id=actor_id,
            entidad="reaperturas_curso",
            entidad_id=reapertura.id,
            detalle=(
                f"Reapertura de {registro.curso.asignatura.codigo} "
                f"{registro.curso.codigo}, corte {registro.corte.numero}: {limpio}"
            ),
        )
        db.session.commit()
        return reapertura
    except Exception:
        db.session.rollback()
        raise


def cerrar_reapertura(reapertura_id: int, actor_id: int) -> ReaperturaCurso:
    """Cierra una reapertura: el curso se bloquea y se recalculan alertas (RF-39)."""
    # Responsable: Islender Arturo Alfonso
    # RF-39
    try:
        reapertura = db.session.get(ReaperturaCurso, reapertura_id)
        if reapertura is None:
            raise ErrorNegocio("La reapertura no existe.")
        if reapertura.cerrada_en is not None:
            raise ErrorNegocio("La reapertura ya estaba cerrada.")
        reapertura.cerrada_en = ahora()
        reapertura.cerrada_por_usuario_id = actor_id
        db.session.flush()
        registro = reapertura.registro_curso_corte
        alertas.recalcular_curso(registro.curso_id, registro.corte.numero)
        bitacora.registrar_evento(
            EVENTO_CIERRE_REAPERTURA,
            usuario_id=actor_id,
            entidad="reaperturas_curso",
            entidad_id=reapertura.id,
            detalle=(
                f"Cierre de la reapertura de {registro.curso.asignatura.codigo} "
                f"{registro.curso.codigo}, corte {registro.corte.numero}"
            ),
        )
        db.session.commit()
        return reapertura
    except Exception:
        db.session.rollback()
        raise


def reaperturas_del_corte(corte: Corte) -> list[ReaperturaCurso]:
    """Reaperturas del corte (vigentes y cerradas), la más reciente primero."""
    # Responsable: Islender Arturo Alfonso
    # RF-38
    return list(
        db.session.scalars(
            select(ReaperturaCurso)
            .join(
                RegistroCursoCorte,
                RegistroCursoCorte.id == ReaperturaCurso.registro_curso_corte_id,
            )
            .where(RegistroCursoCorte.corte_id == corte.id)
            .order_by(ReaperturaCurso.abierta_en.desc())
        )
    )
