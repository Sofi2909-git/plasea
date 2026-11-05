"""Estadística de reporte de un curso para el Profesor (RF-66 y RF-67).

Responde dos preguntas del profesor sobre uno de sus cursos:

1. Cuántos de sus estudiantes ya tienen nota registrada frente al total de
   inscritos, en cada corte (``AvanceCorte``).
2. En un corte elegido, cómo va cada estudiante: nota del corte, acumulada,
   requerida, horas ausentes, inasistencia, ritmo y estado de alerta con su
   motivo (``FilaReporte``).

Los valores son los de RF-40 a RF-43 y los mismos de RF-34: salen de
``seguimiento_profesor.valores_del_corte``. Mientras el corte esté abierto son
provisionales y se recalculan al guardar una nota, registrar asistencia o
corregir (RF-31); al cerrarse son definitivos. El total de inscritos es el de
la lista de RF-27.

Un estudiante sin nota registrada en el corte se evalúa solo por inasistencia:
si no hay alerta por inasistencia aparece como "sin nota".

El control de que el curso sea del profesor lo hace quien llama
(``registro_academico.obtener_curso_propio``).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from sqlalchemy import select

from plasea.modelos import ConfiguracionAlerta, Corte, Curso, Inscripcion, NotaCorte, db
from plasea.servicios import calculos, registro_academico, seguimiento_profesor
from plasea.servicios.comunes import ahora

ESTADO_SIN_NOTA = "sin_nota"
NOMBRES_ESTADO = {
    calculos.ESTADO_ROJA: "Roja",
    calculos.ESTADO_AMARILLA: "Amarilla",
    calculos.ESTADO_VERDE: "Verde",
    ESTADO_SIN_NOTA: "Sin nota",
}
ORDEN_ESTADO = {
    calculos.ESTADO_ROJA: 0,
    calculos.ESTADO_AMARILLA: 1,
    ESTADO_SIN_NOTA: 2,
    calculos.ESTADO_VERDE: 3,
}
NOMBRES_MOTIVO = {
    "nota": "Por nota",
    "inasistencia": "Por inasistencia",
    "ambos": "Por nota e inasistencia",
}


@dataclass(frozen=True)
class FilaReporte:
    """Un estudiante del curso en el corte elegido (RF-66)."""

    inscripcion_id: int
    codigo: str
    nombres: str
    nota_corte: Optional[Decimal]
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
        """``nota``, ``inasistencia``, ``ambos`` o ``None`` (verde o sin nota)."""
        if self.motivo_nota and self.motivo_inasistencia:
            return "ambos"
        if self.motivo_nota:
            return "nota"
        if self.motivo_inasistencia:
            return "inasistencia"
        return None

    @property
    def nombre_estado(self) -> str:
        """Texto del estado: el color nunca va solo."""
        return NOMBRES_ESTADO[self.estado]

    @property
    def nombre_motivo(self) -> str:
        """Motivo legible; vacío en verde y sin nota."""
        return NOMBRES_MOTIVO.get(self.motivo or "", "")


@dataclass(frozen=True)
class AvanceCorte:
    """Notas registradas frente a inscritos en un corte (RF-66)."""

    corte: Corte
    estado: str
    nombre_estado: str
    iniciado: bool
    con_nota: int
    inscritos: int

    @property
    def pendientes(self) -> int:
        """Estudiantes que aún no tienen nota en el corte."""
        return self.inscritos - self.con_nota

    @property
    def porcentaje(self) -> Optional[Decimal]:
        """Porcentaje de inscritos con nota; ``None`` sin inscritos."""
        return calculos.porcentaje(self.con_nota, self.inscritos)


@dataclass(frozen=True)
class ReporteCurso:
    """Datos de la pantalla de RF-66 y del documento de RF-67."""

    curso: Curso
    avances: list[AvanceCorte]
    corte: Optional[Corte]
    filas: list[FilaReporte] = field(default_factory=list)
    definitivo: bool = False

    @property
    def avance(self) -> Optional[AvanceCorte]:
        """Avance del corte elegido."""
        return next(
            (a for a in self.avances if self.corte and a.corte.id == self.corte.id),
            None,
        )

    def total(self, estado: str) -> int:
        """Estudiantes del corte elegido en un estado."""
        return sum(1 for fila in self.filas if fila.estado == estado)


def corte_elegido(curso: Curso, numero: Optional[int]) -> Optional[Corte]:
    """Corte pedido si ya inició; si no, el último corte iniciado (RF-66, RF-67)."""
    # Responsable: Sofi Celmar Galvis
    # RF-66
    disponibles = seguimiento_profesor.cortes_disponibles(curso)
    return next(
        (c for c in disponibles if c.numero == numero), None
    ) or seguimiento_profesor.corte_por_defecto(curso)


def estado_solo_inasistencia(
    umbrales: calculos.Umbrales,
    porcentaje_inasistencia: Optional[Decimal],
    porcentaje_ritmo: Optional[Decimal],
) -> str:
    """Estado de un estudiante sin nota en el corte, evaluado solo por asistencia.

    Reglas de RF-43 aplicadas únicamente a la inasistencia:

    - Roja: inasistencia acumulada mayor que el límite de pérdida.
    - Amarilla: inasistencia acumulada o ritmo desde el umbral amarillo.
    - En otro caso: ``sin_nota`` (no hay alerta por inasistencia).
    """
    # Responsable: Sofi Celmar Galvis
    # RF-66
    acumulada = porcentaje_inasistencia or Decimal("0")
    if acumulada > umbrales.limite_perdida_inasistencia:
        return calculos.ESTADO_ROJA
    if acumulada >= umbrales.umbral_amarillo_inasistencia or (
        porcentaje_ritmo is not None
        and porcentaje_ritmo >= umbrales.umbral_amarillo_inasistencia
    ):
        return calculos.ESTADO_AMARILLA
    return ESTADO_SIN_NOTA


def _notas_registradas(
    curso: Curso, cortes: list[Corte]
) -> dict[tuple[int, int], Decimal]:
    """Notas del curso por (inscripción, corte), para todos los cortes."""
    # Responsable: Sofi Celmar Galvis
    # RF-66
    return {
        (inscripcion_id, corte_id): nota
        for inscripcion_id, corte_id, nota in db.session.execute(
            select(NotaCorte.inscripcion_id, NotaCorte.corte_id, NotaCorte.nota)
            .join(Inscripcion, Inscripcion.id == NotaCorte.inscripcion_id)
            .where(
                Inscripcion.curso_id == curso.id,
                NotaCorte.corte_id.in_([c.id for c in cortes] or [0]),
            )
        )
    }


def _configuraciones(valores: dict[int, dict]) -> dict[int, ConfiguracionAlerta]:
    """Umbrales con que se calculó cada alerta, por identificador."""
    # Responsable: Sofi Celmar Galvis
    # RF-66
    ids = {d["configuracion_alerta_id"] for d in valores.values()}
    if not ids:
        return {}
    return {
        c.id: c
        for c in db.session.scalars(
            select(ConfiguracionAlerta).where(ConfiguracionAlerta.id.in_(ids))
        )
    }


def reporte_curso(curso: Curso, corte: Optional[Corte]) -> ReporteCurso:
    """Avance de notas por corte y situación de cada estudiante en el corte.

    Args:
        curso: curso del profesor (ya verificado por quien llama).
        corte: corte cuya lista de estudiantes se muestra; ``None`` si el
            período aún no tiene un corte iniciado.
    """
    # Responsable: Sofi Celmar Galvis
    # RF-66
    estados = registro_academico.estados_de_cortes(curso)
    inscritos = registro_academico.estudiantes_del_curso(curso.id)
    cortes = [e.corte for e in estados]
    notas = _notas_registradas(curso, cortes)
    vigentes = {f.inscripcion_id for f in inscritos}
    iniciados = {c.id for c in seguimiento_profesor.cortes_disponibles(curso)}
    avances = [
        AvanceCorte(
            corte=e.corte,
            estado=e.estado,
            nombre_estado=e.nombre,
            iniciado=e.corte.id in iniciados,
            con_nota=sum(1 for i in vigentes if (i, e.corte.id) in notas),
            inscritos=len(vigentes),
        )
        for e in estados
    ]
    if corte is None:
        return ReporteCurso(curso, avances, None)

    valores, definitivo = seguimiento_profesor.valores_del_corte(curso, corte)
    configuraciones = _configuraciones(valores)
    filas: list[FilaReporte] = []
    for fila in inscritos:
        datos = valores.get(fila.inscripcion_id)
        nota_corte = notas.get((fila.inscripcion_id, corte.id))
        if datos is None:
            filas.append(
                FilaReporte(
                    fila.inscripcion_id,
                    fila.codigo,
                    fila.nombres,
                    nota_corte,
                    None,
                    None,
                    0,
                    None,
                    None,
                    ESTADO_SIN_NOTA,
                    False,
                    False,
                )
            )
            continue
        estado = datos["estado_alerta"]
        motivo_nota = bool(datos["motivo_nota"])
        motivo_inasistencia = bool(datos["motivo_inasistencia"])
        if nota_corte is None:
            # Sin nota en el corte: se evalúa solo por inasistencia (RF-66).
            estado = estado_solo_inasistencia(
                configuraciones[datos["configuracion_alerta_id"]],
                datos["porcentaje_inasistencia"],
                datos["porcentaje_ritmo"],
            )
            motivo_nota = False
            motivo_inasistencia = estado in (
                calculos.ESTADO_ROJA,
                calculos.ESTADO_AMARILLA,
            )
        filas.append(
            FilaReporte(
                inscripcion_id=fila.inscripcion_id,
                codigo=fila.codigo,
                nombres=fila.nombres,
                nota_corte=nota_corte,
                nota_acumulada=calculos.redondear(datos["nota_acumulada"]),
                nota_requerida=datos["nota_requerida"],
                horas_ausentes=int(datos["horas_ausentes"] or 0),
                porcentaje_inasistencia=datos["porcentaje_inasistencia"],
                porcentaje_ritmo=datos["porcentaje_ritmo"],
                estado=estado,
                motivo_nota=motivo_nota,
                motivo_inasistencia=motivo_inasistencia,
            )
        )
    filas.sort(
        key=lambda f: (
            ORDEN_ESTADO[f.estado],
            -(f.porcentaje_inasistencia or 0),
            f.nombres,
        )
    )
    return ReporteCurso(curso, avances, corte, filas, definitivo)


def fecha_generacion() -> dt.datetime:
    """Fecha y hora de generación del documento de RF-67."""
    # Responsable: Sofi Celmar Galvis
    # RF-67
    return ahora()
