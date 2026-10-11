"""Calendario de sesiones y horas totales de cada curso (RF-19).

El calendario se genera a partir del horario semanal del curso (RF-15), de las
fechas del período (RF-16) y de sus festivos (RF-18). Solo se regenera mientras
el curso no tenga asistencia registrada: después de eso las sesiones son
información académica y no se tocan.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import delete, exists, func, insert, or_, select

from plasea.modelos import (
    Ausencia,
    BloqueHorario,
    Curso,
    Festivo,
    PeriodoAcademico,
    SesionClase,
    db,
)

SEGUNDOS_POR_HORA = 3600


@dataclass(frozen=True)
class SesionCalculada:
    """Sesión de clase calculada (aún no guardada)."""

    fecha: dt.date
    hora_inicio: dt.time
    hora_fin: dt.time

    @property
    def duracion_horas(self) -> int:
        """Horas completas de la sesión (1, 2 o 3)."""
        return duracion_en_horas(self.hora_inicio, self.hora_fin)


def duracion_en_horas(hora_inicio: dt.time, hora_fin: dt.time) -> int:
    """Devuelve la duración entera en horas entre dos horas del mismo día."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-19
    inicio = dt.timedelta(hours=hora_inicio.hour, minutes=hora_inicio.minute)
    fin = dt.timedelta(hours=hora_fin.hour, minutes=hora_fin.minute)
    return int((fin - inicio).total_seconds() // SEGUNDOS_POR_HORA)


def calcular_sesiones(
    bloques: Iterable[tuple[int, dt.time, dt.time]],
    fecha_inicio: dt.date,
    fecha_fin: dt.date,
    festivos: Iterable[dt.date],
) -> list[SesionCalculada]:
    """Calcula las sesiones de un curso entre dos fechas, omitiendo festivos.

    Args:
        bloques: tuplas (día ISO 1-7, hora de inicio, hora de fin).
        fecha_inicio: primer día del período.
        fecha_fin: último día del período.
        festivos: fechas sin clase.

    Returns:
        Sesiones ordenadas por fecha y hora de inicio.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-19
    bloques_por_dia: dict[int, list[tuple[dt.time, dt.time]]] = {}
    for dia, inicio, fin in bloques:
        bloques_por_dia.setdefault(dia, []).append((inicio, fin))
    dias_festivos = set(festivos)
    sesiones: list[SesionCalculada] = []
    fecha = fecha_inicio
    while fecha <= fecha_fin:
        if fecha not in dias_festivos:
            for inicio, fin in sorted(bloques_por_dia.get(fecha.isoweekday(), [])):
                sesiones.append(SesionCalculada(fecha, inicio, fin))
        fecha += dt.timedelta(days=1)
    return sesiones


def horas_totales(sesiones: Iterable[SesionCalculada]) -> int:
    """Suma las horas de una lista de sesiones calculadas."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-19
    return sum(sesion.duracion_horas for sesion in sesiones)


def curso_tiene_asistencia(curso_id: int) -> bool:
    """Indica si el curso tiene asistencia registrada (sesión marcada o ausencias)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-19
    sesion_marcada = exists().where(
        SesionClase.curso_id == curso_id,
        SesionClase.asistencia_registrada_en.is_not(None),
    )
    con_ausencias = exists().where(
        Ausencia.sesion_clase_id == SesionClase.id,
        SesionClase.curso_id == curso_id,
    )
    return bool(db.session.scalar(select(or_(sesion_marcada, con_ausencias))))


def regenerar_calendario(curso: Curso) -> bool:
    """Reemplaza las sesiones del curso por las calculadas con su horario actual.

    No confirma la transacción. Si el curso ya tiene asistencia, no cambia nada.

    Returns:
        ``True`` si se regeneró; ``False`` si se omitió por tener asistencia.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-19
    if curso_tiene_asistencia(curso.id):
        return False
    periodo = db.session.get(PeriodoAcademico, curso.periodo_academico_id)
    bloques = db.session.execute(
        select(
            BloqueHorario.dia_semana, BloqueHorario.hora_inicio, BloqueHorario.hora_fin
        ).where(BloqueHorario.curso_id == curso.id)
    ).all()
    festivos = db.session.scalars(
        select(Festivo.fecha).where(Festivo.periodo_academico_id == periodo.id)
    ).all()
    sesiones = calcular_sesiones(
        bloques, periodo.fecha_inicio, periodo.fecha_fin, festivos
    )
    db.session.execute(delete(SesionClase).where(SesionClase.curso_id == curso.id))
    if sesiones:
        db.session.execute(
            insert(SesionClase),
            [
                {
                    "curso_id": curso.id,
                    "fecha": sesion.fecha,
                    "hora_inicio": sesion.hora_inicio,
                    "hora_fin": sesion.hora_fin,
                }
                for sesion in sesiones
            ],
        )
    return True


def regenerar_calendarios_periodo(periodo_id: int) -> tuple[int, int]:
    """Regenera los calendarios de todos los cursos de un período (RF-18, RF-16).

    No confirma la transacción.

    Returns:
        (cursos regenerados, cursos omitidos por tener asistencia).
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-19
    regenerados = omitidos = 0
    cursos = db.session.scalars(
        select(Curso).where(Curso.periodo_academico_id == periodo_id)
    ).all()
    for curso in cursos:
        if regenerar_calendario(curso):
            regenerados += 1
        else:
            omitidos += 1
    return regenerados, omitidos


def resumen_calendario(curso_id: int) -> tuple[int, int]:
    """Devuelve (número de sesiones, horas totales) guardadas para el curso."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-19
    fila = db.session.execute(
        select(
            func.count(SesionClase.id),
            func.coalesce(func.sum(SesionClase.duracion_horas), 0),
        ).where(SesionClase.curso_id == curso_id)
    ).one()
    return int(fila[0]), int(fila[1])


def sesiones_del_curso(curso_id: int) -> list[SesionClase]:
    """Lista las sesiones guardadas del curso en orden cronológico."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-19
    return list(
        db.session.scalars(
            select(SesionClase)
            .where(SesionClase.curso_id == curso_id)
            .order_by(SesionClase.fecha, SesionClase.hora_inicio)
        )
    )
