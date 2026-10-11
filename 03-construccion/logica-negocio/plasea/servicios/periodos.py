"""Períodos académicos, cortes y festivos (RF-16, RF-17 y RF-18).

Cada cambio queda en la bitácora como ``cambio_administrativo`` (RF-61). Los
cambios de fechas o festivos regeneran los calendarios de los cursos que aún no
tienen asistencia (RF-19).
"""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select

from plasea.modelos import Corte, Curso, Festivo, PeriodoAcademico, db
from plasea.servicios import bitacora, calendario
from plasea.servicios.comunes import ErrorNegocio

SEMANAS_PERIODO = 16
NUMERO_CORTES = 3
PESOS_POR_DEFECTO = (Decimal("30.00"), Decimal("30.00"), Decimal("40.00"))
_PATRON_PERIODO = re.compile(r"^\d{4}-[12]$")


@dataclass(frozen=True)
class DatosPeriodo:
    """Datos editables de un período académico (RF-16)."""

    identificador: str
    fecha_inicio: dt.date
    fecha_fin: dt.date


@dataclass(frozen=True)
class DatosCorte:
    """Datos de un corte (RF-17)."""

    numero: int
    peso_porcentaje: Decimal
    fecha_inicio: dt.date
    fecha_fin: dt.date
    limite_carga: dt.date
    limite_correccion: dt.date


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------


def listar_periodos() -> list[PeriodoAcademico]:
    """Lista los períodos del más reciente al más antiguo."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-16
    return list(
        db.session.scalars(
            select(PeriodoAcademico).order_by(PeriodoAcademico.fecha_inicio.desc())
        )
    )


def obtener_periodo(periodo_id: int) -> PeriodoAcademico:
    """Devuelve el período o lanza ``ErrorNegocio`` si no existe."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-16
    periodo = db.session.get(PeriodoAcademico, periodo_id)
    if periodo is None:
        raise ErrorNegocio("El período solicitado no existe.")
    return periodo


def periodo_en_curso() -> Optional[PeriodoAcademico]:
    """Devuelve el período marcado como en curso, si hay uno."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-16
    return db.session.scalar(
        select(PeriodoAcademico).where(PeriodoAcademico.en_curso_marca == 1)
    )


def semanas_calendario(fecha_inicio: dt.date, fecha_fin: dt.date) -> int:
    """Número de semanas calendario que abarca el rango (incluye semana parcial)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-16
    return math.ceil(((fecha_fin - fecha_inicio).days + 1) / 7)


# ---------------------------------------------------------------------------
# RF-16: períodos
# ---------------------------------------------------------------------------


def _validar_periodo(datos: DatosPeriodo, excluir_id: Optional[int] = None) -> str:
    """Valida identificador único, orden de fechas y duración de 16 semanas."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-16
    identificador = datos.identificador.strip()
    if not _PATRON_PERIODO.match(identificador):
        raise ErrorNegocio("El identificador debe tener la forma AAAA-1 o AAAA-2.")
    if datos.fecha_fin <= datos.fecha_inicio:
        raise ErrorNegocio("La fecha de fin debe ser posterior a la de inicio.")
    if semanas_calendario(datos.fecha_inicio, datos.fecha_fin) != SEMANAS_PERIODO:
        raise ErrorNegocio(
            f"El período debe durar {SEMANAS_PERIODO} semanas: la fecha de fin "
            f"debe caer en la semana {SEMANAS_PERIODO} contada desde el inicio."
        )
    consulta = select(PeriodoAcademico.id).where(
        PeriodoAcademico.identificador == identificador
    )
    if excluir_id is not None:
        consulta = consulta.where(PeriodoAcademico.id != excluir_id)
    if db.session.scalar(consulta) is not None:
        raise ErrorNegocio(f"Ya existe el período {identificador}.")
    return identificador


def crear_periodo(datos: DatosPeriodo, actor_id: int) -> PeriodoAcademico:
    """Registra un período académico (RF-16)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-16
    try:
        identificador = _validar_periodo(datos)
        periodo = PeriodoAcademico(
            identificador=identificador,
            fecha_inicio=datos.fecha_inicio,
            fecha_fin=datos.fecha_fin,
        )
        db.session.add(periodo)
        db.session.flush()
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="periodos_academicos",
            entidad_id=periodo.id,
            detalle=f"Registro del período {identificador}",
        )
        db.session.commit()
        return periodo
    except Exception:
        db.session.rollback()
        raise


def modificar_periodo(
    periodo_id: int, datos: DatosPeriodo, actor_id: int
) -> tuple[PeriodoAcademico, int]:
    """Modifica identificador y fechas de un período (RF-16).

    Las fechas solo cambian si ningún curso del período tiene asistencia, y los
    cortes y festivos existentes deben quedar dentro de las nuevas fechas.

    Returns:
        (período, cursos cuyo calendario se regeneró).
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-16
    try:
        periodo = obtener_periodo(periodo_id)
        identificador = _validar_periodo(datos, excluir_id=periodo.id)
        cambian_fechas = (datos.fecha_inicio, datos.fecha_fin) != (
            periodo.fecha_inicio,
            periodo.fecha_fin,
        )
        regenerados = 0
        if cambian_fechas:
            _verificar_sin_asistencia(periodo.id)
            for corte in periodo.cortes:
                if (
                    corte.fecha_inicio < datos.fecha_inicio
                    or corte.fecha_fin > datos.fecha_fin
                ):
                    raise ErrorNegocio(
                        f"El corte {corte.numero} quedaría fuera de las nuevas "
                        "fechas. Ajuste primero los cortes."
                    )
            for festivo in periodo.festivos:
                if not datos.fecha_inicio <= festivo.fecha <= datos.fecha_fin:
                    raise ErrorNegocio(
                        "Hay festivos fuera de las nuevas fechas. Elimínelos primero."
                    )
        periodo.identificador = identificador
        periodo.fecha_inicio = datos.fecha_inicio
        periodo.fecha_fin = datos.fecha_fin
        if cambian_fechas:
            db.session.flush()
            regenerados, _ = calendario.regenerar_calendarios_periodo(periodo.id)
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="periodos_academicos",
            entidad_id=periodo.id,
            detalle=f"Modificación del período {identificador}",
        )
        db.session.commit()
        return periodo, regenerados
    except Exception:
        db.session.rollback()
        raise


def marcar_en_curso(periodo_id: int, actor_id: int) -> PeriodoAcademico:
    """Marca el período como en curso; solo uno puede estarlo (RF-16)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-16
    try:
        periodo = obtener_periodo(periodo_id)
        anterior = periodo_en_curso()
        if anterior is not None and anterior.id != periodo.id:
            anterior.en_curso_marca = None
            db.session.flush()
        periodo.en_curso_marca = 1
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="periodos_academicos",
            entidad_id=periodo.id,
            detalle=f"Período {periodo.identificador} marcado en curso",
        )
        db.session.commit()
        return periodo
    except Exception:
        db.session.rollback()
        raise


def _verificar_sin_asistencia(periodo_id: int) -> None:
    """Impide cambios de fechas cuando algún curso del período tiene asistencia."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-16 / RF-19
    cursos = db.session.scalars(
        select(Curso.id).where(Curso.periodo_academico_id == periodo_id)
    ).all()
    if any(calendario.curso_tiene_asistencia(curso_id) for curso_id in cursos):
        raise ErrorNegocio(
            "No se pueden cambiar las fechas: hay cursos con asistencia registrada."
        )


# ---------------------------------------------------------------------------
# RF-17: cortes
# ---------------------------------------------------------------------------


def cortes_sugeridos(periodo: PeriodoAcademico) -> list[DatosCorte]:
    """Propone los 3 cortes (semanas 1-5, 6-10 y 11-16) con pesos 30, 30 y 40."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-17
    inicio = periodo.fecha_inicio
    limites = (
        (inicio, inicio + dt.timedelta(weeks=5, days=-1)),
        (inicio + dt.timedelta(weeks=5), inicio + dt.timedelta(weeks=10, days=-1)),
        (inicio + dt.timedelta(weeks=10), periodo.fecha_fin),
    )
    return [
        DatosCorte(
            numero=numero,
            peso_porcentaje=PESOS_POR_DEFECTO[numero - 1],
            fecha_inicio=desde,
            fecha_fin=hasta,
            limite_carga=hasta + dt.timedelta(days=3),
            limite_correccion=hasta + dt.timedelta(days=7),
        )
        for numero, (desde, hasta) in enumerate(limites, start=1)
    ]


def validar_cortes(periodo: PeriodoAcademico, cortes: list[DatosCorte]) -> None:
    """Aplica las reglas de RF-17 a los 3 cortes de un período.

    Reglas: pesos que suman 100 %, cortes en orden y sin solaparse, inicio y fin
    dentro del período, límite de carga desde el fin del corte y límite de
    corrección posterior al de carga.

    Raises:
        ErrorNegocio: con la primera regla incumplida.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-17
    if sorted(c.numero for c in cortes) != list(range(1, NUMERO_CORTES + 1)):
        raise ErrorNegocio("Se deben definir exactamente los cortes 1, 2 y 3.")
    ordenados = sorted(cortes, key=lambda c: c.numero)
    if any(c.peso_porcentaje <= 0 for c in ordenados):
        raise ErrorNegocio("Cada corte debe tener un peso mayor que 0 %.")
    if sum(c.peso_porcentaje for c in ordenados) != Decimal("100"):
        raise ErrorNegocio("Los pesos de los 3 cortes deben sumar 100 %.")
    anterior: Optional[DatosCorte] = None
    for corte in ordenados:
        etiqueta = f"Corte {corte.numero}"
        if corte.fecha_inicio > corte.fecha_fin:
            raise ErrorNegocio(f"{etiqueta}: la fecha de inicio supera la de fin.")
        if (
            corte.fecha_inicio < periodo.fecha_inicio
            or corte.fecha_fin > periodo.fecha_fin
        ):
            raise ErrorNegocio(
                f"{etiqueta}: sus fechas deben estar dentro del período."
            )
        if anterior is not None and corte.fecha_inicio <= anterior.fecha_fin:
            raise ErrorNegocio(
                f"{etiqueta}: debe empezar después del fin del corte {anterior.numero}."
            )
        if corte.limite_carga < corte.fecha_fin:
            raise ErrorNegocio(
                f"{etiqueta}: el límite de carga no puede ser anterior al fin "
                "del corte."
            )
        if corte.limite_correccion <= corte.limite_carga:
            raise ErrorNegocio(
                f"{etiqueta}: el límite de corrección debe ser posterior al de carga."
            )
        anterior = corte


def guardar_cortes(
    periodo_id: int, cortes: list[DatosCorte], actor_id: int
) -> PeriodoAcademico:
    """Crea o modifica los 3 cortes de un período (RF-17); el cerrado no cambia."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-17
    try:
        periodo = obtener_periodo(periodo_id)
        validar_cortes(periodo, cortes)
        existentes = {corte.numero: corte for corte in periodo.cortes}
        for datos in cortes:
            corte = existentes.get(datos.numero)
            if corte is not None and corte.cerrado_en is not None:
                cambia = (
                    corte.peso_porcentaje,
                    corte.fecha_inicio,
                    corte.fecha_fin,
                    corte.limite_carga,
                    corte.limite_correccion,
                ) != (
                    datos.peso_porcentaje,
                    datos.fecha_inicio,
                    datos.fecha_fin,
                    datos.limite_carga,
                    datos.limite_correccion,
                )
                if cambia:
                    raise ErrorNegocio(
                        f"El corte {datos.numero} está cerrado y no se puede modificar."
                    )
                continue
            if corte is None:
                corte = Corte(periodo_academico_id=periodo.id, numero=datos.numero)
                db.session.add(corte)
            corte.peso_porcentaje = datos.peso_porcentaje
            corte.fecha_inicio = datos.fecha_inicio
            corte.fecha_fin = datos.fecha_fin
            corte.limite_carga = datos.limite_carga
            corte.limite_correccion = datos.limite_correccion
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="periodos_academicos",
            entidad_id=periodo.id,
            detalle=f"Definición de los cortes del período {periodo.identificador}",
        )
        db.session.commit()
        db.session.refresh(periodo)
        return periodo
    except Exception:
        db.session.rollback()
        raise


# ---------------------------------------------------------------------------
# RF-18: festivos
# ---------------------------------------------------------------------------


def agregar_festivo(periodo_id: int, fecha: dt.date, actor_id: int) -> tuple[int, int]:
    """Registra un festivo y regenera los calendarios afectados (RF-18, RF-19).

    Returns:
        (cursos regenerados, cursos omitidos por tener asistencia).
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-18
    try:
        periodo = obtener_periodo(periodo_id)
        if not periodo.fecha_inicio <= fecha <= periodo.fecha_fin:
            raise ErrorNegocio(
                "El festivo debe estar dentro de las fechas del período."
            )
        repetido = db.session.scalar(
            select(func.count(Festivo.id)).where(
                Festivo.periodo_academico_id == periodo.id, Festivo.fecha == fecha
            )
        )
        if repetido:
            raise ErrorNegocio("Ese festivo ya está registrado en el período.")
        db.session.add(Festivo(periodo_academico_id=periodo.id, fecha=fecha))
        db.session.flush()
        resultado = calendario.regenerar_calendarios_periodo(periodo.id)
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="festivos",
            entidad_id=periodo.id,
            detalle=f"Festivo {fecha:%d/%m/%Y} agregado al período "
            f"{periodo.identificador}",
        )
        db.session.commit()
        return resultado
    except Exception:
        db.session.rollback()
        raise


def eliminar_festivo(festivo_id: int, actor_id: int) -> tuple[int, int]:
    """Quita un festivo y regenera los calendarios afectados (RF-18, RF-19).

    Returns:
        (cursos regenerados, cursos omitidos por tener asistencia).
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-18
    try:
        festivo = db.session.get(Festivo, festivo_id)
        if festivo is None:
            raise ErrorNegocio("El festivo no existe.")
        periodo_id = festivo.periodo_academico_id
        fecha = festivo.fecha
        db.session.delete(festivo)
        db.session.flush()
        resultado = calendario.regenerar_calendarios_periodo(periodo_id)
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="festivos",
            entidad_id=periodo_id,
            detalle=f"Festivo {fecha:%d/%m/%Y} retirado",
        )
        db.session.commit()
        return resultado
    except Exception:
        db.session.rollback()
        raise
