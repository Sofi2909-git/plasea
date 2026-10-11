"""Blueprint de la épica E7: Continuidad y deserción (RF-49 a RF-53).

Pantalla del Auditor académico con el índice de no continuidad del período
(RF-49, RF-50), su desglose por semestre cursado y por cohorte (RF-51), por
causa (RF-52) y la lista de quienes no continuaron con filtros (RF-53).
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from plasea.autorizacion import destino_seguro, rol_requerido
from plasea.formularios.continuidad import FormularioCausa
from plasea.modelos import PeriodoAcademico, db
from plasea.servicios import continuidad
from plasea.servicios.comunes import ErrorNegocio
from plasea.servicios.cuentas import ROL_AUDITOR

blueprint = Blueprint("continuidad_desercion", __name__)


@blueprint.get("/")
@rol_requerido(ROL_AUDITOR)
def panel() -> Any:
    """Índice de no continuidad, desgloses y lista con filtros (RF-49 a RF-53)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-50
    evaluables = continuidad.periodos_evaluables()
    periodo_id = request.args.get("periodo", type=int)
    periodo = db.session.get(PeriodoAcademico, periodo_id) if periodo_id else None
    if periodo is None or periodo not in evaluables:
        periodo = evaluables[0] if evaluables else None
    contexto: dict[str, Any] = {
        "evaluables": evaluables,
        "periodo": periodo,
        "causas": continuidad.causas(),
        "formulario": FormularioCausa(),
        "filtros": {
            "programa": request.args.get("programa", ""),
            "semestre": request.args.get("semestre", type=int),
            "causa": request.args.get("causa", ""),
        },
    }
    if periodo is not None:
        try:
            filas = continuidad.clasificar(periodo)
        except ErrorNegocio as fallo:
            flash(fallo.mensaje, "info")
            filas = []
        lista = continuidad.no_continuaron(
            filas,
            contexto["filtros"]["programa"] or None,
            contexto["filtros"]["semestre"],
            contexto["filtros"]["causa"] or None,
        )
        contexto.update(
            siguiente=continuidad.periodo_siguiente(periodo),
            total=continuidad.indicador(periodo.identificador, filas),
            por_semestre=continuidad.por_grupo(filas, lambda f: f.semestre),
            por_cohorte=continuidad.por_grupo(filas, lambda f: f.cohorte),
            por_causa=continuidad.por_causa(filas),
            lista=lista,
            historial=continuidad.historial_causas([f.matricula_id for f in lista]),
            programas=sorted({f.programa for f in filas}),
        )
    return render_template("continuidad/panel.html", **contexto)


@blueprint.post("/matriculas/<int:matricula_id>/causa")
@rol_requerido(ROL_AUDITOR)
def registrar_causa(matricula_id: int) -> Any:
    """Registra o cambia la causa de no continuidad, con historial (RF-52)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-52
    formulario = FormularioCausa()
    formulario.causa.choices = [(c.codigo, c.nombre) for c in continuidad.causas()]
    if not formulario.validate_on_submit():
        flash("Seleccione una causa de la lista.", "error")
    else:
        try:
            continuidad.registrar_causa(
                matricula_id, formulario.causa.data, g.usuario.id
            )
        except ErrorNegocio as fallo:
            flash(fallo.mensaje, "error")
        else:
            flash("Se registró la causa de no continuidad.", "exito")
    destino = destino_seguro(request.form.get("volver")) or url_for(
        "continuidad_desercion.panel"
    )
    return redirect(destino + f"#matricula-{matricula_id}")
