"""Blueprint de la épica E1: Acceso y cuentas (RF-01 a RF-12).

Las rutas son delgadas: leen la petición, llaman a un servicio y deciden qué
mostrar. Las reglas viven en ``plasea.servicios``.
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
    session,
    url_for,
)

from plasea.autorizacion import (
    CLAVE_SESION,
    destino_seguro,
    login_requerido,
    rol_requerido,
)
from plasea.formularios.acceso_cuentas import (
    FormularioCuenta,
    FormularioInicioSesion,
    FormularioNuevaContrasena,
    FormularioSolicitudRestablecimiento,
)
from plasea.servicios import cuentas, enlaces_cuenta, sesiones
from plasea.servicios.comunes import ErrorNegocio, ahora
from plasea.servicios.contrasenas import MENSAJE_POLITICA

blueprint = Blueprint("acceso_cuentas", __name__)

MENSAJE_SOLICITUD_ENVIADA = (
    "Si el correo corresponde a una cuenta activa, en unos minutos recibirá un "
    "enlace para restablecer la contraseña. Revise también la carpeta de spam."
)


# ---------------------------------------------------------------------------
# Inicio y cierre de sesión (RF-01, RF-03, RF-04, RF-05)
# ---------------------------------------------------------------------------


@blueprint.get("/")
def raiz() -> Any:
    """Envía a la página de inicio del rol o al inicio de sesión."""
    # Responsable: Andrés Camilo Anaya García
    # RF-01
    if g.get("usuario") is not None:
        return redirect(url_for("acceso_cuentas.inicio"))
    return redirect(url_for("acceso_cuentas.iniciar_sesion"))


@blueprint.route("/iniciar-sesion", methods=["GET", "POST"])
def iniciar_sesion() -> Any:
    """Formulario de inicio de sesión con correo y contraseña."""
    # Responsable: Andrés Camilo Anaya García
    # RF-01 / RF-05
    if g.get("usuario") is not None:
        return redirect(url_for("acceso_cuentas.inicio"))
    formulario = FormularioInicioSesion()
    error = None
    if formulario.validate_on_submit():
        try:
            identificador = sesiones.iniciar_sesion(
                formulario.correo.data, formulario.contrasena.data
            )
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            # Sesión nueva: se descarta cualquier dato previo de la cookie.
            session.clear()
            session[CLAVE_SESION] = identificador
            destino = destino_seguro(request.args.get("siguiente"))
            return redirect(destino or url_for("acceso_cuentas.inicio"))
    return render_template(
        "acceso/iniciar_sesion.html", formulario=formulario, error=error
    ), (401 if error else 200)


@blueprint.post("/cerrar-sesion")
def cerrar_sesion() -> Any:
    """Cierra la sesión activa (RF-03)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-03
    sesiones.cerrar_sesion(session.get(CLAVE_SESION))
    session.clear()
    flash("Cerró sesión correctamente.", "exito")
    return redirect(url_for("acceso_cuentas.iniciar_sesion"))


@blueprint.get("/inicio")
@login_requerido
def inicio() -> Any:
    """Página de inicio del rol del usuario (RF-01)."""
    # Responsable: Andrés Camilo Anaya García
    # RF-01
    return render_template("acceso/inicio.html")


# ---------------------------------------------------------------------------
# Restablecimiento de contraseña (RF-06, RF-07)
# ---------------------------------------------------------------------------


@blueprint.route("/recuperar-contrasena", methods=["GET", "POST"])
def recuperar_contrasena() -> Any:
    """Solicitud del enlace de restablecimiento (RF-06)."""
    # Responsable: Islender Arturo Alfonso
    # RF-06
    formulario = FormularioSolicitudRestablecimiento()
    if formulario.validate_on_submit():
        enlaces_cuenta.solicitar_restablecimiento(formulario.correo.data)
        # La respuesta es la misma exista o no el correo.
        flash(MENSAJE_SOLICITUD_ENVIADA, "info")
        return redirect(url_for("acceso_cuentas.iniciar_sesion"))
    return render_template("acceso/recuperar_contrasena.html", formulario=formulario)


@blueprint.route("/restablecer-contrasena/<token>", methods=["GET", "POST"])
def restablecer_contrasena(token: str) -> Any:
    """Definición de una nueva contraseña desde el enlace (RF-07)."""
    # Responsable: Sofi Celmar Galvis
    # RF-07
    return _formulario_desde_enlace(
        token,
        proposito=enlaces_cuenta.PROPOSITO_RESTABLECIMIENTO,
        accion=enlaces_cuenta.restablecer_contrasena,
        titulo="Restablecer contraseña",
        mensaje_exito=(
            "Su contraseña se actualizó. Las sesiones abiertas se cerraron; "
            "inicie sesión con la nueva contraseña."
        ),
    )


# ---------------------------------------------------------------------------
# Activación de cuenta (RF-09)
# ---------------------------------------------------------------------------


@blueprint.route("/activar-cuenta/<token>", methods=["GET", "POST"])
def activar_cuenta(token: str) -> Any:
    """Activación de la cuenta y definición de la contraseña inicial (RF-09)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-09
    return _formulario_desde_enlace(
        token,
        proposito=enlaces_cuenta.PROPOSITO_ACTIVACION,
        accion=enlaces_cuenta.activar_cuenta,
        titulo="Activar cuenta",
        mensaje_exito="Su cuenta está activa. Ya puede iniciar sesión.",
    )


def _formulario_desde_enlace(
    token: str, proposito: str, accion: Any, titulo: str, mensaje_exito: str
) -> Any:
    """Muestra y procesa el formulario de contraseña de un enlace de un solo uso."""
    # Responsable: Sofi Celmar Galvis
    # RF-07 / RF-09
    try:
        enlaces_cuenta.obtener_enlace_vigente(token, proposito)
    except ErrorNegocio as fallo:
        return (
            render_template("acceso/enlace_invalido.html", mensaje=fallo.mensaje),
            410,
        )
    formulario = FormularioNuevaContrasena()
    error = None
    if formulario.validate_on_submit():
        try:
            accion(token, formulario.contrasena.data, formulario.confirmacion.data)
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            session.clear()
            flash(mensaje_exito, "exito")
            return redirect(url_for("acceso_cuentas.iniciar_sesion"))
    return render_template(
        "acceso/definir_contrasena.html",
        formulario=formulario,
        titulo=titulo,
        error=error,
        politica=MENSAJE_POLITICA,
    )


# ---------------------------------------------------------------------------
# Administración de cuentas (RF-08, RF-10, RF-11, RF-12)
# ---------------------------------------------------------------------------


def _opciones_rol() -> list[tuple[str, str]]:
    """Opciones del selector de rol."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-08 / RF-10
    return [("", "Seleccione un rol")] + [
        (rol.codigo, rol.nombre) for rol in cuentas.listar_roles()
    ]


def _datos_formulario(formulario: FormularioCuenta) -> cuentas.DatosCuenta:
    """Convierte el formulario en los datos que recibe el servicio."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-08 / RF-10
    return cuentas.DatosCuenta(
        nombre_completo=formulario.nombre_completo.data or "",
        correo=formulario.correo.data or "",
        rol_codigo=formulario.rol.data or "",
    )


@blueprint.get("/cuentas")
@rol_requerido(cuentas.ROL_ADMINISTRADOR)
def lista_cuentas() -> Any:
    """Listado de usuarios con filtros por rol y estado y búsqueda (RF-12)."""
    # Responsable: Islender Arturo Alfonso
    # RF-12
    filtros = {
        "rol": request.args.get("rol", ""),
        "estado": request.args.get("estado", ""),
        "q": request.args.get("q", "").strip(),
    }
    paginacion = cuentas.listar_usuarios(
        rol_codigo=filtros["rol"] or None,
        estado=filtros["estado"] or None,
        texto=filtros["q"] or None,
        pagina=request.args.get("pagina", 1, type=int),
    )
    return render_template(
        "cuentas/lista.html",
        paginacion=paginacion,
        filtros=filtros,
        roles=cuentas.listar_roles(),
        estados=cuentas.ESTADOS_CUENTA,
        momento=ahora(),
    )


@blueprint.route("/cuentas/nueva", methods=["GET", "POST"])
@rol_requerido(cuentas.ROL_ADMINISTRADOR)
def lista_cuentas_nueva() -> Any:
    """Creación de una cuenta con envío del enlace de activación (RF-08)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-08
    formulario = FormularioCuenta()
    formulario.rol.choices = _opciones_rol()
    error = None
    if formulario.validate_on_submit():
        try:
            usuario = cuentas.crear_cuenta(_datos_formulario(formulario), g.usuario.id)
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            flash(
                f"Se creó la cuenta de {usuario.nombre_completo} y se envió el "
                "enlace de activación a su correo.",
                "exito",
            )
            return redirect(url_for("acceso_cuentas.lista_cuentas"))
    return render_template(
        "cuentas/formulario.html",
        formulario=formulario,
        titulo="Nueva cuenta",
        error=error,
        usuario=None,
    )


@blueprint.route("/cuentas/<int:usuario_id>/editar", methods=["GET", "POST"])
@rol_requerido(cuentas.ROL_ADMINISTRADOR)
def lista_cuentas_editar(usuario_id: int) -> Any:
    """Modificación de nombre, correo y rol de una cuenta (RF-10)."""
    # Responsable: Sofi Celmar Galvis
    # RF-10
    try:
        usuario = cuentas.obtener_usuario(usuario_id)
    except ErrorNegocio:
        abort(404)
    formulario = FormularioCuenta()
    formulario.rol.choices = _opciones_rol()
    if request.method == "GET":
        formulario.nombre_completo.data = usuario.nombre_completo
        formulario.correo.data = usuario.correo
        formulario.rol.data = usuario.rol.codigo
    error = None
    if formulario.validate_on_submit():
        try:
            usuario = cuentas.modificar_cuenta(
                usuario_id, _datos_formulario(formulario), g.usuario.id
            )
        except ErrorNegocio as fallo:
            error = fallo.mensaje
        else:
            flash(
                f"Se guardaron los cambios de {usuario.nombre_completo}. "
                "Un cambio de rol aplica desde su siguiente inicio de sesión.",
                "exito",
            )
            return redirect(url_for("acceso_cuentas.lista_cuentas"))
    return render_template(
        "cuentas/formulario.html",
        formulario=formulario,
        titulo="Editar cuenta",
        error=error,
        usuario=usuario,
    )


@blueprint.post("/cuentas/<int:usuario_id>/estado/<accion>")
@rol_requerido(cuentas.ROL_ADMINISTRADOR)
def lista_cuentas_estado(usuario_id: int, accion: str) -> Any:
    """Activa, desactiva, bloquea o desbloquea una cuenta (RF-11)."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-11
    if accion not in cuentas.ACCIONES_ESTADO:
        abort(404)
    try:
        usuario = cuentas.cambiar_estado(usuario_id, accion, g.usuario.id)
    except ErrorNegocio as fallo:
        flash(fallo.mensaje, "error")
    else:
        estado = cuentas.ESTADOS_CUENTA[usuario.estado_cuenta].lower()
        flash(f"La cuenta de {usuario.nombre_completo} quedó {estado}.", "exito")
    return redirect(_volver_a_lista())


@blueprint.post("/cuentas/<int:usuario_id>/reenviar-activacion")
@rol_requerido(cuentas.ROL_ADMINISTRADOR)
def lista_cuentas_reenviar(usuario_id: int) -> Any:
    """Envía un enlace de activación nuevo a una cuenta pendiente (RF-08)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-08
    try:
        usuario = cuentas.reenviar_activacion(usuario_id, g.usuario.id)
    except ErrorNegocio as fallo:
        flash(fallo.mensaje, "error")
    else:
        flash(f"Se envió un enlace de activación nuevo a {usuario.correo}.", "exito")
    return redirect(_volver_a_lista())


def _volver_a_lista() -> str:
    """Regresa al listado conservando filtros si la petición los trae."""
    # Responsable: Islender Arturo Alfonso
    # RF-12
    return destino_seguro(request.form.get("volver")) or url_for(
        "acceso_cuentas.lista_cuentas"
    )
