"""Blueprint de la épica E8: Gráficos del tablero (RF-54 a RF-56).

Una pantalla del Auditor académico con tres gráficos de barras dibujados con
HTML y CSS (sin librerías externas ni CDN), cada uno con su tabla de datos:

- RF-54: estudiantes en verde, amarillo y rojo por corte y período.
- RF-55: inscritos por semestre y cuántos continúan en el siguiente.
- RF-56: no continuidad por semestre de la carrera (1 a 10) de un período.

Y una pantalla del Profesor por cada uno de sus cursos:

- RF-66: notas registradas frente a inscritos por corte y estado de alerta de
  cada estudiante con su motivo.
"""

from __future__ import annotations

from typing import Any, Optional

from flask import Blueprint, flash, render_template, request

from plasea.autorizacion import curso_propio_o_error, rol_requerido
from plasea.modelos import PeriodoAcademico, db
from plasea.rutas.alertas_analitica import seleccion_corte
from plasea.servicios import continuidad, estadistica_profesor, graficos, periodos
from plasea.servicios.comunes import ErrorNegocio
from plasea.servicios.cuentas import ROL_AUDITOR, ROL_PROFESOR

blueprint = Blueprint("graficos_tablero", __name__)


def _periodo_continuidad(
    evaluables: list[PeriodoAcademico],
) -> Optional[PeriodoAcademico]:
    """Período elegido para RF-56; por defecto el más reciente evaluable."""
    # Responsable: Andrés Camilo Anaya García
    # RF-56
    periodo_id = request.args.get("periodo_nc", type=int)
    periodo = db.session.get(PeriodoAcademico, periodo_id) if periodo_id else None
    if periodo is None or periodo not in evaluables:
        return evaluables[0] if evaluables else None
    return periodo


@blueprint.get("/")
@rol_requerido(ROL_AUDITOR)
def tablero() -> Any:
    """Tablero con los gráficos de alertas y continuidad (RF-54 a RF-56)."""
    # Responsable: Andrés Camilo Anaya García
    # RF-54
    periodo, corte = seleccion_corte()
    semaforo = graficos.semaforo_por_corte(periodo) if periodo else []
    seleccionado = next((s for s in semaforo if corte and s.corte.id == corte.id), None)
    comparativo = graficos.comparativo_periodos()
    evaluables = continuidad.periodos_evaluables()
    periodo_nc = _periodo_continuidad(evaluables)
    total_nc, por_semestre = (
        graficos.no_continuidad_por_semestre(periodo_nc) if periodo_nc else (None, [])
    )
    return render_template(
        "graficos/tablero.html",
        periodos=periodos.listar_periodos(),
        periodo=periodo,
        corte=corte,
        semaforo=semaforo,
        seleccionado=seleccionado,
        maximo_semaforo=graficos.maximo(
            [seleccionado.verde, seleccionado.amarilla, seleccionado.roja]
            if seleccionado
            else []
        ),
        comparativo=comparativo,
        maximo_inscritos=graficos.maximo([f.inscritos for f in comparativo]),
        evaluables=evaluables,
        periodo_nc=periodo_nc,
        siguiente_nc=continuidad.periodo_siguiente(periodo_nc) if periodo_nc else None,
        por_semestre=por_semestre,
        maximo_indice=graficos.maximo([g.indice for g in por_semestre]),
        total_nc=total_nc,
    )


# ---------------------------------------------------------------------------
# RF-66: estadística de reporte del Profesor
# ---------------------------------------------------------------------------


@blueprint.get("/cursos/<int:curso_id>")
@rol_requerido(ROL_PROFESOR)
def reporte_curso(curso_id: int) -> Any:
    """Notas registradas y estado de cada estudiante de un curso propio (RF-66).

    Abrir por URL el curso de otro docente responde HTTP 403 (RF-02).
    """
    # Responsable: Sofi Celmar Galvis
    # RF-66
    curso = curso_propio_o_error(curso_id)
    corte = estadistica_profesor.corte_elegido(
        curso, request.args.get("corte", type=int)
    )
    try:
        datos = estadistica_profesor.reporte_curso(curso, corte)
    except ErrorNegocio as fallo:
        flash(fallo.mensaje, "error")
        datos = estadistica_profesor.reporte_curso(curso, None)
    return render_template(
        "graficos/reporte_curso.html",
        curso=curso,
        datos=datos,
        corte=datos.corte,
        estados=estadistica_profesor.ORDEN_ESTADO,
    )
