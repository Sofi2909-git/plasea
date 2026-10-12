"""Cómo van los estudiantes de un curso, vista del Profesor (RF-34).

Para cada inscrito del curso muestra las notas de los cortes hasta el elegido,
la nota acumulada, el porcentaje de inasistencia y el estado de alerta con su
motivo. Los valores salen del mismo cálculo de RF-40 a RF-43:

- Corte abierto: se calculan al momento con ``alertas.evaluar`` (provisional),
  aunque el curso aún no se haya enviado.
- Corte cerrado: se leen las alertas definitivas guardadas al cerrar.

El control de que el curso sea del profesor lo hace quien llama
(``registro_academico.obtener_curso_propio``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy import select

from plasea.modelos import (
    Alerta,
    Corte,
    Curso,
    Estudiante,
    Inscripcion,
    MatriculaPeriodo,
    NotaCorte,
    db,
)
from plasea.servicios import alertas, calculos
from plasea.servicios.comunes import ahora

NOMBRES_ESTADO = {
    calculos.ESTADO_ROJA: "Roja",
    calculos.ESTADO_AMARILLA: "Amarilla",
    calculos.ESTADO_VERDE: "Verde",
}
NOMBRES_MOTIVO = {
    "nota": "Por nota",
    "inasistencia": "Por inasistencia",
    "ambos": "Por nota e inasistencia",
}


@dataclass(frozen=True)
class FilaSeguimiento:
    """Un estudiante del curso con su situación en el corte (RF-34)."""

    inscripcion_id: int
    codigo: str
    nombres: str
    notas: list[Optional[Decimal]]
    nota_acumulada: Optional[Decimal]
    nota_requerida: Optional[Decimal]
    horas_ausentes: int
    porcentaje_inasistencia: Optional[Decimal]
    porcentaje_ritmo: Optional[Decimal]
    estado: str
    motivo_nota: bool
    motivo_inasistencia: bool

    @property
    def motivo(self) -> Optional[str]:
        """``nota``, ``inasistencia``, ``ambos`` o ``None`` en verde."""
        if self.motivo_nota and self.motivo_inasistencia:
            return "ambos"
        if self.motivo_nota:
            return "nota"
        if self.motivo_inasistencia:
            return "inasistencia"
        return None

    @property
    def nombre_estado(self) -> str:
        """Nombre visible del estado."""
        return NOMBRES_ESTADO[self.estado]

    @property
    def nombre_motivo(self) -> str:
        """Motivo legible, vacío en verde."""
        return NOMBRES_MOTIVO.get(self.motivo or "", "")


@dataclass(frozen=True)
class SeguimientoCurso:
    """Resultado de la vista del profesor para un curso y corte (RF-34)."""

    corte: Corte
    cortes_mostrados: list[Corte]
    filas: list[FilaSeguimiento]
    definitivo: bool

    def total(self, estado: str) -> int:
        """Número de estudiantes en un estado."""
        return sum(1 for fila in self.filas if fila.estado == estado)


def cortes_disponibles(curso: Curso) -> list[Corte]:
    """Cortes del período que ya iniciaron (los que tienen algo que mostrar)."""
    # Responsable: Andrés Camilo Anaya García
    # RF-34
    hoy = ahora().date()
    cortes = sorted(curso.periodo_academico.cortes, key=lambda c: c.numero)
    return [c for c in cortes if c.fecha_inicio <= hoy or c.cerrado_en is not None]


def corte_por_defecto(curso: Curso) -> Optional[Corte]:
    """El último corte iniciado: el que el profesor está trabajando."""
    # Responsable: Andrés Camilo Anaya García
    # RF-34
    disponibles = cortes_disponibles(curso)
    return disponibles[-1] if disponibles else None


def _valores_guardados(corte: Corte, curso_id: int) -> dict[int, dict]:
    """Alertas definitivas del curso en un corte cerrado, por inscripción."""
    # Responsable: Andrés Camilo Anaya García
    # RF-34
    return {
        alerta.inscripcion_id: {
            "estado_alerta": alerta.estado_alerta,
            "motivo_nota": alerta.motivo_nota,
            "motivo_inasistencia": alerta.motivo_inasistencia,
            "nota_acumulada": alerta.nota_acumulada,
            "nota_requerida": alerta.nota_requerida,
            "horas_ausentes": alerta.horas_ausentes,
            "porcentaje_inasistencia": alerta.porcentaje_inasistencia,
            "porcentaje_ritmo": alerta.porcentaje_ritmo,
        }
        for alerta in db.session.scalars(
            select(Alerta)
            .join(Inscripcion, Inscripcion.id == Alerta.inscripcion_id)
            .where(Alerta.corte_id == corte.id, Inscripcion.curso_id == curso_id)
        )
    }


def seguimiento_curso(curso: Curso, corte: Corte) -> SeguimientoCurso:
    """Situación de cada inscrito del curso en el corte, ordenada por severidad.

    Tres consultas por lote (inscritos, notas y alertas) sin importar el número
    de estudiantes; el cálculo en vivo reutiliza ``alertas.evaluar``.
    """
    # Responsable: Andrés Camilo Anaya García
    # RF-34
    cortes = sorted(curso.periodo_academico.cortes, key=lambda c: c.numero)
    mostrados = [c for c in cortes if c.numero <= corte.numero]
    definitivo = corte.cerrado_en is not None
    valores = _valores_guardados(corte, curso.id) if definitivo else {}
    if not valores:
        definitivo = False
        valores = {
            inscripcion_id: datos
            for inscripcion_id, _, datos in alertas.evaluar(corte, [curso.id])
        }

    notas: dict[tuple[int, int], Decimal] = {
        (inscripcion_id, corte_id): nota
        for inscripcion_id, corte_id, nota in db.session.execute(
            select(NotaCorte.inscripcion_id, NotaCorte.corte_id, NotaCorte.nota)
            .join(Inscripcion, Inscripcion.id == NotaCorte.inscripcion_id)
            .where(
                Inscripcion.curso_id == curso.id,
                NotaCorte.corte_id.in_([c.id for c in mostrados]),
            )
        )
    }
    inscritos = db.session.execute(
        select(Inscripcion.id, Estudiante.codigo, Estudiante.nombres)
        .join(MatriculaPeriodo, MatriculaPeriodo.id == Inscripcion.matricula_periodo_id)
        .join(Estudiante, Estudiante.id == MatriculaPeriodo.estudiante_id)
        .where(
            Inscripcion.curso_id == curso.id,
            Inscripcion.id.in_(list(valores) or [0]),
        )
    ).all()

    filas: list[FilaSeguimiento] = []
    for inscripcion_id, codigo, nombres in inscritos:
        datos = valores[inscripcion_id]
        filas.append(
            FilaSeguimiento(
                inscripcion_id=inscripcion_id,
                codigo=codigo,
                nombres=nombres,
                notas=[notas.get((inscripcion_id, c.id)) for c in mostrados],
                nota_acumulada=calculos.redondear(datos["nota_acumulada"]),
                nota_requerida=datos["nota_requerida"],
                horas_ausentes=int(datos["horas_ausentes"] or 0),
                porcentaje_inasistencia=datos["porcentaje_inasistencia"],
                porcentaje_ritmo=datos["porcentaje_ritmo"],
                estado=datos["estado_alerta"],
                motivo_nota=bool(datos["motivo_nota"]),
                motivo_inasistencia=bool(datos["motivo_inasistencia"]),
            )
        )
    filas.sort(
        key=lambda f: (
            calculos.SEVERIDAD[f.estado],
            -(f.porcentaje_inasistencia or 0),
            f.nombres,
        )
    )
    return SeguimientoCurso(corte, mostrados, filas, definitivo)
