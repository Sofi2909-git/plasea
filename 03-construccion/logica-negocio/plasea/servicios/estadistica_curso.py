"""Estadística de un curso para el Auditor académico (RF-65).

Reúne, para un curso, lo que muestra el documento imprimible de RF-65:

- inscritos, aprobados, en alerta y perdidos por corte, con las mismas cifras
  de la pantalla de resultados (RF-48);
- la distribución de estudiantes por estado y motivo en cada corte, que
  alimenta la gráfica (RF-48);
- la lista de estudiantes con pérdida reiterada y su motivo (RF-64).

No calcula nada propio: reutiliza ``analitica`` y ``perdida_reiterada``, así
las cifras del documento coinciden con las de las pantallas.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from plasea.modelos import Corte, Curso, PeriodoAcademico, db
from plasea.servicios import analitica, perdida_reiterada
from plasea.servicios.comunes import ErrorNegocio


@dataclass(frozen=True)
class EstadisticaCurso:
    """Datos del documento de estadística de un curso (RF-65)."""

    curso: Curso
    cortes: list[Corte]
    totales: list[analitica.FilaResultado]
    distribucion: list[analitica.DistribucionCorte]
    reiteradas: list[perdida_reiterada.PerdidaReiterada]

    @property
    def por_corte(self) -> list[tuple[Corte, analitica.FilaResultado]]:
        """Cada corte con sus cifras de inscritos, aprobados, en alerta y perdidos."""
        return list(zip(self.cortes, self.totales))


def obtener_curso(curso_id: int) -> Curso:
    """Curso con asignatura, profesor, período y cortes cargados.

    Raises:
        ErrorNegocio: el curso no existe.
    """
    # Responsable: Sofi Celmar Galvis
    # RF-65
    curso = db.session.scalar(
        select(Curso)
        .options(
            joinedload(Curso.asignatura),
            joinedload(Curso.profesor),
            joinedload(Curso.periodo_academico).selectinload(PeriodoAcademico.cortes),
            selectinload(Curso.bloques_horario),
        )
        .where(Curso.id == curso_id)
    )
    if curso is None:
        raise ErrorNegocio("El curso solicitado no existe.")
    return curso


def estadistica(curso: Curso) -> EstadisticaCurso:
    """Cifras por corte, gráfica y pérdida reiterada de un curso (RF-65)."""
    # Responsable: Sofi Celmar Galvis
    # RF-65
    filtros = analitica.FiltrosResultados(curso_id=curso.id)
    cortes = sorted(curso.periodo_academico.cortes, key=lambda c: c.numero)
    totales = [analitica.resultados(corte, filtros)[1] for corte in cortes]
    return EstadisticaCurso(
        curso=curso,
        cortes=cortes,
        totales=totales,
        distribucion=analitica.distribucion_por_corte(curso.periodo_academico, filtros),
        reiteradas=perdida_reiterada.del_curso(curso.id),
    )
