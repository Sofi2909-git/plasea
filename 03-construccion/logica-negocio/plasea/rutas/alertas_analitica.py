"""Blueprint de la épica E6: Alertas y analítica (RF-40 a RF-48).

- RF-44: lista de alertas (Islender Arturo Alfonso).
- RF-45 a RF-48: detalle de la alerta, riesgo alto, histórico del estudiante y
  resultados por asignatura y curso (Wilson D'Alessandro Saavedra Rolón).

Los cálculos de RF-40 a RF-43 viven en ``servicios/calculos.py`` y
``servicios/alertas.py``; la analítica en ``servicios/analitica.py``.
"""

from __future__ import annotations

from typing import Any, Optional

from flask import Blueprint, abort, render_template, request

from plasea.autorizacion import rol_requerido
from plasea.modelos import Corte, PeriodoAcademico, db
from plasea.servicios import alertas, analitica, periodos
from plasea.servicios.comunes import ErrorNegocio
from plasea.servicios.cuentas import ROL_AUDITOR

blueprint = Blueprint("alertas_analitica", __name__)


def _entero(nombre: str) -> Optional[int]:
    """Parámetro entero positivo de la consulta, o ``None``."""
    # Responsable: Islender Arturo Alfonso
    # RF-44
    valor = request.args.get(nombre, type=int)
    return valor if valor and valor > 0 else None


def seleccion_corte(
    por_defecto=alertas.corte_por_defecto,
) -> tuple[Optional[PeriodoAcademico], Optional[Corte]]:
    """Período y corte de la petición, o los actuales (RF-44, RF-48, RF-58)."""
    # Responsable: Islender Arturo Alfonso
    # RF-44
    periodo_id = _entero("periodo")
    periodo = db.session.get(PeriodoAcademico, periodo_id) if periodo_id else None
    periodo = periodo or periodos.periodo_en_curso()
    if periodo is None:
        return None, None
    numero = _entero("corte")
    corte = next((c for c in periodo.cortes if c.numero == numero), None)
    return periodo, corte or por_defecto(periodo)


def filtros_alertas() -> alertas.FiltrosAlertas:
    """Filtros de la lista de alertas leídos de la petición (RF-44, RF-58)."""
    # Responsable: Islender Arturo Alfonso
    # RF-44
    return alertas.FiltrosAlertas(
        asignatura_id=_entero("asignatura"),
        curso_id=_entero("curso"),
        tipo=request.args.get("tipo") or None,
        motivo=request.args.get("motivo") or None,
        solo_riesgo_alto=request.args.get("riesgo") == "1",
    )


def filtros_resultados() -> analitica.FiltrosResultados:
    """Filtros de resultados leídos de la petición (RF-48, RF-59)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-48
    return analitica.FiltrosResultados(
        asignatura_id=_entero("asignatura"),
        curso_id=_entero("curso"),
        profesor_id=_entero("profesor"),
    )


def _parametros() -> dict[str, str]:
    """Parámetros de la consulta sin la página (para paginar y exportar)."""
    # Responsable: Islender Arturo Alfonso
    # RF-44
    return {k: v for k, v in request.args.items() if k != "pagina" and v}


@blueprint.get("/")
@rol_requerido(ROL_AUDITOR)
def lista() -> Any:
    """Estudiantes en alerta de un corte, ordenados por severidad (RF-44)."""
    # Responsable: Islender Arturo Alfonso
    # RF-44
    periodo, corte = seleccion_corte()
    filtros = filtros_alertas()
    contexto: dict[str, Any] = {
        "periodo": periodo,
        "corte": corte,
        "periodos": periodos.listar_periodos(),
        "filtros": filtros,
        "parametros": _parametros(),
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


# ---------------------------------------------------------------------------
# RF-45 y RF-46: detalle de la alerta y riesgo alto
# ---------------------------------------------------------------------------


@blueprint.get("/detalle/<int:inscripcion_id>")
@rol_requerido(ROL_AUDITOR)
def lista_detalle(inscripcion_id: int) -> Any:
    """Detalle de la alerta de un estudiante en una asignatura (RF-45)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-45
    try:
        datos = analitica.detalle_alerta(inscripcion_id, _entero("corte"))
    except ErrorNegocio:
        abort(404)
    return render_template(
        "alertas/detalle.html", d=datos, motivos=analitica.NOMBRES_MOTIVO
    )


# ---------------------------------------------------------------------------
# RF-47: histórico del estudiante
# ---------------------------------------------------------------------------


@blueprint.get("/historico")
@rol_requerido(ROL_AUDITOR)
def historico_buscar() -> Any:
    """Búsqueda de estudiantes para abrir su histórico (RF-47)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-47
    texto = request.args.get("q", "").strip()
    return render_template(
        "alertas/historico_buscar.html",
        texto=texto,
        encontrados=analitica.buscar_estudiantes(texto) if texto else [],
    )


@blueprint.get("/historico/<int:estudiante_id>")
@rol_requerido(ROL_AUDITOR)
def historico(estudiante_id: int) -> Any:
    """Histórico académico por semestre (RF-47)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-47
    try:
        estudiante, semestres = analitica.historico_estudiante(estudiante_id)
    except ErrorNegocio:
        abort(404)
    return render_template(
        "alertas/historico.html", estudiante=estudiante, semestres=semestres
    )


# ---------------------------------------------------------------------------
# RF-48: resultados por asignatura, curso y corte
# ---------------------------------------------------------------------------


@blueprint.get("/resultados")
@rol_requerido(ROL_AUDITOR)
def resultados() -> Any:
    """Inscritos, aprobados, en alerta y perdidos por curso y corte (RF-48)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-48
    periodo, corte = seleccion_corte()
    filtros = filtros_resultados()
    contexto: dict[str, Any] = {
        "periodo": periodo,
        "corte": corte,
        "periodos": periodos.listar_periodos(),
        "filtros": filtros,
        "parametros": _parametros(),
    }
    if corte is not None:
        filas, total = analitica.resultados(corte, filtros)
        asignaturas, cursos = alertas.opciones_filtro(corte)
        contexto.update(
            filas=filas,
            total=total,
            cortes=alertas.cortes_con_alertas(periodo),
            asignaturas=asignaturas,
            cursos=cursos,
            profesores=analitica.profesores_del_periodo(periodo),
        )
    return render_template("alertas/resultados.html", **contexto)
