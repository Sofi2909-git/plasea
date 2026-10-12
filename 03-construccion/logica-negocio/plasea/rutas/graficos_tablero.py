"""Blueprint de la épica E8: Gráficos del tablero (RF-54 a RF-56).

Una pantalla del Auditor académico con tres gráficos de barras dibujados con
HTML y CSS (sin librerías externas ni CDN), cada uno con su tabla de datos:

- RF-54: estudiantes en verde, amarillo y rojo por corte y período.
- RF-55: inscritos por semestre y cuántos continúan en el siguiente.
- RF-56: no continuidad por semestre de la carrera (1 a 10) de un período.
"""

from __future__ import annotations

from typing import Any, Optional

from flask import Blueprint, render_template, request

from plasea.autorizacion import rol_requerido
from plasea.modelos import PeriodoAcademico, db
from plasea.rutas.alertas_analitica import seleccion_corte
from plasea.servicios import continuidad, graficos, periodos
from plasea.servicios.cuentas import ROL_AUDITOR

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
