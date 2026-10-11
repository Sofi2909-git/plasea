"""Blueprint de la épica E4: Registro de asistencia y notas (RF-26 a RF-34).

Este módulo implementa RF-26 a RF-29 para el Profesor. El envío (RF-30), las
correcciones (RF-31 a RF-33) y el resumen por estudiante (RF-34) pertenecen a
otros módulos de la misma épica.
"""

from __future__ import annotations

from typing import Any

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from plasea.autorizacion import rol_requerido
from plasea.formularios.registro_asistencia_notas import (
    FormularioAsistencia,
    FormularioNotas,
)
from plasea.servicios import cursos, periodos, registro_academico
from plasea.servicios.comunes import ErrorNegocio
from plasea.servicios.cuentas import ROL_PROFESOR
from plasea.servicios.registro_academico import AccesoDenegado, ErrorNotas

blueprint = Blueprint("registro_asistencia_notas", __name__)


def _curso_propio(curso_id: int) -> Any:
    """Curso del profesor autenticado; 404 si no existe y 403 si es de otro."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-27
    try:
        return registro_academico.obtener_curso_propio(curso_id, g.usuario.id)
    except AccesoDenegado:
        abort(403)
    except ErrorNegocio:
        abort(404)


@blueprint.get("/")
@rol_requerido(ROL_PROFESOR)
def mis_cursos() -> Any:
    """Cursos del profesor en el período en curso y estado de cada corte (RF-26)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-26
    periodo = periodos.periodo_en_curso()
    return render_template(
        "registro/mis_cursos.html",
        periodo=periodo,
        resumenes=registro_academico.cursos_del_profesor(g.usuario.id, periodo),
        dias=cursos.DIAS_SEMANA,
    )


@blueprint.get("/cursos/<int:curso_id>")
@rol_requerido(ROL_PROFESOR)
def curso(curso_id: int) -> Any:
    """Estudiantes inscritos, cortes y calendario de sesiones (RF-27, RF-28)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-27
    curso_actual = _curso_propio(curso_id)
    estados = registro_academico.estados_de_cortes(curso_actual)
    sesiones = registro_academico.sesiones_con_estado(curso_actual, estados)
    return render_template(
        "registro/curso.html",
        curso=curso_actual,
        estados=estados,
        corte_en_carga=registro_academico.corte_en_carga(estados),
        estudiantes=registro_academico.estudiantes_del_curso(curso_actual.id),
        sesiones=sesiones,
        grupos=[
            (item, [f for f in sesiones if f.corte_numero == item.corte.numero])
            for item in estados
        ],
        fuera_de_corte=[f for f in sesiones if f.corte_numero is None],
        dias=cursos.DIAS_SEMANA,
    )


def _ids_marcados(nombre: str) -> set[int]:
    """Lee una lista de identificadores enteros enviada por el formulario."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-28
    marcados: set[int] = set()
    for valor in request.form.getlist(nombre):
        if not valor.isdigit():
            abort(400)
        marcados.add(int(valor))
    return marcados


@blueprint.route(
    "/cursos/<int:curso_id>/sesiones/<int:sesion_id>/asistencia",
    methods=["GET", "POST"],
)
@rol_requerido(ROL_PROFESOR)
def asistencia(curso_id: int, sesion_id: int) -> Any:
    """Asistencia de una sesión: se marcan solo los ausentes (RF-28)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-28
    curso_actual = _curso_propio(curso_id)
    try:
        sesion = registro_academico.sesion_del_curso(curso_actual, sesion_id)
    except ErrorNegocio:
        abort(404)
    formulario = FormularioAsistencia()
    marcados = registro_academico.ausentes_de_sesion(sesion.id)
    error = None
    if formulario.validate_on_submit():
        marcados = _ids_marcados("ausentes")
        try:
            resultado = registro_academico.registrar_asistencia(
                curso_actual.id, sesion.id, marcados, g.usuario.id
            )
        except AccesoDenegado:
            abort(403)
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            if resultado.ausentes:
                flash(
                    f"Se guardó la asistencia del {sesion.fecha:%d/%m/%Y}: "
                    f"{resultado.ausentes} ausente(s), "
                    f"{resultado.horas_por_ausente} h a cada uno.",
                    "exito",
                )
            else:
                flash(
                    f"Se guardó la asistencia del {sesion.fecha:%d/%m/%Y}: "
                    "todos presentes.",
                    "exito",
                )
            return redirect(
                url_for("registro_asistencia_notas.curso", curso_id=curso_actual.id)
                + "#sesiones"
            )
    corte, estado, bloqueo = registro_academico.estado_de_sesion(curso_actual, sesion)
    return render_template(
        "registro/asistencia.html",
        curso=curso_actual,
        sesion=sesion,
        corte=corte,
        estado=estado,
        bloqueo=bloqueo,
        estudiantes=registro_academico.estudiantes_del_curso(
            curso_actual.id, en_fecha=sesion.fecha
        ),
        marcados=marcados,
        formulario=formulario,
        error=error,
    )


@blueprint.route(
    "/cursos/<int:curso_id>/cortes/<int:numero>/notas", methods=["GET", "POST"]
)
@rol_requerido(ROL_PROFESOR)
def notas(curso_id: int, numero: int) -> Any:
    """Planilla de notas de un corte con guardado en borrador (RF-29)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-29
    curso_actual = _curso_propio(curso_id)
    try:
        corte = registro_academico.corte_por_numero(curso_actual, numero)
    except ErrorNegocio:
        abort(404)
    formulario = FormularioNotas()
    filas = registro_academico.planilla_notas(curso_actual, corte)
    valores = {
        fila.inscripcion_id: (
            "" if fila.nota is None else f"{fila.nota}".replace(".", ",")
        )
        for fila in filas
    }
    errores: dict[int, str] = {}
    error = None
    if formulario.validate_on_submit():
        enviados = {
            fila.inscripcion_id: request.form.get(f"nota-{fila.inscripcion_id}", "")
            for fila in filas
        }
        valores.update(enviados)
        try:
            con_nota, sin_nota = registro_academico.guardar_notas(
                curso_actual.id, corte.numero, enviados, g.usuario.id
            )
        except AccesoDenegado:
            abort(403)
        except ErrorNotas as fallo:
            errores, error = fallo.errores, fallo.mensaje
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            detalle = f" Faltan {sin_nota}." if sin_nota else " Están todas."
            flash(
                f"Se guardó el borrador del corte {corte.numero}: {con_nota} nota(s)."
                + detalle,
                "exito",
            )
            return redirect(
                url_for(
                    "registro_asistencia_notas.notas",
                    curso_id=curso_actual.id,
                    numero=corte.numero,
                )
            )
    estado, bloqueo = registro_academico.estado_de_notas(curso_actual, corte)
    return render_template(
        "registro/notas.html",
        curso=curso_actual,
        corte=corte,
        estado=estado,
        nombre_estado=registro_academico.NOMBRES_ESTADO[estado],
        bloqueo=bloqueo,
        filas=filas,
        valores=valores,
        errores=errores,
        formulario=formulario,
        error=error,
        cortes=registro_academico.cortes_del_periodo(curso_actual.periodo_academico),
    )
