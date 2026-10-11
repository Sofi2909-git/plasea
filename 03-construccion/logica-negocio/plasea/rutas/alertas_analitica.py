"""Blueprint de la épica E6: Alertas y analítica (RF-40 a RF-48).

Este módulo implementa la lista de alertas del Auditor académico (RF-44). Los
cálculos de RF-40 a RF-43 viven en ``servicios/calculos.py`` y
``servicios/alertas.py``. El detalle (RF-45), el riesgo alto como marcador
(RF-46), el histórico (RF-47) y los resultados (RF-48) son de otro módulo.
"""

from __future__ import annotations

from typing import Any, Optional

from flask import Blueprint, render_template, request

from plasea.autorizacion import rol_requerido
from plasea.modelos import Corte, PeriodoAcademico, db
from plasea.servicios import alertas, periodos
from plasea.servicios.cuentas import ROL_AUDITOR

blueprint = Blueprint("alertas_analitica", __name__)


def _entero(nombre: str) -> Optional[int]:
    """Parámetro entero positivo de la consulta, o ``None``."""
    # Responsable: Islender Arturo Alfonso
    # RF-44
    valor = request.args.get(nombre, type=int)
    return valor if valor and valor > 0 else None


@blueprint.get("/")
@rol_requerido(ROL_AUDITOR)
def lista() -> Any:
    """Estudiantes en alerta de un corte, ordenados por severidad (RF-44)."""
    # Responsable: Islender Arturo Alfonso
    # RF-44
    periodo_id = _entero("periodo")
    periodo = db.session.get(PeriodoAcademico, periodo_id) if periodo_id else None
    periodo = periodo or periodos.periodo_en_curso()
    corte: Optional[Corte] = None
    if periodo is not None:
        numero = _entero("corte")
        corte = next((c for c in periodo.cortes if c.numero == numero), None)
        corte = corte or alertas.corte_por_defecto(periodo)
    filtros = alertas.FiltrosAlertas(
        asignatura_id=_entero("asignatura"),
        curso_id=_entero("curso"),
        tipo=request.args.get("tipo") or None,
        motivo=request.args.get("motivo") or None,
        solo_riesgo_alto=request.args.get("riesgo") == "1",
    )
    contexto: dict[str, Any] = {
        "periodo": periodo,
        "corte": corte,
        "periodos": periodos.listar_periodos(),
        "filtros": filtros,
        "parametros": {
            clave: valor
            for clave, valor in request.args.items()
            if clave != "pagina" and valor
        },
    }
    if corte is not None:
        paginacion, en_riesgo = alertas.listar_alertas(
            corte, filtros, request.args.get("pagina", 1, type=int)
        )
        asignaturas, cursos = alertas.opciones_filtro(corte)
        contexto.update(
            paginacion=paginacion,
            en_riesgo=en_riesgo,
            resumen=alertas.resumen_corte(corte),
            cortes=alertas.cortes_con_alertas(periodo),
            asignaturas=asignaturas,
            cursos=cursos,
        )
    return render_template("alertas/lista.html", **contexto)
