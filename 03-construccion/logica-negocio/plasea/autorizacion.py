"""Control de acceso por rol (RF-02) y carga de la sesión de cada petición (RF-04).

- ``cargar_sesion`` valida la sesión del servidor antes de cada petición.
- ``login_requerido`` y ``rol_requerido`` protegen las rutas en el servidor: no
  basta con ocultar el menú.
- ``MENU`` es la matriz de navegación: cada opción declara los roles que la ven.
  Cada épica agrega aquí sus opciones cuando implementa sus pantallas.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Optional, TypeVar
from urllib.parse import urlsplit

from flask import Flask, abort, flash, g, redirect, request, session, url_for

from plasea.servicios import sesiones
from plasea.servicios.cuentas import ROL_ADMINISTRADOR, ROL_AUDITOR, ROL_PROFESOR

CLAVE_SESION = "id_sesion"
F = TypeVar("F", bound=Callable[..., Any])

TODOS_LOS_ROLES = (ROL_PROFESOR, ROL_AUDITOR, ROL_ADMINISTRADOR)


@dataclass(frozen=True)
class OpcionMenu:
    """Opción de la navegación principal.

    ``blueprints`` marca la opción como activa en cualquier pantalla de esos
    blueprints. ``en_inicio`` la muestra como tarjeta en la página de inicio.
    """

    etiqueta: str
    endpoint: str
    roles: tuple[str, ...]
    descripcion: str = ""
    blueprints: tuple[str, ...] = ()
    en_inicio: bool = True


MENU: tuple[OpcionMenu, ...] = (
    OpcionMenu("Inicio", "acceso_cuentas.inicio", TODOS_LOS_ROLES, en_inicio=False),
    OpcionMenu(
        "Cuentas de usuario",
        "acceso_cuentas.lista_cuentas",
        (ROL_ADMINISTRADOR,),
        "Cree cuentas, cambie roles y active, desactive, bloquee o desbloquee accesos.",
    ),
    OpcionMenu(
        "Mis cursos",
        "registro_asistencia_notas.mis_cursos",
        (ROL_PROFESOR,),
        "Sus cursos del período, la asistencia por sesión y las notas de cada "
        "corte.",
        blueprints=("registro_asistencia_notas",),
    ),
    OpcionMenu(
        "Estructura académica",
        "estructura_academica.panel",
        (ROL_AUDITOR,),
        "Períodos, cortes, festivos, asignaturas, cursos con horario y umbrales de "
        "alerta.",
        blueprints=("estructura_academica",),
    ),
    OpcionMenu(
        "Estudiantes",
        "estudiantes_inscripciones.lista",
        (ROL_AUDITOR,),
        "Registro de estudiantes, historial de estados, inscripciones y carga por "
        "CSV.",
        blueprints=("estudiantes_inscripciones",),
    ),
    OpcionMenu(
        "Acerca de PLASEA",
        "ayuda_informacion.acerca",
        TODOS_LOS_ROLES,
        en_inicio=False,
    ),
    OpcionMenu(
        "Políticas",
        "ayuda_informacion.politicas",
        TODOS_LOS_ROLES,
        en_inicio=False,
    ),
)


def cargar_sesion() -> None:
    """Valida la sesión de la petición y deja el usuario en ``g`` (RF-04)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-04
    g.sesion = None
    g.usuario = None
    g.rol_codigo = None
    g.sesion_expirada = False
    if request.endpoint == "static":
        return
    identificador = session.get(CLAVE_SESION)
    if identificador is None:
        return
    resultado = sesiones.validar_sesion(identificador)
    if resultado.sesion is None:
        session.pop(CLAVE_SESION, None)
        g.sesion_expirada = resultado.expirada_por_inactividad
        return
    g.sesion = resultado.sesion
    g.usuario = resultado.sesion.usuario
    # RF-10: el rol de la sesión es el vigente al iniciarla.
    g.rol_codigo = resultado.sesion.rol.codigo


def destino_seguro(destino: Optional[str]) -> Optional[str]:
    """Acepta solo rutas internas de la aplicación como destino tras iniciar sesión."""
    # Responsable: Andrés Camilo Anaya García
    # RF-01
    if not destino or not destino.startswith("/") or destino.startswith("//"):
        return None
    partes = urlsplit(destino)
    if partes.scheme or partes.netloc or "\\" in destino:
        return None
    return destino


def _redirigir_a_inicio_sesion() -> Any:
    """Redirige al inicio de sesión conservando la ruta solicitada."""
    # Responsable: Islender Arturo Alfonso
    # RF-02
    if g.get("sesion_expirada"):
        flash("Su sesión se cerró por inactividad. Inicie sesión de nuevo.", "aviso")
    else:
        flash("Inicie sesión para continuar.", "info")
    siguiente = request.full_path if request.method == "GET" else None
    return redirect(
        url_for("acceso_cuentas.iniciar_sesion", siguiente=destino_seguro(siguiente))
    )


def login_requerido(vista: F) -> F:
    """Exige una sesión válida; si no la hay, redirige al inicio de sesión."""

    @wraps(vista)
    def envoltura(*args: Any, **kwargs: Any) -> Any:
        # Responsable: Islender Arturo Alfonso
        # RF-02
        if g.get("usuario") is None:
            return _redirigir_a_inicio_sesion()
        return vista(*args, **kwargs)

    return envoltura  # type: ignore[return-value]


def rol_requerido(*roles: str) -> Callable[[F], F]:
    """Exige sesión y uno de los roles indicados; si no, responde HTTP 403."""

    def decorador(vista: F) -> F:
        @wraps(vista)
        def envoltura(*args: Any, **kwargs: Any) -> Any:
            # Responsable: Islender Arturo Alfonso
            # RF-02
            if g.get("usuario") is None:
                return _redirigir_a_inicio_sesion()
            if g.rol_codigo not in roles:
                abort(403)
            return vista(*args, **kwargs)

        return envoltura  # type: ignore[return-value]

    return decorador


def opciones_menu() -> list[dict[str, Any]]:
    """Devuelve las opciones del menú permitidas para el rol de la sesión (RF-02)."""
    # Responsable: Islender Arturo Alfonso
    # RF-02 (opciones de E2, E3 y E12: Yeferson Fabián Jaimes, RF-13 a RF-23,
    # RF-62 y RF-63)
    rol = g.get("rol_codigo")
    if rol is None:
        return []
    endpoint_actual = request.endpoint or ""
    return [
        {
            "etiqueta": opcion.etiqueta,
            "url": url_for(opcion.endpoint),
            "descripcion": opcion.descripcion,
            "en_inicio": opcion.en_inicio,
            "activa": endpoint_actual == opcion.endpoint
            or endpoint_actual.startswith(opcion.endpoint + "_")
            or request.blueprint in opcion.blueprints,
        }
        for opcion in MENU
        if rol in opcion.roles
    ]


def registrar(app: Flask) -> None:
    """Conecta la carga de sesión y el menú a la aplicación."""
    # Responsable: Islender Arturo Alfonso
    # RF-02
    app.before_request(cargar_sesion)

    @app.context_processor
    def contexto_autorizacion() -> dict[str, Any]:
        # Responsable: Islender Arturo Alfonso
        # RF-02
        return {
            "usuario_actual": g.get("usuario"),
            "rol_actual": g.get("rol_codigo"),
            "menu": opciones_menu(),
        }
