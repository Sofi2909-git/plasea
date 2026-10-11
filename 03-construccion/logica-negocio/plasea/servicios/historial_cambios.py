"""Historial de cambios de notas y asistencia (RF-33).

Une ``historial_notas`` e ``historial_ausencias`` en una sola lista con columnas
canónicas (``UNION ALL`` con la misma proyección en las dos ramas), ordenada de
la más reciente a la más antigua. Incluye las correcciones de RF-31 y las hechas
en reaperturas excepcionales (RF-38).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import Select, cast, func, literal, or_, select, union_all
from sqlalchemy.types import Date, Integer, String

from plasea.modelos import (
    Asignatura,
    Ausencia,
    Corte,
    Curso,
    Estudiante,
    HistorialAusencia,
    HistorialNota,
    Inscripcion,
    MatriculaPeriodo,
    NotaCorte,
    SesionClase,
    Usuario,
    db,
)

CAMBIOS_POR_PAGINA = 50


@dataclass(frozen=True)
class FiltrosHistorial:
    """Filtros del historial: curso, estudiante (código o nombre) y fechas."""

    curso_id: Optional[int] = None
    estudiante: Optional[str] = None
    desde: Optional[dt.date] = None
    hasta: Optional[dt.date] = None


@dataclass
class PaginaHistorial:
    """Página de cambios con el total para la paginación."""

    filas: list[Any]
    total: int
    pagina: int
    por_pagina: int

    @property
    def paginas(self) -> int:
        """Número de páginas."""
        return max(1, -(-self.total // self.por_pagina))


def _rama_notas() -> Select:
    """Correcciones de notas con la proyección canónica."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-33
    return (
        select(
            literal("nota").label("tipo"),
            HistorialNota.id.label("id"),
            HistorialNota.creado_en.label("fecha"),
            cast(HistorialNota.nota_anterior, String(10)).label("anterior"),
            cast(HistorialNota.nota_nueva, String(10)).label("nuevo"),
            HistorialNota.motivo.label("motivo"),
            Usuario.nombre_completo.label("usuario"),
            HistorialNota.reapertura_curso_id.label("reapertura_id"),
            Estudiante.id.label("estudiante_id"),
            Estudiante.codigo.label("codigo"),
            Estudiante.nombres.label("nombres"),
            Curso.id.label("curso_id"),
            Asignatura.codigo.label("asignatura"),
            Curso.codigo.label("curso"),
            Corte.numero.label("corte"),
            cast(literal(None), Date).label("sesion"),
        )
        .join(NotaCorte, NotaCorte.id == HistorialNota.nota_corte_id)
        .join(Corte, Corte.id == NotaCorte.corte_id)
        .join(Inscripcion, Inscripcion.id == NotaCorte.inscripcion_id)
        .join(MatriculaPeriodo, MatriculaPeriodo.id == Inscripcion.matricula_periodo_id)
        .join(Estudiante, Estudiante.id == MatriculaPeriodo.estudiante_id)
        .join(Curso, Curso.id == Inscripcion.curso_id)
        .join(Asignatura, Asignatura.id == Curso.asignatura_id)
        .join(Usuario, Usuario.id == HistorialNota.usuario_id)
    )


def _rama_asistencia() -> Select:
    """Correcciones de asistencia con la misma proyección."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-33
    return (
        select(
            literal("asistencia").label("tipo"),
            HistorialAusencia.id.label("id"),
            HistorialAusencia.creado_en.label("fecha"),
            cast(HistorialAusencia.ausente_anterior, String(10)).label("anterior"),
            cast(HistorialAusencia.ausente_nuevo, String(10)).label("nuevo"),
            HistorialAusencia.motivo.label("motivo"),
            Usuario.nombre_completo.label("usuario"),
            HistorialAusencia.reapertura_curso_id.label("reapertura_id"),
            Estudiante.id.label("estudiante_id"),
            Estudiante.codigo.label("codigo"),
            Estudiante.nombres.label("nombres"),
            Curso.id.label("curso_id"),
            Asignatura.codigo.label("asignatura"),
            Curso.codigo.label("curso"),
            cast(literal(None), Integer).label("corte"),
            SesionClase.fecha.label("sesion"),
        )
        .join(Ausencia, Ausencia.id == HistorialAusencia.ausencia_id)
        .join(SesionClase, SesionClase.id == Ausencia.sesion_clase_id)
        .join(Inscripcion, Inscripcion.id == Ausencia.inscripcion_id)
        .join(MatriculaPeriodo, MatriculaPeriodo.id == Inscripcion.matricula_periodo_id)
        .join(Estudiante, Estudiante.id == MatriculaPeriodo.estudiante_id)
        .join(Curso, Curso.id == Inscripcion.curso_id)
        .join(Asignatura, Asignatura.id == Curso.asignatura_id)
        .join(Usuario, Usuario.id == HistorialAusencia.usuario_id)
    )


def _filtrar(consulta: Select, modelo_fecha: Any, filtros: FiltrosHistorial) -> Select:
    """Aplica los filtros a una rama (antes de la unión, para usar índices)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-33
    if filtros.curso_id:
        consulta = consulta.where(Curso.id == filtros.curso_id)
    texto = (filtros.estudiante or "").strip()[:150]
    if texto:
        consulta = consulta.where(
            or_(
                Estudiante.codigo == texto,
                Estudiante.nombres.contains(texto, autoescape=True),
            )
        )
    if filtros.desde:
        consulta = consulta.where(
            modelo_fecha >= dt.datetime.combine(filtros.desde, dt.time.min)
        )
    if filtros.hasta:
        consulta = consulta.where(
            modelo_fecha
            < dt.datetime.combine(filtros.hasta, dt.time.min) + dt.timedelta(days=1)
        )
    return consulta


def listar_cambios(filtros: FiltrosHistorial, pagina: int = 1) -> PaginaHistorial:
    """Cambios de notas y asistencia, del más reciente al más antiguo (RF-33)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-33
    union = union_all(
        _filtrar(_rama_notas(), HistorialNota.creado_en, filtros),
        _filtrar(_rama_asistencia(), HistorialAusencia.creado_en, filtros),
    ).subquery()
    total = db.session.scalar(select(func.count()).select_from(union)) or 0
    pagina = max(1, pagina)
    filas = db.session.execute(
        select(union)
        .order_by(union.c.fecha.desc(), union.c.tipo, union.c.id.desc())
        .limit(CAMBIOS_POR_PAGINA)
        .offset((pagina - 1) * CAMBIOS_POR_PAGINA)
    ).all()
    return PaginaHistorial(list(filas), int(total), pagina, CAMBIOS_POR_PAGINA)


def cursos_con_cambios() -> list[tuple[int, str]]:
    """Cursos que tienen alguna corrección, para el filtro (RF-33)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-33
    union = union_all(
        select(Inscripcion.curso_id.label("curso_id"))
        .join(NotaCorte, NotaCorte.inscripcion_id == Inscripcion.id)
        .join(HistorialNota, HistorialNota.nota_corte_id == NotaCorte.id),
        select(Inscripcion.curso_id.label("curso_id"))
        .join(Ausencia, Ausencia.inscripcion_id == Inscripcion.id)
        .join(HistorialAusencia, HistorialAusencia.ausencia_id == Ausencia.id),
    ).subquery()
    filas = db.session.execute(
        select(Curso.id, Asignatura.codigo, Curso.codigo, Asignatura.nombre)
        .join(Asignatura, Asignatura.id == Curso.asignatura_id)
        .where(Curso.id.in_(select(union.c.curso_id).distinct()))
        .order_by(Asignatura.nombre, Curso.codigo)
    )
    return [
        (cid, f"{codigo} {curso} · {nombre}") for cid, codigo, curso, nombre in filas
    ]
