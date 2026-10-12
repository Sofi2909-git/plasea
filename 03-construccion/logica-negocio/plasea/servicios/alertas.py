"""Cálculo y consulta de alertas (RF-40 a RF-44).

- ``recalcular``: calcula y guarda la alerta de cada estudiante de uno o varios
  cursos en un corte, con la configuración vigente (RF-20). Es provisional
  mientras el corte está abierto y definitiva cuando está cerrado (RF-43).
- ``listar_alertas``: lista del Auditor académico con filtros y orden por
  severidad (RF-44).

Las consultas son por lotes: una por tipo de dato (inscritos, notas, horas
totales, horas dictadas, horas ausentes y alertas existentes), sin importar
cuántos estudiantes tenga el corte.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

from flask_sqlalchemy.pagination import Pagination
from sqlalchemy import and_, case, func, insert, or_, select
from sqlalchemy.orm import contains_eager

from plasea.modelos import (
    Alerta,
    Asignatura,
    Ausencia,
    Corte,
    Curso,
    Estudiante,
    Inscripcion,
    MatriculaPeriodo,
    NotaCorte,
    PeriodoAcademico,
    SesionClase,
    db,
)
from plasea.servicios import calculos, umbrales
from plasea.servicios.comunes import ErrorNegocio, ahora

ALERTAS_POR_PAGINA = 50
TIPOS = (calculos.ESTADO_ROJA, calculos.ESTADO_AMARILLA)
MOTIVOS = ("nota", "inasistencia", "ambos")
ASIGNATURAS_RIESGO_ALTO = 2


@dataclass(frozen=True)
class FiltrosAlertas:
    """Filtros de la lista de alertas (RF-44)."""

    asignatura_id: Optional[int] = None
    curso_id: Optional[int] = None
    tipo: Optional[str] = None
    motivo: Optional[str] = None
    solo_riesgo_alto: bool = False


def _cortes_del_periodo(corte: Corte) -> list[Corte]:
    """Cortes del período del corte, ordenados por número."""
    # Responsable: Islender Arturo Alfonso
    # RF-40
    return sorted(corte.periodo_academico.cortes, key=lambda c: c.numero)


def fecha_referencia(corte: Corte) -> dt.date:
    """Fecha hasta la que se cuentan ausencias y horas dictadas del corte."""
    # Responsable: Islender Arturo Alfonso
    # RF-42
    return min(ahora().date(), corte.fecha_fin)


def evaluar(
    corte: Corte, curso_ids: Optional[Iterable[int]] = None
) -> list[tuple[int, int, dict]]:
    """Calcula, sin guardar, la alerta de cada inscrito en el corte (RF-40 a RF-43).

    Lo usan ``recalcular`` (que guarda) y la vista del profesor de RF-34 (que
    muestra los valores vigentes aunque el curso aún no se haya enviado).

    Args:
        corte: corte que se evalúa.
        curso_ids: cursos a evaluar; ``None`` = todos los del período.

    Returns:
        Tuplas (inscripción, curso, valores de la fila de ``alertas``).

    Raises:
        ErrorNegocio: no hay configuración de umbrales (RF-20).
    """
    # Responsable: Islender Arturo Alfonso
    # RF-43
    configuracion = umbrales.configuracion_vigente()
    if configuracion is None:
        raise ErrorNegocio("No hay umbrales de alerta configurados (RF-20).")
    cortes = _cortes_del_periodo(corte)
    anteriores = [c for c in cortes if c.numero <= corte.numero]
    peso_restante = sum(
        (c.peso_porcentaje for c in cortes if c.numero > corte.numero), Decimal("0")
    )
    referencia = fecha_referencia(corte)
    periodo_id = corte.periodo_academico_id

    filtro_cursos = [Curso.periodo_academico_id == periodo_id]
    if curso_ids is not None:
        curso_ids = list(curso_ids)
        if not curso_ids:
            return []
        filtro_cursos.append(Curso.id.in_(curso_ids))
    cursos_sub = select(Curso.id).where(*filtro_cursos).scalar_subquery()

    inscripciones = db.session.execute(
        select(Inscripcion.id, Inscripcion.curso_id).where(
            Inscripcion.curso_id.in_(cursos_sub),
            or_(
                Inscripcion.retirada_en.is_(None),
                Inscripcion.retirada_en > referencia,
            ),
        )
    ).all()
    if not inscripciones:
        return []

    notas: dict[tuple[int, int], Decimal] = {}
    for inscripcion_id, corte_id, nota in db.session.execute(
        select(NotaCorte.inscripcion_id, NotaCorte.corte_id, NotaCorte.nota)
        .join(Inscripcion, Inscripcion.id == NotaCorte.inscripcion_id)
        .where(
            Inscripcion.curso_id.in_(cursos_sub),
            NotaCorte.corte_id.in_([c.id for c in anteriores]),
        )
    ):
        notas[(inscripcion_id, corte_id)] = nota

    def horas_por_curso(*condiciones):
        # Responsable: Islender Arturo Alfonso
        # RF-42
        return {
            curso_id: int(horas or 0)
            for curso_id, horas in db.session.execute(
                select(SesionClase.curso_id, func.sum(SesionClase.duracion_horas))
                .where(SesionClase.curso_id.in_(cursos_sub), *condiciones)
                .group_by(SesionClase.curso_id)
            )
        }

    totales = horas_por_curso()
    dictadas = horas_por_curso(SesionClase.fecha <= referencia)
    ausentes = {
        inscripcion_id: int(horas or 0)
        for inscripcion_id, horas in db.session.execute(
            select(Ausencia.inscripcion_id, func.sum(SesionClase.duracion_horas))
            .join(SesionClase, SesionClase.id == Ausencia.sesion_clase_id)
            .where(
                SesionClase.curso_id.in_(cursos_sub),
                SesionClase.fecha <= referencia,
                Ausencia.ausente.is_(True),
            )
            .group_by(Ausencia.inscripcion_id)
        )
    }
    definitiva = corte.cerrado_en is not None
    momento = ahora()
    filas: list[tuple[int, int, dict]] = []
    for inscripcion_id, curso_id in inscripciones:
        resultado = calculos.evaluar_alerta(
            configuracion,
            [
                (notas.get((inscripcion_id, c.id)), c.peso_porcentaje)
                for c in anteriores
            ],
            peso_restante,
            ausentes.get(inscripcion_id, 0),
            totales.get(curso_id, 0),
            dictadas.get(curso_id, 0),
        )
        valores = {
            "configuracion_alerta_id": configuracion.id,
            "estado_alerta": resultado.estado,
            "motivo_nota": resultado.motivo_nota,
            "motivo_inasistencia": resultado.motivo_inasistencia,
            "nota_corte": resultado.nota_corte,
            "nota_acumulada": calculos.redondear(resultado.nota_acumulada),
            "nota_requerida": calculos.redondear(
                min(resultado.nota_requerida, Decimal("999.99"))
                if resultado.nota_requerida is not None
                else None
            ),
            "horas_ausentes": min(
                ausentes.get(inscripcion_id, 0), totales.get(curso_id, 0)
            ),
            "horas_dictadas": dictadas.get(curso_id, 0),
            "horas_totales": totales.get(curso_id, 0),
            "porcentaje_inasistencia": calculos.redondear(
                min(resultado.porcentaje_inasistencia, calculos.CIEN)
            ),
            "porcentaje_ritmo": calculos.redondear(
                min(resultado.porcentaje_ritmo, calculos.CIEN)
                if resultado.porcentaje_ritmo is not None
                else None
            ),
            "definitiva": definitiva,
            "calculada_en": momento,
        }
        filas.append((inscripcion_id, curso_id, valores))
    return filas


def recalcular(corte: Corte, curso_ids: Optional[Iterable[int]] = None) -> int:
    """Calcula y guarda las alertas del corte para los cursos indicados (RF-43).

    No confirma la transacción: lo hace quien la llama, junto con el evento que
    origina el cálculo (envío, corrección, cierre o reapertura).

    Args:
        corte: corte que se evalúa.
        curso_ids: cursos a recalcular; ``None`` = todos los del período.

    Returns:
        Número de alertas calculadas.

    Raises:
        ErrorNegocio: no hay configuración de umbrales (RF-20).
    """
    # Responsable: Islender Arturo Alfonso
    # RF-43
    filas = evaluar(corte, curso_ids)
    if not filas:
        return 0
    existentes = {
        alerta.inscripcion_id: alerta
        for alerta in db.session.scalars(
            select(Alerta)
            .join(Inscripcion, Inscripcion.id == Alerta.inscripcion_id)
            .where(
                Alerta.corte_id == corte.id,
                Inscripcion.curso_id.in_({curso_id for _, curso_id, _ in filas}),
            )
        )
    }
    nuevas: list[dict] = []
    for inscripcion_id, _, valores in filas:
        existente = existentes.get(inscripcion_id)
        if existente is None:
            nuevas.append(
                {"inscripcion_id": inscripcion_id, "corte_id": corte.id, **valores}
            )
        else:
            for campo, valor in valores.items():
                setattr(existente, campo, valor)
    if nuevas:
        db.session.execute(insert(Alerta), nuevas)
    db.session.flush()
    return len(filas)


def recalcular_curso(curso_id: int, desde_numero: int) -> None:
    """Recalcula un curso en el corte indicado y en los siguientes que ya
    tengan alertas, porque la acumulada y la requerida dependen de los cortes
    anteriores (RF-31, RF-39). No confirma la transacción.
    """
    # Responsable: Islender Arturo Alfonso
    # RF-31
    curso = db.session.get(Curso, curso_id)
    if curso is None:
        return
    con_alertas = set(
        db.session.scalars(
            select(Alerta.corte_id)
            .join(Inscripcion, Inscripcion.id == Alerta.inscripcion_id)
            .where(Inscripcion.curso_id == curso_id)
            .distinct()
        )
    )
    for corte in sorted(curso.periodo_academico.cortes, key=lambda c: c.numero):
        if corte.numero == desde_numero or (
            corte.numero > desde_numero and corte.id in con_alertas
        ):
            recalcular(corte, [curso_id])


# ---------------------------------------------------------------------------
# RF-44: lista de alertas del Auditor académico
# ---------------------------------------------------------------------------


def cortes_con_alertas(periodo: PeriodoAcademico) -> list[tuple[Corte, int]]:
    """Cortes del período con el número de alertas amarillas o rojas."""
    # Responsable: Islender Arturo Alfonso
    # RF-44
    conteo = dict(
        db.session.execute(
            select(Alerta.corte_id, func.count(Alerta.id))
            .join(Corte, Corte.id == Alerta.corte_id)
            .where(
                Corte.periodo_academico_id == periodo.id,
                Alerta.estado_alerta.in_(TIPOS),
            )
            .group_by(Alerta.corte_id)
        ).all()
    )
    return [
        (corte, int(conteo.get(corte.id, 0)))
        for corte in sorted(periodo.cortes, key=lambda c: c.numero)
    ]


def corte_por_defecto(periodo: PeriodoAcademico) -> Optional[Corte]:
    """El corte más reciente que ya tiene alertas; si ninguno, el primero."""
    # Responsable: Islender Arturo Alfonso
    # RF-44
    cortes = cortes_con_alertas(periodo)
    con_datos = [corte for corte, total in cortes if total]
    if con_datos:
        return con_datos[-1]
    return cortes[0][0] if cortes else None


def subconsulta_riesgo_alto(corte_id: int):
    """Estudiantes con alerta amarilla o roja en 2 o más asignaturas del corte.

    Es la regla de riesgo alto (RF-46) que RF-44 necesita para filtrar; se
    calcula en la consulta, así se actualiza cada vez que se recalculan las
    alertas.
    """
    # Responsable: Islender Arturo Alfonso
    # RF-44
    return (
        select(MatriculaPeriodo.estudiante_id)
        .join(Inscripcion, Inscripcion.matricula_periodo_id == MatriculaPeriodo.id)
        .join(Alerta, Alerta.inscripcion_id == Inscripcion.id)
        .join(Curso, Curso.id == Inscripcion.curso_id)
        .where(Alerta.corte_id == corte_id, Alerta.estado_alerta.in_(TIPOS))
        .group_by(MatriculaPeriodo.estudiante_id)
        .having(
            func.count(func.distinct(Curso.asignatura_id)) >= ASIGNATURAS_RIESGO_ALTO
        )
    )


def listar_alertas(
    corte: Corte, filtros: FiltrosAlertas, pagina: int = 1
) -> tuple[Pagination, set[int]]:
    """Estudiantes en alerta de un corte, de mayor a menor severidad (RF-44).

    Orden: rojas primero, luego amarillas; dentro de cada una, mayor nota
    requerida y mayor inasistencia primero.

    Returns:
        (página de alertas con inscripción, estudiante, curso y asignatura
        cargados; identificadores de estudiantes en riesgo alto de la página).
    """
    # Responsable: Islender Arturo Alfonso
    # RF-44
    riesgo = subconsulta_riesgo_alto(corte.id)
    paginacion = db.paginate(
        consulta_alertas(corte, filtros),
        page=max(pagina, 1),
        per_page=ALERTAS_POR_PAGINA,
        error_out=False,
    )
    ids = {a.inscripcion.matricula_periodo.estudiante_id for a in paginacion.items}
    en_riesgo = (
        set(
            db.session.scalars(
                riesgo.where(MatriculaPeriodo.estudiante_id.in_(ids or {0}))
            )
        )
        if ids
        else set()
    )
    return paginacion, en_riesgo


def consulta_alertas(corte: Corte, filtros: FiltrosAlertas):
    """Consulta filtrada y ordenada por severidad, sin paginar (RF-44).

    La usan la lista paginada (RF-44) y la exportación de todas las filas del
    filtro (RF-58), así ambas coinciden.
    """
    # Responsable: Islender Arturo Alfonso
    # RF-44
    riesgo = subconsulta_riesgo_alto(corte.id)
    consulta = (
        select(Alerta)
        .join(Alerta.inscripcion)
        .join(Inscripcion.matricula_periodo)
        .join(MatriculaPeriodo.estudiante)
        .join(Inscripcion.curso)
        .join(Curso.asignatura)
        .options(
            contains_eager(Alerta.inscripcion)
            .contains_eager(Inscripcion.matricula_periodo)
            .contains_eager(MatriculaPeriodo.estudiante),
            contains_eager(Alerta.inscripcion)
            .contains_eager(Inscripcion.curso)
            .contains_eager(Curso.asignatura),
        )
        .where(Alerta.corte_id == corte.id, Alerta.estado_alerta.in_(TIPOS))
    )
    if filtros.asignatura_id:
        consulta = consulta.where(Curso.asignatura_id == filtros.asignatura_id)
    if filtros.curso_id:
        consulta = consulta.where(Curso.id == filtros.curso_id)
    if filtros.tipo in TIPOS:
        consulta = consulta.where(Alerta.estado_alerta == filtros.tipo)
    if filtros.motivo == "nota":
        consulta = consulta.where(
            Alerta.motivo_nota.is_(True), Alerta.motivo_inasistencia.is_(False)
        )
    elif filtros.motivo == "inasistencia":
        consulta = consulta.where(
            Alerta.motivo_nota.is_(False), Alerta.motivo_inasistencia.is_(True)
        )
    elif filtros.motivo == "ambos":
        consulta = consulta.where(
            and_(Alerta.motivo_nota.is_(True), Alerta.motivo_inasistencia.is_(True))
        )
    if filtros.solo_riesgo_alto:
        consulta = consulta.where(MatriculaPeriodo.estudiante_id.in_(riesgo))
    severidad = case((Alerta.estado_alerta == calculos.ESTADO_ROJA, 0), else_=1)
    consulta = consulta.order_by(
        severidad,
        Alerta.nota_requerida.is_(None),
        Alerta.nota_requerida.desc(),
        Alerta.porcentaje_inasistencia.desc(),
        Estudiante.nombres,
        Alerta.id,
    )
    return consulta


def resumen_corte(corte: Corte) -> dict[str, int]:
    """Totales de rojas, amarillas y riesgo alto del corte (RF-44)."""
    # Responsable: Islender Arturo Alfonso
    # RF-44
    conteo = dict(
        db.session.execute(
            select(Alerta.estado_alerta, func.count(Alerta.id))
            .where(Alerta.corte_id == corte.id)
            .group_by(Alerta.estado_alerta)
        ).all()
    )
    riesgo = db.session.scalar(
        select(func.count()).select_from(subconsulta_riesgo_alto(corte.id).subquery())
    )
    return {
        "roja": int(conteo.get(calculos.ESTADO_ROJA, 0)),
        "amarilla": int(conteo.get(calculos.ESTADO_AMARILLA, 0)),
        "verde": int(conteo.get(calculos.ESTADO_VERDE, 0)),
        "riesgo_alto": int(riesgo or 0),
    }


def opciones_filtro(corte: Corte) -> tuple[list[Asignatura], list[tuple[Curso, str]]]:
    """Asignaturas y cursos del período del corte para los filtros (RF-44)."""
    # Responsable: Islender Arturo Alfonso
    # RF-44
    filas = db.session.execute(
        select(Curso, Asignatura)
        .join(Asignatura, Asignatura.id == Curso.asignatura_id)
        .where(Curso.periodo_academico_id == corte.periodo_academico_id)
        .order_by(Asignatura.nombre, Curso.codigo)
    ).all()
    asignaturas: dict[int, Asignatura] = {}
    cursos: list[tuple[Curso, str]] = []
    for curso, asignatura in filas:
        asignaturas[asignatura.id] = asignatura
        cursos.append(
            (curso, f"{asignatura.codigo} {curso.codigo} · {asignatura.nombre}")
        )
    return list(asignaturas.values()), cursos
