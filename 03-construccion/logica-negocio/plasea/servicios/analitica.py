"""Detalle de alerta, riesgo alto, histórico y resultados (RF-45 a RF-48).

- RF-45: detalle de la alerta de un estudiante en una asignatura, con los
  mismos valores que guardó RF-43 (notas, acumulada, requerida, horas, ritmo).
- RF-46: marcador de riesgo alto (amarilla o roja en 2 o más asignaturas del
  mismo período y corte). Se calcula en la consulta a partir de ``alertas``,
  así se actualiza cada vez que se recalculan.
- RF-47: histórico por semestre con resultado (aprobada o perdida) y motivo.
- RF-48: inscritos, aprobados, en alerta y perdidos por asignatura, curso y corte.

Todas las consultas son por lotes (sin una consulta por fila).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import aliased, joinedload

from plasea.modelos import (
    Alerta,
    Asignatura,
    Ausencia,
    ConfiguracionAlerta,
    Corte,
    Curso,
    Estudiante,
    Inscripcion,
    MatriculaPeriodo,
    NotaCorte,
    PeriodoAcademico,
    SesionClase,
    Usuario,
    db,
)
from plasea.servicios import alertas, calculos
from plasea.servicios.comunes import ErrorNegocio, ahora

RESULTADO_APROBADA = "aprobada"
RESULTADO_PERDIDA = "perdida"
RESULTADO_EN_CURSO = "en_curso"
RESULTADO_RETIRADA = "retirada"
NOMBRES_RESULTADO = {
    RESULTADO_APROBADA: "Aprobada",
    RESULTADO_PERDIDA: "Perdida",
    RESULTADO_EN_CURSO: "En curso",
    RESULTADO_RETIRADA: "Retirada",
}
NOMBRES_MOTIVO = {
    "nota": "Por nota",
    "inasistencia": "Por inasistencia",
    "ambos": "Por nota e inasistencia",
}


# ---------------------------------------------------------------------------
# RF-46: riesgo alto
# ---------------------------------------------------------------------------


def estudiantes_en_riesgo(corte_id: int) -> set[int]:
    """Estudiantes en riesgo alto en el corte (RF-46)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-46
    return set(db.session.scalars(alertas.subconsulta_riesgo_alto(corte_id)))


def es_riesgo_alto(estudiante_id: int, corte_id: int) -> bool:
    """Indica si el estudiante está en riesgo alto en el corte (RF-46)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-46
    subconsulta = alertas.subconsulta_riesgo_alto(corte_id).where(
        MatriculaPeriodo.estudiante_id == estudiante_id
    )
    return db.session.scalar(subconsulta) is not None


# ---------------------------------------------------------------------------
# RF-45: detalle de la alerta
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FilaCorteDetalle:
    """Un corte en el detalle de la alerta."""

    corte: Corte
    nota: Optional[Decimal]
    alerta: Optional[Alerta]


@dataclass(frozen=True)
class DetalleAlerta:
    """Detalle de la alerta de un estudiante en una asignatura (RF-45)."""

    inscripcion: Inscripcion
    estudiante: Estudiante
    curso: Curso
    cortes: list[FilaCorteDetalle]
    seleccionada: Optional[FilaCorteDetalle]
    riesgo_alto: bool
    configuracion: Optional[ConfiguracionAlerta]

    @property
    def motivo(self) -> Optional[str]:
        """Motivo de la alerta seleccionada: nota, inasistencia o ambos."""
        alerta = self.seleccionada.alerta if self.seleccionada else None
        if alerta is None or alerta.estado_alerta == calculos.ESTADO_VERDE:
            return None
        if alerta.motivo_nota and alerta.motivo_inasistencia:
            return "ambos"
        return "nota" if alerta.motivo_nota else "inasistencia"


def detalle_alerta(
    inscripcion_id: int, numero_corte: Optional[int] = None
) -> DetalleAlerta:
    """Notas por corte y valores de la alerta de una inscripción (RF-45).

    Raises:
        ErrorNegocio: la inscripción no existe.
    """
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-45
    inscripcion = db.session.scalar(
        select(Inscripcion)
        .options(
            joinedload(Inscripcion.matricula_periodo).joinedload(
                MatriculaPeriodo.estudiante
            ),
            joinedload(Inscripcion.curso).joinedload(Curso.asignatura),
            joinedload(Inscripcion.curso).joinedload(Curso.profesor),
            joinedload(Inscripcion.curso).joinedload(Curso.periodo_academico),
        )
        .where(Inscripcion.id == inscripcion_id)
    )
    if inscripcion is None:
        raise ErrorNegocio("La inscripción no existe.")
    cortes = sorted(inscripcion.curso.periodo_academico.cortes, key=lambda c: c.numero)
    notas = dict(
        db.session.execute(
            select(NotaCorte.corte_id, NotaCorte.nota).where(
                NotaCorte.inscripcion_id == inscripcion.id
            )
        ).all()
    )
    por_corte = {
        alerta.corte_id: alerta
        for alerta in db.session.scalars(
            select(Alerta)
            .options(joinedload(Alerta.configuracion_alerta))
            .where(Alerta.inscripcion_id == inscripcion.id)
        )
    }
    filas = [FilaCorteDetalle(c, notas.get(c.id), por_corte.get(c.id)) for c in cortes]
    con_alerta = [f for f in filas if f.alerta is not None]
    seleccionada = next(
        (f for f in filas if f.corte.numero == numero_corte and f.alerta), None
    ) or (con_alerta[-1] if con_alerta else None)
    estudiante = inscripcion.matricula_periodo.estudiante
    return DetalleAlerta(
        inscripcion=inscripcion,
        estudiante=estudiante,
        curso=inscripcion.curso,
        cortes=filas,
        seleccionada=seleccionada,
        riesgo_alto=bool(
            seleccionada and es_riesgo_alto(estudiante.id, seleccionada.corte.id)
        ),
        configuracion=(
            seleccionada.alerta.configuracion_alerta if seleccionada else None
        ),
    )


# ---------------------------------------------------------------------------
# RF-47: histórico del estudiante
# ---------------------------------------------------------------------------


@dataclass
class FilaHistorico:
    """Una asignatura cursada en un semestre (RF-47)."""

    inscripcion: Inscripcion
    notas: list[Optional[Decimal]]
    acumulada: Optional[Decimal]
    horas_ausentes: int
    horas_totales: int
    inasistencia: Decimal
    resultado: str
    motivo: Optional[str]

    @property
    def nombre_resultado(self) -> str:
        """Nombre visible del resultado."""
        return NOMBRES_RESULTADO[self.resultado]

    @property
    def nombre_motivo(self) -> str:
        """Motivo legible de la pérdida o de la aprobación."""
        if self.resultado == RESULTADO_PERDIDA and self.motivo:
            return NOMBRES_MOTIVO[self.motivo]
        if self.resultado == RESULTADO_APROBADA:
            return "Cumple nota e inasistencia"
        return ""


@dataclass
class SemestreHistorico:
    """Un período del histórico con sus asignaturas (RF-47)."""

    periodo: PeriodoAcademico
    semestre_cursado: int
    cortes: list[Corte]
    filas: list[FilaHistorico] = field(default_factory=list)

    @property
    def aprobadas(self) -> int:
        """Asignaturas aprobadas."""
        return sum(1 for f in self.filas if f.resultado == RESULTADO_APROBADA)

    @property
    def perdidas(self) -> int:
        """Asignaturas perdidas."""
        return sum(1 for f in self.filas if f.resultado == RESULTADO_PERDIDA)


def resultado_final(
    acumulada: Optional[Decimal],
    inasistencia: Decimal,
    configuracion: calculos.Umbrales,
) -> tuple[str, Optional[str]]:
    """Resultado de una asignatura terminada y su motivo (RF-47).

    Sin redondear: 3,0 exacto aprueba. Pierde por nota si la acumulada final es
    menor que la nota de aprobación y por inasistencia si supera el límite.
    """
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-47
    por_nota = acumulada is None or acumulada < configuracion.nota_aprobacion
    por_inasistencia = inasistencia > configuracion.limite_perdida_inasistencia
    if por_nota and por_inasistencia:
        return RESULTADO_PERDIDA, "ambos"
    if por_nota:
        return RESULTADO_PERDIDA, "nota"
    if por_inasistencia:
        return RESULTADO_PERDIDA, "inasistencia"
    return RESULTADO_APROBADA, None


def configuracion_del_periodo(
    periodo: PeriodoAcademico,
    cortes: list[Corte],
    configuraciones: list[ConfiguracionAlerta],
) -> ConfiguracionAlerta:
    """Umbrales vigentes al terminar el período (RF-47).

    El período termina en su fecha de fin o, antes, cuando se cierra su último
    corte. Se usa la configuración más reciente vigente en ese momento, de modo
    que un cambio posterior de umbrales no altera el histórico. Si ninguna era
    vigente todavía, se usa la más antigua registrada.

    Args:
        configuraciones: todas las configuraciones, ordenadas de la más antigua
            a la más reciente (no vacía).
    """
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-47
    fin = dt.datetime.combine(periodo.fecha_fin, dt.time.max)
    if cortes and all(c.cerrado_en is not None for c in cortes):
        fin = min(fin, max(c.cerrado_en for c in cortes))
    aplicable = configuraciones[0]
    for configuracion in configuraciones:
        if configuracion.vigente_desde > fin:
            break
        aplicable = configuracion
    return aplicable


def historico_estudiante(
    estudiante_id: int,
) -> tuple[Estudiante, list[SemestreHistorico]]:
    """Histórico por semestre, del más reciente al más antiguo (RF-47).

    Raises:
        ErrorNegocio: el estudiante no existe o no hay umbrales configurados.
    """
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-47
    estudiante = db.session.get(Estudiante, estudiante_id)
    if estudiante is None:
        raise ErrorNegocio("El estudiante no existe.")
    configuraciones = db.session.scalars(
        select(ConfiguracionAlerta).order_by(
            ConfiguracionAlerta.vigente_desde, ConfiguracionAlerta.id
        )
    ).all()
    if not configuraciones:
        raise ErrorNegocio("No hay umbrales de alerta configurados (RF-20).")
    matriculas = db.session.scalars(
        select(MatriculaPeriodo)
        .join(
            PeriodoAcademico,
            PeriodoAcademico.id == MatriculaPeriodo.periodo_academico_id,
        )
        .options(
            joinedload(MatriculaPeriodo.periodo_academico).selectinload(
                PeriodoAcademico.cortes
            )
        )
        .where(MatriculaPeriodo.estudiante_id == estudiante.id)
        .order_by(PeriodoAcademico.fecha_inicio.desc())
    ).all()
    if not matriculas:
        return estudiante, []
    inscripciones = db.session.scalars(
        select(Inscripcion)
        .options(
            joinedload(Inscripcion.curso).joinedload(Curso.asignatura),
            joinedload(Inscripcion.curso).joinedload(Curso.profesor),
        )
        .where(Inscripcion.matricula_periodo_id.in_([m.id for m in matriculas]))
    ).all()
    ids = [i.id for i in inscripciones] or [0]
    cursos = list({i.curso_id for i in inscripciones}) or [0]
    notas: dict[tuple[int, int], Decimal] = {
        (inscripcion_id, numero): nota
        for inscripcion_id, numero, nota in db.session.execute(
            select(NotaCorte.inscripcion_id, Corte.numero, NotaCorte.nota)
            .join(Corte, Corte.id == NotaCorte.corte_id)
            .where(NotaCorte.inscripcion_id.in_(ids))
        )
    }
    totales = dict(
        db.session.execute(
            select(SesionClase.curso_id, func.sum(SesionClase.duracion_horas))
            .where(SesionClase.curso_id.in_(cursos))
            .group_by(SesionClase.curso_id)
        ).all()
    )
    ausentes = dict(
        db.session.execute(
            select(Ausencia.inscripcion_id, func.sum(SesionClase.duracion_horas))
            .join(SesionClase, SesionClase.id == Ausencia.sesion_clase_id)
            .where(Ausencia.inscripcion_id.in_(ids), Ausencia.ausente.is_(True))
            .group_by(Ausencia.inscripcion_id)
        ).all()
    )
    hoy = ahora().date()
    por_matricula: dict[int, list[Inscripcion]] = {}
    for inscripcion in inscripciones:
        por_matricula.setdefault(inscripcion.matricula_periodo_id, []).append(
            inscripcion
        )

    semestres: list[SemestreHistorico] = []
    for matricula in matriculas:
        periodo = matricula.periodo_academico
        cortes = sorted(periodo.cortes, key=lambda c: c.numero)
        terminado = hoy > periodo.fecha_fin or (
            bool(cortes) and all(c.cerrado_en is not None for c in cortes)
        )
        semestre = SemestreHistorico(periodo, matricula.semestre_cursado, cortes)
        for inscripcion in sorted(
            por_matricula.get(matricula.id, []),
            key=lambda i: (i.curso.asignatura.nivel, i.curso.asignatura.nombre),
        ):
            valores = [notas.get((inscripcion.id, c.numero)) for c in cortes]
            acumulada = calculos.nota_acumulada(
                zip(valores, [c.peso_porcentaje for c in cortes])
            )
            horas_totales = int(totales.get(inscripcion.curso_id) or 0)
            horas_ausentes = int(ausentes.get(inscripcion.id) or 0)
            inasistencia = calculos.porcentaje(
                horas_ausentes, horas_totales
            ) or Decimal("0")
            if inscripcion.retirada_en is not None:
                resultado, motivo = RESULTADO_RETIRADA, None
            elif terminado:
                resultado, motivo = resultado_final(
                    acumulada,
                    inasistencia,
                    configuracion_del_periodo(periodo, cortes, configuraciones),
                )
            else:
                resultado, motivo = RESULTADO_EN_CURSO, None
            semestre.filas.append(
                FilaHistorico(
                    inscripcion,
                    valores,
                    acumulada,
                    horas_ausentes,
                    horas_totales,
                    inasistencia,
                    resultado,
                    motivo,
                )
            )
        semestres.append(semestre)
    return estudiante, semestres


def buscar_estudiantes(texto: str, limite: int = 25) -> list[Estudiante]:
    """Búsqueda por código o nombre para abrir el histórico (RF-47)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-47
    limpio = (texto or "").strip()[:150]
    if len(limpio) < 3:
        return []
    return list(
        db.session.scalars(
            select(Estudiante)
            .where(
                or_(
                    Estudiante.codigo.contains(limpio, autoescape=True),
                    Estudiante.nombres.contains(limpio, autoescape=True),
                )
            )
            .order_by(Estudiante.nombres)
            .limit(limite)
        )
    )


# ---------------------------------------------------------------------------
# RF-48: resultados por asignatura, curso y corte
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FiltrosResultados:
    """Filtros de RF-48 (el período y el corte se eligen aparte)."""

    asignatura_id: Optional[int] = None
    curso_id: Optional[int] = None
    profesor_id: Optional[int] = None


@dataclass
class FilaResultado:
    """Totales de un curso en un corte (RF-48)."""

    asignatura: str
    nombre_asignatura: str
    curso: str
    curso_id: int
    profesor: str
    inscritos: int
    aprobados: int
    en_alerta: int
    perdidos: int

    def porcentaje(self, valor: int) -> Optional[Decimal]:
        """Porcentaje sobre los inscritos."""
        return calculos.porcentaje(valor, self.inscritos)


def resultados(
    corte: Corte, filtros: FiltrosResultados
) -> tuple[list[FilaResultado], FilaResultado]:
    """Inscritos, aprobados, en alerta y perdidos por curso en el corte (RF-48).

    Se cuentan las alertas calculadas (RF-43), así los totales coinciden con la
    lista de alertas (RF-44). Con los umbrales con que se calculó cada alerta:

    - En alerta: amarilla o roja.
    - Perdido: inasistencia mayor que el límite, o nota requerida mayor que 5,0
      (en el último corte: acumulada final menor que la nota de aprobación).
    - Aprobado: inasistencia dentro del límite y nota requerida de 1,0 o menos
      (en el último corte: acumulada final mayor o igual a la de aprobación).
    """
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-48
    ultimo = corte.numero == max(c.numero for c in corte.periodo_academico.cortes)
    inasistencia_ok = (
        Alerta.porcentaje_inasistencia
        <= ConfiguracionAlerta.limite_perdida_inasistencia
    )
    if ultimo:
        aprobado = and_(
            Alerta.nota_acumulada >= ConfiguracionAlerta.nota_aprobacion,
            inasistencia_ok,
        )
        perdido = or_(
            Alerta.nota_acumulada.is_(None),
            Alerta.nota_acumulada < ConfiguracionAlerta.nota_aprobacion,
            ~inasistencia_ok,
        )
    else:
        aprobado = and_(
            Alerta.nota_requerida <= calculos.NOTA_MINIMA_ESCALA, inasistencia_ok
        )
        perdido = or_(
            Alerta.nota_requerida > calculos.NOTA_MAXIMA_ESCALA, ~inasistencia_ok
        )
    profesor = aliased(Usuario)
    consulta = (
        select(
            Asignatura.codigo,
            Asignatura.nombre,
            Curso.codigo,
            Curso.id,
            profesor.nombre_completo,
            func.count(Alerta.id),
            func.sum(case((aprobado, 1), else_=0)),
            func.sum(case((Alerta.estado_alerta.in_(alertas.TIPOS), 1), else_=0)),
            func.sum(case((perdido, 1), else_=0)),
        )
        .join(Inscripcion, Inscripcion.id == Alerta.inscripcion_id)
        .join(Curso, Curso.id == Inscripcion.curso_id)
        .join(Asignatura, Asignatura.id == Curso.asignatura_id)
        .join(profesor, profesor.id == Curso.profesor_usuario_id)
        .join(
            ConfiguracionAlerta,
            ConfiguracionAlerta.id == Alerta.configuracion_alerta_id,
        )
        .where(Alerta.corte_id == corte.id)
        .group_by(
            Asignatura.codigo,
            Asignatura.nombre,
            Curso.codigo,
            Curso.id,
            profesor.nombre_completo,
        )
        .order_by(Asignatura.nombre, Curso.codigo)
    )
    if filtros.asignatura_id:
        consulta = consulta.where(Curso.asignatura_id == filtros.asignatura_id)
    if filtros.curso_id:
        consulta = consulta.where(Curso.id == filtros.curso_id)
    if filtros.profesor_id:
        consulta = consulta.where(Curso.profesor_usuario_id == filtros.profesor_id)
    filas = [
        FilaResultado(a, n, c, cid, p, int(i), int(ap or 0), int(al or 0), int(pe or 0))
        for a, n, c, cid, p, i, ap, al, pe in db.session.execute(consulta)
    ]
    total = FilaResultado(
        "",
        "Total",
        "",
        0,
        "",
        sum(f.inscritos for f in filas),
        sum(f.aprobados for f in filas),
        sum(f.en_alerta for f in filas),
        sum(f.perdidos for f in filas),
    )
    return filas, total


def profesores_del_periodo(periodo: PeriodoAcademico) -> list[tuple[int, str]]:
    """Profesores con cursos en el período, para el filtro de RF-48."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-48
    return [
        (uid, nombre)
        for uid, nombre in db.session.execute(
            select(Usuario.id, Usuario.nombre_completo)
            .join(Curso, Curso.profesor_usuario_id == Usuario.id)
            .where(Curso.periodo_academico_id == periodo.id)
            .distinct()
            .order_by(Usuario.nombre_completo)
        )
    ]


def fecha_generacion() -> dt.datetime:
    """Fecha y hora de generación para reportes imprimibles (RF-60)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-60
    return ahora()
