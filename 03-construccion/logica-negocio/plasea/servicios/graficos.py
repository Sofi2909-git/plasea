"""Datos de los gráficos del tablero del Auditor académico (RF-54 a RF-56).

Los gráficos no calculan nada propio: reutilizan las mismas fuentes que las
pantallas de las que dependen, para que las cifras coincidan.

- RF-54: alertas guardadas por corte, como la lista de RF-44.
- RF-55: clasificación de continuidad de RF-49.
- RF-56: no continuidad por semestre cursado de RF-51.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select

from plasea.modelos import Alerta, Corte, MatriculaPeriodo, PeriodoAcademico, db
from plasea.servicios import calculos, continuidad

SEMESTRES_CARRERA = range(1, 11)


@dataclass(frozen=True)
class SemaforoCorte:
    """Estudiantes por estado de alerta en un corte (RF-54)."""

    corte: Corte
    verde: int
    amarilla: int
    roja: int

    @property
    def total(self) -> int:
        """Alertas calculadas en el corte (una por estudiante y asignatura)."""
        return self.verde + self.amarilla + self.roja

    def porcentaje(self, valor: int) -> Optional[Decimal]:
        """Participación de un estado en el total del corte."""
        return calculos.porcentaje(valor, self.total)


@dataclass(frozen=True)
class ComparativoPeriodo:
    """Inscritos de un período y cuántos continúan en el siguiente (RF-55)."""

    periodo: PeriodoAcademico
    inscritos: int
    continuan: Optional[int]
    no_continuan: Optional[int]
    indice: Optional[Decimal]


def semaforo_por_corte(periodo: PeriodoAcademico) -> list[SemaforoCorte]:
    """Conteo de verde, amarilla y roja de cada corte del período (RF-54).

    Una sola consulta agrupada por corte y estado (usa el índice
    ``ix_alertas_corte_estado``). Las cifras son las de ``alertas.resumen_corte``.
    """
    # Responsable: Andrés Camilo Anaya García
    # RF-54
    cortes = sorted(periodo.cortes, key=lambda c: c.numero)
    conteo: dict[tuple[int, str], int] = {
        (corte_id, estado): int(total)
        for corte_id, estado, total in db.session.execute(
            select(Alerta.corte_id, Alerta.estado_alerta, func.count(Alerta.id))
            .where(Alerta.corte_id.in_([c.id for c in cortes] or [0]))
            .group_by(Alerta.corte_id, Alerta.estado_alerta)
        )
    }
    return [
        SemaforoCorte(
            corte,
            conteo.get((corte.id, calculos.ESTADO_VERDE), 0),
            conteo.get((corte.id, calculos.ESTADO_AMARILLA), 0),
            conteo.get((corte.id, calculos.ESTADO_ROJA), 0),
        )
        for corte in cortes
    ]


def comparativo_periodos() -> list[ComparativoPeriodo]:
    """Inscritos por período y cuántos continúan, del más antiguo al reciente.

    Los inscritos salen de una consulta agrupada; la continuidad, de
    ``continuidad.clasificar`` (RF-49) para cada período que ya tiene siguiente.
    El período más reciente muestra solo sus inscritos.
    """
    # Responsable: Andrés Camilo Anaya García
    # RF-55
    inscritos = dict(
        db.session.execute(
            select(
                MatriculaPeriodo.periodo_academico_id, func.count(MatriculaPeriodo.id)
            ).group_by(MatriculaPeriodo.periodo_academico_id)
        ).all()
    )
    evaluables = {p.id for p in continuidad.periodos_evaluables()}
    filas: list[ComparativoPeriodo] = []
    for periodo in db.session.scalars(
        select(PeriodoAcademico).order_by(PeriodoAcademico.fecha_inicio)
    ):
        continuan = no_continuan = indice = None
        if periodo.id in evaluables:
            total = continuidad.indicador(
                periodo.identificador, continuidad.clasificar(periodo)
            )
            continuan, no_continuan, indice = (
                total.continuan,
                total.no_continuan,
                total.indice,
            )
        filas.append(
            ComparativoPeriodo(
                periodo,
                int(inscritos.get(periodo.id, 0)),
                continuan,
                no_continuan,
                indice,
            )
        )
    return filas


def no_continuidad_por_semestre(
    periodo: PeriodoAcademico,
) -> tuple[continuidad.Indicador, list[continuidad.Indicador]]:
    """Total del período e índice por semestre cursado, del 1 al 10 (RF-56).

    Los semestres sin inscritos aparecen en cero para que el eje sea completo.
    Una sola clasificación (RF-49) alimenta el total y los grupos.

    Raises:
        ErrorNegocio: el período aún no tiene período siguiente.
    """
    # Responsable: Andrés Camilo Anaya García
    # RF-56
    filas = continuidad.clasificar(periodo)
    grupos = {
        int(g.etiqueta): g for g in continuidad.por_grupo(filas, lambda f: f.semestre)
    }
    return continuidad.indicador(periodo.identificador, filas), [
        grupos.get(s) or continuidad.Indicador(str(s), 0, 0, 0, 0, 0)
        for s in SEMESTRES_CARRERA
    ]


def maximo(valores: list[Optional[Decimal | int]]) -> Decimal:
    """Valor máximo de una serie para escalar las barras (mínimo 1)."""
    # Responsable: Andrés Camilo Anaya García
    # RF-54
    return max([Decimal(v) for v in valores if v is not None] + [Decimal(1)])
