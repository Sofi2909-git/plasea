"""Blueprint de la épica E5: Cierre de cortes (RF-35 a RF-39).

Pantallas del Auditor académico: seguimiento de envíos por corte (RF-35),
cierre manual (RF-36) y reaperturas excepcionales (RF-38, RF-39).

El cierre automático (RF-37) corre de dos formas, ambas idempotentes:

1. En la primera petición de cada día que atiende la aplicación (así funciona
   aunque el computador haya estado apagado) y al arrancar el planificador.
2. Con un planificador interno (APScheduler) que revisa a diario a las 00:10.

Además existe el comando ``flask cerrar-cortes-vencidos``.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

import click
from flask import (
    Blueprint,
    Flask,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from plasea.autorizacion import rol_requerido
from plasea.formularios.cierre_cortes import FormularioAccion, FormularioReapertura
from plasea.modelos import Corte, PeriodoAcademico, db
from plasea.servicios import cierre_cortes, periodos
from plasea.servicios.comunes import ErrorNegocio, ahora
from plasea.servicios.cuentas import ROL_AUDITOR

blueprint = Blueprint("cierre_cortes", __name__, cli_group=None)
registro_log = logging.getLogger(__name__)

_revision: dict[str, Any] = {"fecha": None, "planificador": None}
_candado = threading.Lock()


# ---------------------------------------------------------------------------
# RF-37: cierre automático
# ---------------------------------------------------------------------------


def _ejecutar_cierre_automatico(app: Flask) -> list[str]:
    """Cierra los cortes vencidos dentro del contexto de la aplicación."""
    # Responsable: Islender Arturo Alfonso
    # RF-37
    with app.app_context():
        try:
            cerrados = cierre_cortes.cerrar_vencidos()
        except Exception:
            db.session.rollback()
            registro_log.exception("Falló la revisión de cortes vencidos")
            return []
        if cerrados:
            registro_log.info(
                "Cortes cerrados automáticamente: %s", ", ".join(cerrados)
            )
        return cerrados


def _iniciar_planificador(app: Flask) -> None:
    """Programa la revisión diaria (00:10, hora de Colombia)."""
    # Responsable: Islender Arturo Alfonso
    # RF-37
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        registro_log.warning("APScheduler no está instalado: solo revisión diaria.")
        return
    planificador = BackgroundScheduler(timezone="America/Bogota", daemon=True)
    planificador.add_job(
        _ejecutar_cierre_automatico,
        "cron",
        hour=0,
        minute=10,
        args=[app],
        id="cierre_cortes_vencidos",
        replace_existing=True,
    )
    planificador.start()
    _revision["planificador"] = planificador


@blueprint.before_app_request
def revisar_cortes_vencidos() -> None:
    """Revisión de RF-37 en la primera petición de cada día."""
    # Responsable: Islender Arturo Alfonso
    # RF-37
    app = current_app._get_current_object()  # type: ignore[attr-defined]
    if app.config.get("TESTING") or not app.config.get("CIERRE_AUTOMATICO", True):
        return
    hoy = ahora().date()
    if _revision["fecha"] == hoy:
        return
    with _candado:
        if _revision["fecha"] == hoy:
            return
        _revision["fecha"] = hoy
        if _revision["planificador"] is None:
            _iniciar_planificador(app)
    _ejecutar_cierre_automatico(app)


@blueprint.cli.command("cerrar-cortes-vencidos")
def comando_cerrar_vencidos() -> None:
    """Cierra los cortes con el límite de corrección vencido (RF-37)."""
    # Responsable: Islender Arturo Alfonso
    # RF-37
    cerrados = cierre_cortes.cerrar_vencidos()
    click.echo(
        "Cortes cerrados: " + ", ".join(cerrados)
        if cerrados
        else "No hay cortes vencidos."
    )


# ---------------------------------------------------------------------------
# RF-35 y RF-36: seguimiento y cierre manual
# ---------------------------------------------------------------------------


def _seleccion() -> tuple[Optional[PeriodoAcademico], Optional[Corte]]:
    """Período y corte elegidos en la petición, o los actuales."""
    # Responsable: Islender Arturo Alfonso
    # RF-35
    periodo = None
    periodo_id = request.args.get("periodo", type=int)
    if periodo_id:
        periodo = db.session.get(PeriodoAcademico, periodo_id)
    periodo = periodo or periodos.periodo_en_curso()
    if periodo is None:
        return None, None
    numero = request.args.get("corte", type=int)
    corte = next((c for c in periodo.cortes if c.numero == numero), None)
    return periodo, corte or cierre_cortes.corte_actual(periodo)


@blueprint.get("/")
@rol_requerido(ROL_AUDITOR)
def panel() -> Any:
    """Cursos enviados y pendientes del corte con su profesor (RF-35)."""
    # Responsable: Islender Arturo Alfonso
    # RF-35
    periodo, corte = _seleccion()
    solo_pendientes = request.args.get("pendientes") == "1"
    filas = cierre_cortes.seguimiento(corte, solo_pendientes) if corte else []
    return render_template(
        "cortes/panel.html",
        periodo=periodo,
        corte=corte,
        periodos=periodos.listar_periodos(),
        filas=filas,
        resumen=cierre_cortes.resumen_seguimiento(corte) if corte else {},
        solo_pendientes=solo_pendientes,
        motivo_no_cierre=(
            cierre_cortes.motivo_no_cierre(corte, ahora().date()) if corte else None
        ),
        reaperturas=cierre_cortes.reaperturas_del_corte(corte) if corte else [],
        formulario=FormularioAccion(),
        hoy=ahora().date(),
    )


def _volver(corte: Optional[Corte]) -> Any:
    """Redirección al seguimiento del corte."""
    # Responsable: Islender Arturo Alfonso
    # RF-35
    if corte is None:
        return redirect(url_for("cierre_cortes.panel"))
    return redirect(
        url_for(
            "cierre_cortes.panel",
            periodo=corte.periodo_academico_id,
            corte=corte.numero,
        )
    )


@blueprint.post("/<int:corte_id>/cerrar")
@rol_requerido(ROL_AUDITOR)
def cerrar(corte_id: int) -> Any:
    """Cierre manual del corte (RF-36)."""
    # Responsable: Islender Arturo Alfonso
    # RF-36
    if not FormularioAccion().validate_on_submit():
        abort(400)
    try:
        resultado = cierre_cortes.cerrar_corte(corte_id, g.usuario.id)
    except ErrorNegocio as fallo:
        flash(fallo.mensaje, "error")
    else:
        flash(
            f"Corte cerrado: {resultado['cerrados']} curso(s) enviados, "
            f"{resultado['sin_registro']} sin registro. Las alertas son definitivas.",
            "exito",
        )
    return _volver(db.session.get(Corte, corte_id))


# ---------------------------------------------------------------------------
# RF-38 y RF-39: reaperturas
# ---------------------------------------------------------------------------


@blueprint.route("/registros/<int:registro_id>/reabrir", methods=["GET", "POST"])
@rol_requerido(ROL_AUDITOR)
def reabrir(registro_id: int) -> Any:
    """Reapertura de un curso de un corte cerrado con motivo (RF-38)."""
    # Responsable: Islender Arturo Alfonso
    # RF-38
    try:
        registro = cierre_cortes.obtener_registro(registro_id)
    except ErrorNegocio:
        abort(404)
    formulario = FormularioReapertura()
    error = None
    if formulario.validate_on_submit():
        try:
            cierre_cortes.reabrir(registro.id, formulario.motivo.data, g.usuario.id)
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            flash(
                f"Se reabrió {registro.curso.asignatura.codigo} "
                f"{registro.curso.codigo} "
                f"en el corte {registro.corte.numero}. El profesor solo puede "
                "modificar lo ya registrado.",
                "exito",
            )
            return _volver(registro.corte)
    return render_template(
        "cortes/reabrir.html", registro=registro, formulario=formulario, error=error
    )


@blueprint.post("/reaperturas/<int:reapertura_id>/cerrar")
@rol_requerido(ROL_AUDITOR)
def cerrar_reapertura(reapertura_id: int) -> Any:
    """Cierre manual de una reapertura (RF-39)."""
    # Responsable: Islender Arturo Alfonso
    # RF-39
    if not FormularioAccion().validate_on_submit():
        abort(400)
    try:
        reapertura = cierre_cortes.cerrar_reapertura(reapertura_id, g.usuario.id)
    except ErrorNegocio as fallo:
        flash(fallo.mensaje, "error")
        return redirect(url_for("cierre_cortes.panel"))
    flash(
        "Se cerró la reapertura: el curso quedó bloqueado y se recalcularon "
        "las alertas.",
        "exito",
    )
    return _volver(reapertura.registro_curso_corte.corte)
