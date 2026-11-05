"""Pérdida reiterada de una asignatura en los cortes 1 y 2 (RF-64).

Un estudiante tiene pérdida reiterada en una asignatura cuando su estado de
alerta es rojo en el corte 1 y también en el corte 2 del mismo período. Cada
corte conserva su propio motivo (nota, inasistencia o ambos) y si su estado es
provisional o definitivo.

No se guarda nada nuevo: el marcador se calcula al consultar a partir de la
tabla ``alertas`` (RF-43). Por eso se actualiza solo cada vez que las alertas
se recalculan, ya sea por una corrección (RF-31) o al cerrar una reapertura
(RF-39). Las pantallas y los documentos imprimibles de RF-45, RF-60, RF-65 y
RF-67 usan este mismo servicio, así coinciden entre sí.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import select

from plasea.modelos import (
    Alerta,
    Asignatura,
    Corte,
    Curso,
    Estudiante,
    Inscripcion,
    MatriculaPeriodo,
    db,
)
from plasea.servicios import calculos

CORTES_EVALUADOS = (1, 2)
NOMBRES_MOTIVO = {
    "nota": "Por nota",
    "inasistencia": "Por inasistencia",
    "ambos": "Por nota e inasistencia",
}


@dataclass(frozen=True)
class CortePerdida:
    """Estado rojo de un corte con su motivo (RF-64)."""

    numero: int
    motivo: str
    definitivo: bool

    @property
    def nombre_motivo(self) -> str:
        """Motivo legible del corte."""
        return NOMBRES_MOTIVO[self.motivo]

    @property
    def nombre_estado(self) -> str:
        """``Definitivo`` o ``Provisional``."""
        return "Definitivo" if self.definitivo else "Provisional"


@dataclass(frozen=True)
class PerdidaReiterada:
    """Estudiante en rojo en los cortes 1 y 2 de una misma asignatura (RF-64)."""

    inscripcion_id: int
    estudiante_id: int
    codigo: str
    nombres: str
    curso_id: int
    curso_codigo: str
    asignatura_codigo: str
    asignatura_nombre: str
    corte_1: CortePerdida
    corte_2: CortePerdida

    @property
    def cortes(self) -> tuple[CortePerdida, CortePerdida]:
        """Los dos cortes que originan la marca."""
        return self.corte_1, self.corte_2

    @property
    def definitiva(self) -> bool:
        """Es definitiva solo si los dos cortes ya están cerrados."""
        return self.corte_1.definitivo and self.corte_2.definitivo


def motivo_de(motivo_nota: bool, motivo_inasistencia: bool) -> Optional[str]:
    """``nota``, ``inasistencia``, ``ambos`` o ``None`` (RF-43)."""
    # Responsable: Sofi Celmar Galvis
    # RF-64
    if motivo_nota and motivo_inasistencia:
        return "ambos"
    if motivo_nota:
        return "nota"
    if motivo_inasistencia:
        return "inasistencia"
    return None


def cortes_en_rojo(
    filas: Iterable[tuple[int, int, bool, bool, bool]],
) -> Optional[tuple[CortePerdida, CortePerdida]]:
    """Aplica la regla de RF-64 a las alertas rojas de una inscripción.

    Args:
        filas: alertas rojas de una inscripción, cada una como (``inscripcion_id``,
            ``numero`` de corte, ``motivo_nota``, ``motivo_inasistencia``,
            ``definitiva``).

    Returns:
        Los dos cortes (1 y 2) si ambos están en rojo; ``None`` en otro caso.
        Un estudiante en rojo en un solo corte no se marca.
    """
    # Responsable: Sofi Celmar Galvis
    # RF-64
    por_numero: dict[int, CortePerdida] = {}
    for _inscripcion, numero, motivo_nota, motivo_inasistencia, definitiva in filas:
        motivo = motivo_de(motivo_nota, motivo_inasistencia)
        if numero in CORTES_EVALUADOS and motivo is not None:
            por_numero[numero] = CortePerdida(numero, motivo, bool(definitiva))
    if all(numero in por_numero for numero in CORTES_EVALUADOS):
        return por_numero[1], por_numero[2]
    return None


def _consultar(*condiciones) -> list[PerdidaReiterada]:
    """Marcas de pérdida reiterada de las alertas que cumplen las condiciones."""
    # Responsable: Sofi Celmar Galvis
    # RF-64
    filas = db.session.execute(
        select(
            Inscripcion.id,
            MatriculaPeriodo.estudiante_id,
            Estudiante.codigo,
            Estudiante.nombres,
            Curso.id,
            Curso.codigo,
            Asignatura.codigo,
            Asignatura.nombre,
            Corte.numero,
            Alerta.motivo_nota,
            Alerta.motivo_inasistencia,
            Alerta.definitiva,
        )
        .join(Inscripcion, Inscripcion.id == Alerta.inscripcion_id)
        .join(MatriculaPeriodo, MatriculaPeriodo.id == Inscripcion.matricula_periodo_id)
        .join(Estudiante, Estudiante.id == MatriculaPeriodo.estudiante_id)
        .join(Curso, Curso.id == Inscripcion.curso_id)
        .join(Asignatura, Asignatura.id == Curso.asignatura_id)
        .join(Corte, Corte.id == Alerta.corte_id)
        .where(
            Alerta.estado_alerta == calculos.ESTADO_ROJA,
            Corte.numero.in_(CORTES_EVALUADOS),
            *condiciones,
        )
    ).all()
    agrupadas: dict[int, list[tuple]] = {}
    datos: dict[int, tuple] = {}
    for fila in filas:
        inscripcion_id = fila[0]
        datos[inscripcion_id] = fila[1:8]
        agrupadas.setdefault(inscripcion_id, []).append((inscripcion_id, *fila[8:]))
    resultado: list[PerdidaReiterada] = []
    for inscripcion_id, alertas_rojas in agrupadas.items():
        cortes = cortes_en_rojo(alertas_rojas)
        if cortes is None:
            continue
        est_id, codigo, nombres, curso_id, curso_codigo, asig_codigo, asig_nombre = (
            datos[inscripcion_id]
        )
        resultado.append(
            PerdidaReiterada(
                inscripcion_id,
                est_id,
                codigo,
                nombres,
                curso_id,
                curso_codigo,
                asig_codigo,
                asig_nombre,
                cortes[0],
                cortes[1],
            )
        )
    resultado.sort(key=lambda p: (p.nombres, p.codigo, p.asignatura_codigo))
    return resultado


def de_inscripciones(inscripcion_ids: Iterable[int]) -> dict[int, PerdidaReiterada]:
    """Marcas de las inscripciones indicadas, por identificador de inscripción."""
    # Responsable: Sofi Celmar Galvis
    # RF-64
    ids = list(inscripcion_ids)
    if not ids:
        return {}
    return {p.inscripcion_id: p for p in _consultar(Inscripcion.id.in_(ids))}


def de_inscripcion(inscripcion_id: int) -> Optional[PerdidaReiterada]:
    """Marca de una inscripción, o ``None`` si no tiene pérdida reiterada."""
    # Responsable: Sofi Celmar Galvis
    # RF-64
    return de_inscripciones([inscripcion_id]).get(inscripcion_id)


def del_curso(curso_id: int) -> list[PerdidaReiterada]:
    """Estudiantes del curso con pérdida reiterada, ordenados por nombre."""
    # Responsable: Sofi Celmar Galvis
    # RF-64
    return _consultar(Inscripcion.curso_id == curso_id)
