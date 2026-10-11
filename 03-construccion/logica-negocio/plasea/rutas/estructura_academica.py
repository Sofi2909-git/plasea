"""Blueprint de la épica E2: Estructura académica (RF-13 a RF-20).

Todas las pantallas son del Auditor académico. Las rutas leen la petición,
llaman a un servicio y deciden qué mostrar; las reglas viven en ``servicios``.
"""

from __future__ import annotations

from typing import Any, Optional

import click
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
from sqlalchemy import select

from plasea.autorizacion import destino_seguro, rol_requerido
from plasea.formularios.estructura_academica import (
    FormularioAsignatura,
    FormularioBloque,
    FormularioCortes,
    FormularioCurso,
    FormularioEditarCurso,
    FormularioFestivo,
    FormularioPeriodo,
    FormularioUmbrales,
)
from plasea.formularios.estudiantes_inscripciones import FormularioInscripcion
from plasea.modelos import Curso, PeriodoAcademico, db
from plasea.servicios import (
    asignaturas,
    calendario,
    cursos,
    inscripciones,
    periodos,
    umbrales,
)
from plasea.servicios.comunes import ErrorNegocio
from plasea.servicios.cuentas import ROL_AUDITOR

blueprint = Blueprint("estructura_academica", __name__, cli_group=None)


def _volver(predeterminado: str) -> str:
    """Destino interno tras una acción POST (conserva filtros si vienen)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-13
    return destino_seguro(request.form.get("volver")) or predeterminado


def _avisar_regeneracion(resultado: tuple[int, int]) -> None:
    """Informa calendarios regenerados y omitidos (RF-18, RF-19)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-18
    regenerados, omitidos = resultado
    mensaje = f"Se regeneró el calendario de {regenerados} curso(s)."
    if omitidos:
        mensaje += (
            f" {omitidos} curso(s) ya tienen asistencia registrada y conservaron "
            "su calendario."
        )
    flash(mensaje, "aviso" if omitidos else "info")


# ---------------------------------------------------------------------------
# Panel de la estructura académica
# ---------------------------------------------------------------------------


@blueprint.get("/")
@rol_requerido(ROL_AUDITOR)
def panel() -> Any:
    """Resumen de la estructura académica con accesos a cada sección."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-13 / RF-16
    en_curso = periodos.periodo_en_curso()
    return render_template(
        "estructura/panel.html",
        en_curso=en_curso,
        cursos_en_curso=(
            cursos.listar_cursos(periodo_id=en_curso.id) if en_curso else []
        ),
        umbral=umbrales.configuracion_vigente(),
    )


# ---------------------------------------------------------------------------
# RF-16, RF-17 y RF-18: períodos, cortes y festivos
# ---------------------------------------------------------------------------


@blueprint.get("/periodos")
@rol_requerido(ROL_AUDITOR)
def panel_periodos() -> Any:
    """Listado de períodos académicos (RF-16)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-16
    return render_template(
        "estructura/periodos_lista.html", periodos=periodos.listar_periodos()
    )


@blueprint.route("/periodos/nuevo", methods=["GET", "POST"])
@rol_requerido(ROL_AUDITOR)
def panel_periodo_nuevo() -> Any:
    """Registro de un período académico (RF-16)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-16
    formulario = FormularioPeriodo()
    error = None
    if formulario.validate_on_submit():
        try:
            periodo = periodos.crear_periodo(
                periodos.DatosPeriodo(
                    formulario.identificador.data or "",
                    formulario.fecha_inicio.data,
                    formulario.fecha_fin.data,
                ),
                g.usuario.id,
            )
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            flash(
                f"Se registró el período {periodo.identificador}. "
                "Ahora defina sus cortes.",
                "exito",
            )
            return redirect(
                url_for(
                    "estructura_academica.panel_periodo_cortes", periodo_id=periodo.id
                )
            )
    return render_template(
        "estructura/periodo_formulario.html",
        formulario=formulario,
        titulo="Nuevo período",
        error=error,
        periodo=None,
    )


@blueprint.get("/periodos/<int:periodo_id>")
@rol_requerido(ROL_AUDITOR)
def panel_periodo(periodo_id: int) -> Any:
    """Detalle del período: cortes, festivos y cursos (RF-16, RF-17, RF-18)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-16
    periodo = _periodo_o_404(periodo_id)
    return render_template(
        "estructura/periodo_detalle.html",
        periodo=periodo,
        formulario_festivo=FormularioFestivo(),
        semanas=periodos.semanas_calendario(periodo.fecha_inicio, periodo.fecha_fin),
        total_cursos=len(cursos.listar_cursos(periodo_id=periodo.id)),
    )


@blueprint.route("/periodos/<int:periodo_id>/editar", methods=["GET", "POST"])
@rol_requerido(ROL_AUDITOR)
def panel_periodo_editar(periodo_id: int) -> Any:
    """Modificación del identificador y las fechas de un período (RF-16)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-16
    periodo = _periodo_o_404(periodo_id)
    formulario = FormularioPeriodo(obj=periodo)
    error = None
    if formulario.validate_on_submit():
        try:
            periodo, regenerados = periodos.modificar_periodo(
                periodo.id,
                periodos.DatosPeriodo(
                    formulario.identificador.data or "",
                    formulario.fecha_inicio.data,
                    formulario.fecha_fin.data,
                ),
                g.usuario.id,
            )
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            mensaje = f"Se guardaron los cambios del período {periodo.identificador}."
            if regenerados:
                mensaje += f" Se regeneró el calendario de {regenerados} curso(s)."
            flash(mensaje, "exito")
            return redirect(
                url_for("estructura_academica.panel_periodo", periodo_id=periodo.id)
            )
    return render_template(
        "estructura/periodo_formulario.html",
        formulario=formulario,
        titulo=f"Editar período {periodo.identificador}",
        error=error,
        periodo=periodo,
    )


@blueprint.post("/periodos/<int:periodo_id>/en-curso")
@rol_requerido(ROL_AUDITOR)
def panel_periodo_en_curso(periodo_id: int) -> Any:
    """Marca el período como en curso (RF-16)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-16
    try:
        periodo = periodos.marcar_en_curso(periodo_id, g.usuario.id)
    except ErrorNegocio as fallo:
        flash(fallo.mensaje, "error")
    else:
        flash(f"El período {periodo.identificador} quedó en curso.", "exito")
    return redirect(_volver(url_for("estructura_academica.panel_periodos")))


@blueprint.route("/periodos/<int:periodo_id>/cortes", methods=["GET", "POST"])
@rol_requerido(ROL_AUDITOR)
def panel_periodo_cortes(periodo_id: int) -> Any:
    """Definición de los 3 cortes del período (RF-17)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-17
    periodo = _periodo_o_404(periodo_id)
    formulario = FormularioCortes()
    if request.method == "GET":
        base = (
            [
                periodos.DatosCorte(
                    c.numero,
                    c.peso_porcentaje,
                    c.fecha_inicio,
                    c.fecha_fin,
                    c.limite_carga,
                    c.limite_correccion,
                )
                for c in periodo.cortes
            ]
            if len(periodo.cortes) == periodos.NUMERO_CORTES
            else periodos.cortes_sugeridos(periodo)
        )
        for entrada, datos in zip(formulario.cortes.entries, base):
            entrada.form.process(data=datos.__dict__)
    error = None
    if formulario.validate_on_submit():
        datos = [
            periodos.DatosCorte(
                numero=numero,
                peso_porcentaje=entrada.form.peso_porcentaje.data,
                fecha_inicio=entrada.form.fecha_inicio.data,
                fecha_fin=entrada.form.fecha_fin.data,
                limite_carga=entrada.form.limite_carga.data,
                limite_correccion=entrada.form.limite_correccion.data,
            )
            for numero, entrada in enumerate(formulario.cortes.entries, start=1)
        ]
        try:
            periodos.guardar_cortes(periodo.id, datos, g.usuario.id)
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            flash("Se guardaron los cortes del período.", "exito")
            return redirect(
                url_for("estructura_academica.panel_periodo", periodo_id=periodo.id)
            )
    cerrados = {c.numero for c in periodo.cortes if c.cerrado_en is not None}
    return render_template(
        "estructura/cortes_formulario.html",
        periodo=periodo,
        formulario=formulario,
        error=error,
        cerrados=cerrados,
        sugeridos=len(periodo.cortes) != periodos.NUMERO_CORTES,
    )


@blueprint.post("/periodos/<int:periodo_id>/festivos")
@rol_requerido(ROL_AUDITOR)
def panel_periodo_festivo_nuevo(periodo_id: int) -> Any:
    """Registro de un festivo del período (RF-18)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-18
    formulario = FormularioFestivo()
    if not formulario.validate_on_submit():
        flash("Escriba una fecha válida para el festivo.", "error")
    else:
        try:
            resultado = periodos.agregar_festivo(
                periodo_id, formulario.fecha.data, g.usuario.id
            )
        except ErrorNegocio as fallo:
            flash(fallo.mensaje, "error")
        else:
            flash(f"Se registró el festivo {formulario.fecha.data:%d/%m/%Y}.", "exito")
            _avisar_regeneracion(resultado)
    return redirect(
        url_for("estructura_academica.panel_periodo", periodo_id=periodo_id)
    )


@blueprint.post("/festivos/<int:festivo_id>/eliminar")
@rol_requerido(ROL_AUDITOR)
def panel_festivo_eliminar(festivo_id: int) -> Any:
    """Retiro de un festivo (RF-18)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-18
    try:
        resultado = periodos.eliminar_festivo(festivo_id, g.usuario.id)
    except ErrorNegocio as fallo:
        flash(fallo.mensaje, "error")
    else:
        flash("Se retiró el festivo.", "exito")
        _avisar_regeneracion(resultado)
    return redirect(_volver(url_for("estructura_academica.panel_periodos")))


def _periodo_o_404(periodo_id: int) -> PeriodoAcademico:
    """Devuelve el período o responde 404."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-16
    try:
        return periodos.obtener_periodo(periodo_id)
    except ErrorNegocio:
        abort(404)


# ---------------------------------------------------------------------------
# RF-13: asignaturas
# ---------------------------------------------------------------------------


def _datos_asignatura(formulario: FormularioAsignatura) -> asignaturas.DatosAsignatura:
    """Convierte el formulario en los datos del servicio."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-13
    return asignaturas.DatosAsignatura(
        codigo=formulario.codigo.data or "",
        nombre=formulario.nombre.data or "",
        programa_academico_id=formulario.programa_academico_id.data,
        creditos=formulario.creditos.data,
        horas_semanales=formulario.horas_semanales.data,
        nivel=formulario.nivel.data,
    )


def _opciones_programa(formulario: FormularioAsignatura) -> None:
    """Carga las opciones de programa académico."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-13
    formulario.programa_academico_id.choices = [
        (p.id, p.nombre) for p in asignaturas.listar_programas()
    ]


@blueprint.get("/asignaturas")
@rol_requerido(ROL_AUDITOR)
def panel_asignaturas() -> Any:
    """Listado de asignaturas con búsqueda y filtro por nivel (RF-13)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-13
    filtros = {
        "q": request.args.get("q", "").strip(),
        "nivel": request.args.get("nivel", ""),
    }
    paginacion = asignaturas.listar_asignaturas(
        texto=filtros["q"] or None,
        nivel=request.args.get("nivel", type=int),
        pagina=request.args.get("pagina", 1, type=int),
    )
    return render_template(
        "estructura/asignaturas_lista.html", paginacion=paginacion, filtros=filtros
    )


@blueprint.route("/asignaturas/nueva", methods=["GET", "POST"])
@rol_requerido(ROL_AUDITOR)
def panel_asignatura_nueva() -> Any:
    """Registro de una asignatura (RF-13)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-13
    formulario = FormularioAsignatura()
    _opciones_programa(formulario)
    error = None
    if formulario.validate_on_submit():
        try:
            asignatura = asignaturas.crear_asignatura(
                _datos_asignatura(formulario), g.usuario.id
            )
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            flash(f"Se registró la asignatura {asignatura.codigo}.", "exito")
            return redirect(url_for("estructura_academica.panel_asignaturas"))
    return render_template(
        "estructura/asignatura_formulario.html",
        formulario=formulario,
        titulo="Nueva asignatura",
        error=error,
        asignatura=None,
        total_cursos=0,
    )


@blueprint.route("/asignaturas/<int:asignatura_id>/editar", methods=["GET", "POST"])
@rol_requerido(ROL_AUDITOR)
def panel_asignatura_editar(asignatura_id: int) -> Any:
    """Modificación de una asignatura (RF-13)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-13
    try:
        asignatura = asignaturas.obtener_asignatura(asignatura_id)
    except ErrorNegocio:
        abort(404)
    formulario = FormularioAsignatura(obj=asignatura)
    _opciones_programa(formulario)
    error = None
    if formulario.validate_on_submit():
        try:
            asignatura = asignaturas.modificar_asignatura(
                asignatura.id, _datos_asignatura(formulario), g.usuario.id
            )
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            flash(f"Se guardaron los cambios de {asignatura.codigo}.", "exito")
            return redirect(url_for("estructura_academica.panel_asignaturas"))
    return render_template(
        "estructura/asignatura_formulario.html",
        formulario=formulario,
        titulo=f"Editar asignatura {asignatura.codigo}",
        error=error,
        asignatura=asignatura,
        total_cursos=asignaturas.contar_cursos(asignatura.id),
    )


@blueprint.post("/asignaturas/<int:asignatura_id>/eliminar")
@rol_requerido(ROL_AUDITOR)
def panel_asignatura_eliminar(asignatura_id: int) -> Any:
    """Eliminación de una asignatura sin cursos (RF-13)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-13
    try:
        codigo = asignaturas.eliminar_asignatura(asignatura_id, g.usuario.id)
    except ErrorNegocio as fallo:
        flash(fallo.mensaje, "error")
    else:
        flash(f"Se eliminó la asignatura {codigo}.", "exito")
    return redirect(url_for("estructura_academica.panel_asignaturas"))


# ---------------------------------------------------------------------------
# RF-14, RF-15 y RF-19: cursos, horario y calendario
# ---------------------------------------------------------------------------


def _opciones_docente(campo: Any) -> None:
    """Carga los docentes asignables en un selector."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-14
    campo.choices = [(0, "Seleccione un docente")] + [
        (p.id, f"{p.nombre_completo} ({p.correo})")
        for p in cursos.profesores_asignables()
    ]


@blueprint.get("/cursos")
@rol_requerido(ROL_AUDITOR)
def panel_cursos() -> Any:
    """Listado de cursos por período, asignatura y docente (RF-14)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-14
    lista_periodos = periodos.listar_periodos()
    en_curso = periodos.periodo_en_curso()
    periodo_id: Optional[int] = request.args.get("periodo", type=int)
    if periodo_id is None and "periodo" not in request.args and en_curso:
        periodo_id = en_curso.id
    asignatura_id = request.args.get("asignatura", type=int)
    profesor_id = request.args.get("profesor", type=int)
    return render_template(
        "estructura/cursos_lista.html",
        filas=cursos.listar_cursos(periodo_id, asignatura_id, profesor_id),
        periodos=lista_periodos,
        asignaturas=asignaturas.todas_las_asignaturas(),
        profesores=cursos.profesores_asignables(),
        dias=cursos.DIAS_SEMANA,
        filtros={
            "periodo": periodo_id,
            "asignatura": asignatura_id,
            "profesor": profesor_id,
        },
    )


@blueprint.route("/cursos/nuevo", methods=["GET", "POST"])
@rol_requerido(ROL_AUDITOR)
def panel_curso_nuevo() -> Any:
    """Registro de un curso con su docente (RF-14)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-14
    formulario = FormularioCurso()
    formulario.periodo_academico_id.choices = [(0, "Seleccione un período")] + [
        (p.id, p.identificador + (" (en curso)" if p.en_curso_marca else ""))
        for p in periodos.listar_periodos()
    ]
    formulario.asignatura_id.choices = [(0, "Seleccione una asignatura")] + [
        (a.id, f"{a.codigo} · {a.nombre}") for a in asignaturas.todas_las_asignaturas()
    ]
    _opciones_docente(formulario.profesor_usuario_id)
    if request.method == "GET":
        en_curso = periodos.periodo_en_curso()
        formulario.periodo_academico_id.data = request.args.get(
            "periodo", type=int
        ) or (en_curso.id if en_curso else 0)
        formulario.asignatura_id.data = request.args.get("asignatura", 0, type=int)
    error = None
    if formulario.validate_on_submit():
        try:
            curso = cursos.crear_curso(
                cursos.DatosCurso(
                    asignatura_id=formulario.asignatura_id.data,
                    periodo_academico_id=formulario.periodo_academico_id.data,
                    codigo=formulario.codigo.data or "",
                    profesor_usuario_id=formulario.profesor_usuario_id.data,
                ),
                g.usuario.id,
            )
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            flash("Se registró el curso. Ahora defina su horario semanal.", "exito")
            return redirect(
                url_for("estructura_academica.panel_curso", curso_id=curso.id)
            )
    return render_template(
        "estructura/curso_formulario.html",
        formulario=formulario,
        titulo="Nuevo curso",
        error=error,
        curso=None,
    )


@blueprint.get("/cursos/<int:curso_id>")
@rol_requerido(ROL_AUDITOR)
def panel_curso(curso_id: int) -> Any:
    """Detalle del curso: horario, calendario e inscritos (RF-14, 15, 19, 23)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-15 / RF-19
    curso = _curso_o_404(curso_id)
    formulario_bloque = FormularioBloque()
    formulario_bloque.dia_semana.choices = list(cursos.DIAS_SEMANA.items())
    total_sesiones, total_horas = calendario.resumen_calendario(curso.id)
    return render_template(
        "estructura/curso_detalle.html",
        curso=curso,
        dias=cursos.DIAS_SEMANA,
        formulario_bloque=formulario_bloque,
        formulario_inscripcion=FormularioInscripcion(),
        advertencia=cursos.advertencia_horas(curso),
        horas_programadas=cursos.horas_semanales_programadas(curso),
        tiene_asistencia=calendario.curso_tiene_asistencia(curso.id),
        total_sesiones=total_sesiones,
        total_horas=total_horas,
        sesiones=calendario.sesiones_del_curso(curso.id),
        inscritos=inscripciones.inscritos_del_curso(curso.id),
    )


@blueprint.route("/cursos/<int:curso_id>/editar", methods=["GET", "POST"])
@rol_requerido(ROL_AUDITOR)
def panel_curso_editar(curso_id: int) -> Any:
    """Modificación del código y el docente de un curso (RF-14)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-14
    curso = _curso_o_404(curso_id)
    formulario = FormularioEditarCurso(obj=curso)
    _opciones_docente(formulario.profesor_usuario_id)
    error = None
    if formulario.validate_on_submit():
        try:
            cursos.modificar_curso(
                curso.id,
                formulario.codigo.data or "",
                formulario.profesor_usuario_id.data,
                g.usuario.id,
            )
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            flash("Se guardaron los cambios del curso.", "exito")
            return redirect(
                url_for("estructura_academica.panel_curso", curso_id=curso.id)
            )
    return render_template(
        "estructura/curso_formulario.html",
        formulario=formulario,
        titulo="Editar curso",
        error=error,
        curso=curso,
    )


@blueprint.post("/cursos/<int:curso_id>/bloques")
@rol_requerido(ROL_AUDITOR)
def panel_curso_bloque_nuevo(curso_id: int) -> Any:
    """Agrega un bloque al horario semanal del curso (RF-15)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-15
    formulario = FormularioBloque()
    formulario.dia_semana.choices = list(cursos.DIAS_SEMANA.items())
    if not formulario.validate_on_submit():
        flash("Revise el día y las horas del bloque.", "error")
    else:
        try:
            curso = cursos.agregar_bloque(
                curso_id,
                formulario.dia_semana.data,
                formulario.hora_inicio.data,
                formulario.hora_fin.data,
                g.usuario.id,
            )
        except ErrorNegocio as fallo:
            flash(fallo.mensaje, "error")
        else:
            flash("Se agregó el bloque y se regeneró el calendario del curso.", "exito")
            advertencia = cursos.advertencia_horas(curso)
            if advertencia:
                flash(advertencia, "aviso")
    return redirect(url_for("estructura_academica.panel_curso", curso_id=curso_id))


@blueprint.post("/bloques/<int:bloque_id>/eliminar")
@rol_requerido(ROL_AUDITOR)
def panel_bloque_eliminar(bloque_id: int) -> Any:
    """Quita un bloque del horario semanal (RF-15)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-15
    try:
        curso = cursos.eliminar_bloque(bloque_id, g.usuario.id)
    except ErrorNegocio as fallo:
        flash(fallo.mensaje, "error")
        return redirect(_volver(url_for("estructura_academica.panel_cursos")))
    flash("Se retiró el bloque y se regeneró el calendario del curso.", "exito")
    advertencia = cursos.advertencia_horas(curso)
    if advertencia:
        flash(advertencia, "aviso")
    return redirect(url_for("estructura_academica.panel_curso", curso_id=curso.id))


@blueprint.post("/cursos/<int:curso_id>/calendario")
@rol_requerido(ROL_AUDITOR)
def panel_curso_calendario(curso_id: int) -> Any:
    """Genera o regenera el calendario del curso a petición (RF-19)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-19
    try:
        total_sesiones, total_horas = cursos.generar_calendario(curso_id)
    except ErrorNegocio as fallo:
        flash(fallo.mensaje, "error")
    else:
        flash(
            f"Calendario generado: {total_sesiones} sesiones, {total_horas} horas.",
            "exito",
        )
    return redirect(url_for("estructura_academica.panel_curso", curso_id=curso_id))


def _curso_o_404(curso_id: int) -> Curso:
    """Devuelve el curso o responde 404."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-14
    try:
        return cursos.obtener_curso(curso_id)
    except ErrorNegocio:
        abort(404)


# ---------------------------------------------------------------------------
# RF-20: umbrales de alerta
# ---------------------------------------------------------------------------


@blueprint.route("/umbrales", methods=["GET", "POST"])
@rol_requerido(ROL_AUDITOR)
def panel_umbrales() -> Any:
    """Consulta y cambio de los umbrales de alerta con histórico (RF-20)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-20
    vigente = umbrales.configuracion_vigente()
    formulario = FormularioUmbrales(obj=vigente)
    error = None
    if formulario.validate_on_submit():
        try:
            umbrales.guardar_umbrales(
                umbrales.DatosUmbrales(
                    formulario.nota_aprobacion.data,
                    formulario.limite_perdida_inasistencia.data,
                    formulario.umbral_amarillo_inasistencia.data,
                    formulario.nota_amarilla_minima.data,
                    formulario.nota_amarilla_maxima.data,
                ),
                g.usuario.id,
            )
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            flash(
                "Se guardó la nueva versión de los umbrales. Las alertas de cortes "
                "ya cerrados no se recalculan.",
                "exito",
            )
            return redirect(url_for("estructura_academica.panel_umbrales"))
    return render_template(
        "estructura/umbrales.html",
        formulario=formulario,
        vigente=vigente,
        historial=umbrales.historial_configuraciones(),
        error=error,
    )


# ---------------------------------------------------------------------------
# RF-19: comando de consola
# ---------------------------------------------------------------------------


@blueprint.cli.command("generar-calendarios")
@click.option("--periodo", "identificador", default=None, help="Ej.: 2026-2")
def comando_generar_calendarios(identificador: Optional[str]) -> None:
    """Genera el calendario de los cursos sin asistencia (todos o de un período)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-19
    consulta = select(PeriodoAcademico)
    if identificador:
        consulta = consulta.where(PeriodoAcademico.identificador == identificador)
    lista = db.session.scalars(consulta).all()
    if not lista:
        raise click.ClickException("No hay períodos que coincidan.")
    for periodo in lista:
        try:
            regenerados, omitidos = calendario.regenerar_calendarios_periodo(periodo.id)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        click.echo(
            f"{periodo.identificador}: {regenerados} curso(s) regenerados, "
            f"{omitidos} omitidos por tener asistencia."
        )
