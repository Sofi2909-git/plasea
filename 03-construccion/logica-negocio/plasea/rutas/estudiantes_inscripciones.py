"""Blueprint de la épica E3: Estudiantes e inscripciones (RF-21 a RF-25).

- RF-21 a RF-24: pantallas del Auditor académico (estudiantes, estados,
  inscripciones y carga por CSV).
- RF-25: comando ``flask generar-datos-prueba`` que ejecuta el Administrador del
  sistema en el servidor.
"""

from __future__ import annotations

from typing import Any

import click
from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.exceptions import RequestEntityTooLarge

from plasea.autorizacion import destino_seguro, rol_requerido
from plasea.formularios.estudiantes_inscripciones import (
    FormularioConfirmacion,
    FormularioEstado,
    FormularioEstudiante,
    FormularioImportacion,
    FormularioInscripcion,
)
from plasea.servicios import (
    asignaturas,
    datos_prueba,
    estudiantes,
    importacion_csv,
    inscripciones,
)
from plasea.servicios.comunes import ErrorNegocio
from plasea.servicios.cuentas import ROL_AUDITOR

blueprint = Blueprint("estudiantes_inscripciones", __name__, cli_group=None)
CLAVE_IMPORTACION = "importacion_csv_pendiente"


def _datos_estudiante(formulario: FormularioEstudiante) -> estudiantes.DatosEstudiante:
    """Convierte el formulario en los datos del servicio."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-21
    return estudiantes.DatosEstudiante(
        codigo=formulario.codigo.data or "",
        nombres=formulario.nombres.data or "",
        correo=formulario.correo.data or "",
        programa_academico_id=formulario.programa_academico_id.data,
        periodo_ingreso=formulario.periodo_ingreso.data or "",
    )


def _preparar_formulario(formulario: FormularioEstudiante) -> None:
    """Carga las opciones de programa académico."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-21
    formulario.programa_academico_id.choices = [
        (p.id, p.nombre) for p in asignaturas.listar_programas()
    ]


# ---------------------------------------------------------------------------
# RF-21: estudiantes
# ---------------------------------------------------------------------------


@blueprint.get("/")
@rol_requerido(ROL_AUDITOR)
def lista() -> Any:
    """Listado de estudiantes con búsqueda, cohorte y estado vigente (RF-21, RF-22)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-21
    filtros = {
        "q": request.args.get("q", "").strip(),
        "cohorte": request.args.get("cohorte", ""),
        "estado": request.args.get("estado", ""),
    }
    paginacion = estudiantes.listar_estudiantes(
        texto=filtros["q"] or None,
        cohorte=filtros["cohorte"] or None,
        estado=filtros["estado"] or None,
        pagina=request.args.get("pagina", 1, type=int),
    )
    return render_template(
        "estudiantes/lista.html",
        paginacion=paginacion,
        filtros=filtros,
        cohortes=estudiantes.listar_cohortes(),
        estados=estudiantes.listar_estados(),
    )


@blueprint.route("/nuevo", methods=["GET", "POST"])
@rol_requerido(ROL_AUDITOR)
def lista_nuevo() -> Any:
    """Registro de un estudiante con estado inicial activo (RF-21)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-21
    formulario = FormularioEstudiante()
    _preparar_formulario(formulario)
    if request.method == "GET":
        formulario.fecha_estado_inicial.data = estudiantes.hoy()
    error = None
    if formulario.validate_on_submit():
        try:
            estudiante = estudiantes.crear_estudiante(
                _datos_estudiante(formulario),
                formulario.fecha_estado_inicial.data,
                g.usuario.id,
            )
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            flash(f"Se registró a {estudiante.nombres}.", "exito")
            return redirect(
                url_for(
                    "estudiantes_inscripciones.lista_detalle",
                    estudiante_id=estudiante.id,
                )
            )
    return render_template(
        "estudiantes/formulario.html",
        formulario=formulario,
        titulo="Nuevo estudiante",
        error=error,
        estudiante=None,
    )


@blueprint.get("/<int:estudiante_id>")
@rol_requerido(ROL_AUDITOR)
def lista_detalle(estudiante_id: int) -> Any:
    """Ficha del estudiante: datos, estados e inscripciones (RF-21 a RF-23)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-22
    estudiante = _estudiante_o_404(estudiante_id)
    formulario_estado = FormularioEstado()
    formulario_estado.estado.choices = [
        (e.codigo, e.nombre) for e in estudiantes.listar_estados()
    ]
    formulario_estado.fecha_efectiva.data = estudiantes.hoy()
    return render_template(
        "estudiantes/detalle.html",
        estudiante=estudiante,
        vigente=estudiantes.estado_en_fecha(estudiante.id, estudiantes.hoy()),
        historial=estudiantes.historial_estados(estudiante.id),
        inscripciones=inscripciones.inscripciones_del_estudiante(estudiante.id),
        formulario_estado=formulario_estado,
    )


@blueprint.route("/<int:estudiante_id>/editar", methods=["GET", "POST"])
@rol_requerido(ROL_AUDITOR)
def lista_editar(estudiante_id: int) -> Any:
    """Modificación de los datos de un estudiante (RF-21)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-21
    estudiante = _estudiante_o_404(estudiante_id)
    formulario = FormularioEstudiante(obj=estudiante)
    _preparar_formulario(formulario)
    # El estado inicial solo se define al registrar; aquí no se edita.
    del formulario.fecha_estado_inicial
    error = None
    if formulario.validate_on_submit():
        try:
            estudiantes.modificar_estudiante(
                estudiante.id, _datos_estudiante(formulario), g.usuario.id
            )
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            flash("Se guardaron los cambios del estudiante.", "exito")
            return redirect(
                url_for(
                    "estudiantes_inscripciones.lista_detalle",
                    estudiante_id=estudiante.id,
                )
            )
    return render_template(
        "estudiantes/formulario.html",
        formulario=formulario,
        titulo=f"Editar estudiante {estudiante.codigo}",
        error=error,
        estudiante=estudiante,
    )


@blueprint.post("/<int:estudiante_id>/estados")
@rol_requerido(ROL_AUDITOR)
def lista_estado_nuevo(estudiante_id: int) -> Any:
    """Registro de un estado con fecha efectiva (RF-22)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-22
    formulario = FormularioEstado()
    formulario.estado.choices = [
        (e.codigo, e.nombre) for e in estudiantes.listar_estados()
    ]
    if not formulario.validate_on_submit():
        flash("Seleccione el estado y escriba una fecha efectiva válida.", "error")
    else:
        try:
            registro = estudiantes.registrar_estado(
                estudiante_id,
                formulario.estado.data,
                formulario.fecha_efectiva.data,
                g.usuario.id,
            )
        except ErrorNegocio as fallo:
            flash(fallo.mensaje, "error")
        else:
            flash(
                f"Se registró el estado «{registro.estado_estudiante.nombre}» desde el "
                f"{registro.fecha_efectiva:%d/%m/%Y}.",
                "exito",
            )
    return redirect(
        url_for("estudiantes_inscripciones.lista_detalle", estudiante_id=estudiante_id)
    )


def _estudiante_o_404(estudiante_id: int) -> Any:
    """Devuelve el estudiante o responde 404."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-21
    try:
        return estudiantes.obtener_estudiante(estudiante_id)
    except ErrorNegocio:
        abort(404)


# ---------------------------------------------------------------------------
# RF-23: inscripciones
# ---------------------------------------------------------------------------


@blueprint.post("/cursos/<int:curso_id>/inscripciones")
@rol_requerido(ROL_AUDITOR)
def lista_inscribir(curso_id: int) -> Any:
    """Inscribe a un estudiante en un curso con el semestre que cursa (RF-23)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-23
    formulario = FormularioInscripcion()
    if not formulario.validate_on_submit():
        flash("Escriba el código del estudiante y un semestre entre 1 y 10.", "error")
    else:
        try:
            inscripciones.inscribir(
                curso_id,
                formulario.codigo_estudiante.data,
                formulario.semestre_cursado.data,
                g.usuario.id,
            )
        except ErrorNegocio as fallo:
            flash(fallo.mensaje, "error")
        else:
            flash("Se inscribió al estudiante en el curso.", "exito")
    return redirect(
        url_for("estructura_academica.panel_curso", curso_id=curso_id) + "#inscritos"
    )


@blueprint.post("/inscripciones/<int:inscripcion_id>/retirar")
@rol_requerido(ROL_AUDITOR)
def lista_retirar(inscripcion_id: int) -> Any:
    """Retira al estudiante de un curso conservando la inscripción (RF-23)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-23
    try:
        inscripcion = inscripciones.retirar(inscripcion_id, g.usuario.id)
    except ErrorNegocio as fallo:
        flash(fallo.mensaje, "error")
        destino = url_for("estudiantes_inscripciones.lista")
    else:
        flash("Se registró el retiro del curso. La inscripción se conserva.", "exito")
        destino = (
            url_for("estructura_academica.panel_curso", curso_id=inscripcion.curso_id)
            + "#inscritos"
        )
    return redirect(destino_seguro(request.form.get("volver")) or destino)


# ---------------------------------------------------------------------------
# RF-24: carga de estudiantes e inscripciones desde CSV
# ---------------------------------------------------------------------------


@blueprint.route("/importar", methods=["GET", "POST"])
@rol_requerido(ROL_AUDITOR)
def importar() -> Any:
    """Paso 1: subir y validar el CSV; muestra el resumen sin guardar (RF-24)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    formulario = FormularioImportacion()
    resumen = None
    error = None
    if formulario.validate_on_submit():
        contenido = formulario.archivo.data.read(
            importacion_csv.TAMANO_MAXIMO_BYTES + 1
        )
        try:
            resumen = importacion_csv.analizar(contenido)
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            importacion_csv.eliminar_temporal(session.get(CLAVE_IMPORTACION))
            session[CLAVE_IMPORTACION] = importacion_csv.guardar_temporal(contenido)
    elif request.method == "GET":
        importacion_csv.eliminar_temporal(session.pop(CLAVE_IMPORTACION, None))
    return render_template(
        "estudiantes/importar.html",
        formulario=formulario,
        confirmacion=FormularioConfirmacion(),
        resumen=resumen,
        nombre_archivo=formulario.archivo.data.filename if resumen else None,
        error=error,
        tamano_maximo_mb=importacion_csv.TAMANO_MAXIMO_BYTES // (1024 * 1024),
    )


@blueprint.post("/importar/confirmar")
@rol_requerido(ROL_AUDITOR)
def importar_confirmar() -> Any:
    """Paso 2: guarda las filas válidas de la carga ya validada (RF-24)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    formulario = FormularioConfirmacion()
    token = session.get(CLAVE_IMPORTACION)
    if not formulario.validate_on_submit():
        abort(400)
    try:
        resumen = importacion_csv.aplicar(
            importacion_csv.leer_temporal(token), g.usuario.id
        )
    except ErrorNegocio as fallo:
        flash(fallo.mensaje, "error")
        return redirect(url_for("estudiantes_inscripciones.importar"))
    importacion_csv.eliminar_temporal(session.pop(CLAVE_IMPORTACION, None))
    omitidas = len(resumen.con_error)
    flash(
        f"Carga guardada: {resumen.nuevos} estudiante(s) nuevo(s), "
        f"{resumen.actualizados} actualizado(s) y {resumen.inscripciones} "
        f"inscripción(es)."
        + (f" Se omitieron {omitidas} fila(s) con error." if omitidas else ""),
        "exito",
    )
    return redirect(url_for("estudiantes_inscripciones.lista"))


@blueprint.post("/importar/cancelar")
@rol_requerido(ROL_AUDITOR)
def importar_cancelar() -> Any:
    """Descarta la carga validada sin guardar nada (RF-24)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    if not FormularioConfirmacion().validate_on_submit():
        abort(400)
    importacion_csv.eliminar_temporal(session.pop(CLAVE_IMPORTACION, None))
    flash("Se canceló la carga. No se guardó ningún registro.", "info")
    return redirect(url_for("estudiantes_inscripciones.importar"))


@blueprint.get("/importar/plantilla.csv")
@rol_requerido(ROL_AUDITOR)
def importar_plantilla() -> Any:
    """Plantilla descargable del CSV (RF-24)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    return Response(
        importacion_csv.generar_plantilla(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=plantilla_estudiantes.csv"
        },
    )


@blueprint.errorhandler(RequestEntityTooLarge)
def archivo_demasiado_grande(_error: Any) -> Any:
    """Respuesta comprensible cuando el archivo supera los 5 MB (RF-24)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-24
    flash("El archivo supera el tamaño máximo de 5 MB.", "error")
    return redirect(url_for("estudiantes_inscripciones.importar"))


# ---------------------------------------------------------------------------
# RF-25: generador de datos de prueba (comando del Administrador del sistema)
# ---------------------------------------------------------------------------


@blueprint.cli.command("generar-datos-prueba")
@click.option(
    "--administrador",
    default="admin@plasea.edu.co",
    show_default=True,
    help="Correo de la cuenta de Administrador del sistema que ejecuta el proceso.",
)
@click.option(
    "--reiniciar",
    is_flag=True,
    help="Borra los datos académicos antes de generar (solo datos de prueba).",
)
@click.option("--semilla", default=2026, show_default=True, help="Semilla aleatoria.")
@click.option(
    "--buzones",
    default="",
    help="Correos reales del equipo, separados por coma, para los primeros profesores.",
)
def comando_generar_datos_prueba(
    administrador: str, reiniciar: bool, semilla: int, buzones: str
) -> None:
    """Genera 4 semestres de datos ficticios coherentes (RF-25)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-25
    if reiniciar:
        click.confirm(
            "Se borrarán TODOS los datos académicos (períodos, cursos, estudiantes, "
            "asistencia y notas). Las cuentas de usuario se conservan. ¿Continuar?",
            abort=True,
        )
    try:
        resumen = datos_prueba.generar(
            correo_administrador=administrador,
            reiniciar=reiniciar,
            semilla=semilla,
            buzones=[b.strip() for b in buzones.split(",") if b.strip()],
            avisar=click.echo,
        )
    except ErrorNegocio as fallo:
        raise click.ClickException(fallo.mensaje) from fallo
    for entidad, cantidad in resumen.items():
        click.echo(f"{entidad}: {cantidad}")
    click.echo("Datos de prueba generados.")
