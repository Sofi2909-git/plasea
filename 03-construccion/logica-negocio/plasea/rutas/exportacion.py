"""Blueprint de la épica E10: Exportación (RF-58 a RF-60, RF-65 y RF-67).

- RF-58: CSV de la lista de alertas con los filtros de RF-44.
- RF-59: CSV de resultados por asignatura y curso con los filtros de RF-48.
- RF-60: vista imprimible del histórico (se guarda como PDF desde el navegador).
- RF-65: vista imprimible de la estadística de un curso (Auditor académico).
- RF-67: vista imprimible del reporte de un curso propio (Profesor).

Los PDF no se generan en el servidor: son vistas sin menús, en A4 o Carta, que
el navegador guarda como PDF con «Imprimir». Cada una queda en la bitácora
(RF-61) con el curso o el estudiante exportado.

Los filtros se leen con las mismas funciones de las pantallas, así el archivo
coincide con lo que se ve.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, abort, g, render_template, request

from plasea.autorizacion import curso_propio_o_error, rol_requerido
from plasea.rutas.alertas_analitica import (
    filtros_alertas,
    filtros_resultados,
    seleccion_corte,
)
from plasea.servicios import (
    analitica,
    estadistica_curso,
    estadistica_profesor,
    exportacion,
)
from plasea.servicios.comunes import ErrorNegocio
from plasea.servicios.cuentas import ROL_AUDITOR, ROL_PROFESOR

blueprint = Blueprint("exportacion", __name__)


def _descarga(nombre: str, contenido: bytes) -> Response:
    """Respuesta de descarga de un CSV sin caché."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-58
    return Response(
        contenido,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={nombre}"},
    )


@blueprint.get("/alertas.csv")
@rol_requerido(ROL_AUDITOR)
def alertas_csv() -> Any:
    """Exporta todas las alertas del filtro, no solo la página (RF-58)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-58
    _periodo, corte = seleccion_corte()
    if corte is None:
        abort(404)
    nombre, contenido, _total = exportacion.csv_alertas(
        corte, filtros_alertas(), g.usuario.id
    )
    return _descarga(nombre, contenido)


@blueprint.get("/resultados.csv")
@rol_requerido(ROL_AUDITOR)
def resultados_csv() -> Any:
    """Exporta los resultados por asignatura y curso (RF-59)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-59
    _periodo, corte = seleccion_corte()
    if corte is None:
        abort(404)
    nombre, contenido, _total = exportacion.csv_resultados(
        corte, filtros_resultados(), g.usuario.id
    )
    return _descarga(nombre, contenido)


@blueprint.get("/historico/<int:estudiante_id>")
@rol_requerido(ROL_AUDITOR)
def historico_imprimible(estudiante_id: int) -> Any:
    """Vista imprimible del histórico, sin menús, en A4 o Carta (RF-60)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-60
    try:
        estudiante, semestres = analitica.historico_estudiante(estudiante_id)
    except ErrorNegocio:
        abort(404)
    exportacion.registrar_vista_imprimible(
        estudiante.codigo, g.usuario.id, estudiante.id
    )
    return render_template(
        "exportacion/historico_imprimible.html",
        estudiante=estudiante,
        semestres=semestres,
        generado_en=analitica.fecha_generacion(),
        generado_por=g.usuario.nombre_completo,
    )


@blueprint.get("/curso/<int:curso_id>")
@rol_requerido(ROL_AUDITOR)
def estadistica_curso_imprimible(curso_id: int) -> Any:
    """Estadística de un curso con su gráfica, sin menús, en A4 o Carta (RF-65)."""
    # Responsable: Sofi Celmar Galvis
    # RF-65
    try:
        curso = estadistica_curso.obtener_curso(curso_id)
    except ErrorNegocio:
        abort(404)
    datos = estadistica_curso.estadistica(curso)
    exportacion.registrar_pdf_curso_auditor(curso, g.usuario.id)
    return render_template(
        "exportacion/estadistica_curso_imprimible.html",
        curso=curso,
        d=datos,
        generado_en=analitica.fecha_generacion(),
        generado_por=g.usuario.nombre_completo,
    )


@blueprint.get("/reporte-curso/<int:curso_id>")
@rol_requerido(ROL_PROFESOR)
def reporte_curso_imprimible(curso_id: int) -> Any:
    """Reporte de un curso propio con su gráfica, sin menús, en A4 o Carta (RF-67).

    Solo cursos propios: el curso de otro docente responde HTTP 403.
    """
    # Responsable: Sofi Celmar Galvis
    # RF-67
    curso = curso_propio_o_error(curso_id)
    corte = estadistica_profesor.corte_elegido(
        curso, request.args.get("corte", type=int)
    )
    try:
        datos = estadistica_profesor.reporte_curso(curso, corte)
    except ErrorNegocio:
        abort(404)
    exportacion.registrar_pdf_curso_profesor(curso, corte, g.usuario.id)
    return render_template(
        "exportacion/reporte_curso_imprimible.html",
        curso=curso,
        datos=datos,
        corte=corte,
        generado_en=estadistica_profesor.fecha_generacion(),
        generado_por=g.usuario.nombre_completo,
    )
