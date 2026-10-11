"""Administración de cuentas de usuario (RF-08, RF-10, RF-11 y RF-12).

Las cuentas nunca se eliminan, solo se desactivan (RF-11). Cada cambio queda en la
bitácora como ``cambio_administrativo`` (RF-61), sin datos personales en el detalle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from flask_sqlalchemy.pagination import Pagination
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from plasea.modelos import Rol, Usuario, db
from plasea.servicios import bitacora, enlaces_cuenta, sesiones
from plasea.servicios.comunes import ErrorNegocio, ahora

ROL_PROFESOR = "profesor"
ROL_AUDITOR = "auditor_academico"
ROL_ADMINISTRADOR = "administrador_sistema"
ROLES_VALIDOS = (ROL_PROFESOR, ROL_AUDITOR, ROL_ADMINISTRADOR)

ESTADO_PENDIENTE = "pendiente_activacion"
ESTADO_ACTIVA = "activa"
ESTADO_INACTIVA = "inactiva"
ESTADO_BLOQUEADA = "bloqueada"
ESTADOS_CUENTA = {
    ESTADO_PENDIENTE: "Pendiente de activación",
    ESTADO_ACTIVA: "Activa",
    ESTADO_INACTIVA: "Inactiva",
    ESTADO_BLOQUEADA: "Bloqueada",
}

ACCION_ACTIVAR = "activar"
ACCION_DESACTIVAR = "desactivar"
ACCION_BLOQUEAR = "bloquear"
ACCION_DESBLOQUEAR = "desbloquear"
ACCIONES_ESTADO = (
    ACCION_ACTIVAR,
    ACCION_DESACTIVAR,
    ACCION_BLOQUEAR,
    ACCION_DESBLOQUEAR,
)

USUARIOS_POR_PAGINA = 25
_PATRON_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class DatosCuenta:
    """Datos editables de una cuenta (RF-08 y RF-10)."""

    nombre_completo: str
    correo: str
    rol_codigo: str


def listar_roles() -> list[Rol]:
    """Devuelve los 3 roles fijos ordenados por nombre."""
    # Responsable: Islender Arturo Alfonso
    # RF-12
    return list(db.session.scalars(select(Rol).order_by(Rol.nombre)))


def listar_usuarios(
    rol_codigo: Optional[str] = None,
    estado: Optional[str] = None,
    texto: Optional[str] = None,
    pagina: int = 1,
) -> Pagination:
    """Lista usuarios filtrando por rol y estado y buscando por nombre o correo.

    La búsqueda no distingue mayúsculas ni tildes porque la columna usa la
    intercalación ``utf8mb4_spanish_ci`` de la base de datos (RF-12).
    """
    # Responsable: Islender Arturo Alfonso
    # RF-12
    consulta = select(Usuario).options(joinedload(Usuario.rol))
    if rol_codigo in ROLES_VALIDOS:
        consulta = consulta.join(Usuario.rol).where(Rol.codigo == rol_codigo)
    if estado in ESTADOS_CUENTA:
        consulta = consulta.where(Usuario.estado_cuenta == estado)
    texto_limpio = (texto or "").strip()[:150]
    if texto_limpio:
        consulta = consulta.where(
            or_(
                Usuario.nombre_completo.contains(texto_limpio, autoescape=True),
                Usuario.correo.contains(texto_limpio, autoescape=True),
            )
        )
    consulta = consulta.order_by(Usuario.nombre_completo, Usuario.id)
    return db.paginate(
        consulta, page=max(pagina, 1), per_page=USUARIOS_POR_PAGINA, error_out=False
    )


def obtener_usuario(usuario_id: int) -> Usuario:
    """Devuelve la cuenta o lanza ``ErrorNegocio`` si no existe."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-10 / RF-11
    usuario = db.session.get(Usuario, usuario_id)
    if usuario is None:
        raise ErrorNegocio("La cuenta solicitada no existe.")
    return usuario


def _normalizar(datos: DatosCuenta) -> DatosCuenta:
    """Limpia y valida los datos de una cuenta en el servidor."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-08 / RF-10
    nombre = " ".join(datos.nombre_completo.split())
    correo = datos.correo.strip().lower()
    if not 3 <= len(nombre) <= 150:
        raise ErrorNegocio("El nombre completo debe tener entre 3 y 150 caracteres.")
    if len(correo) > 254 or not _PATRON_CORREO.match(correo):
        raise ErrorNegocio("Escriba un correo electrónico válido.")
    if datos.rol_codigo not in ROLES_VALIDOS:
        raise ErrorNegocio("Seleccione un rol válido.")
    return DatosCuenta(nombre, correo, datos.rol_codigo)


def _rol_por_codigo(codigo: str) -> Rol:
    """Devuelve el rol con el código indicado."""
    # Responsable: Islender Arturo Alfonso
    # RF-02
    rol = db.session.scalar(select(Rol).where(Rol.codigo == codigo))
    if rol is None:
        raise ErrorNegocio("Seleccione un rol válido.")
    return rol


def _verificar_correo_disponible(correo: str, excluir_id: Optional[int] = None) -> None:
    """Verifica que el correo no sea de otra cuenta (sin distinguir mayúsculas)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-08 / RF-10
    consulta = select(Usuario.id).where(Usuario.correo == correo)
    if excluir_id is not None:
        consulta = consulta.where(Usuario.id != excluir_id)
    if db.session.scalar(consulta) is not None:
        raise ErrorNegocio("Ya existe una cuenta con ese correo.")


def _otros_administradores_activos(usuario_id: int) -> int:
    """Cuenta los demás administradores activos, bloqueando sus filas."""
    # Responsable: Sofi Celmar Galvis
    # RF-10
    ids = db.session.scalars(
        select(Usuario.id)
        .join(Usuario.rol)
        .where(
            Rol.codigo == ROL_ADMINISTRADOR,
            Usuario.estado_cuenta == ESTADO_ACTIVA,
            Usuario.id != usuario_id,
        )
        .with_for_update()
    ).all()
    return len(ids)


def crear_cuenta(datos: DatosCuenta, actor_id: int) -> Usuario:
    """Crea una cuenta pendiente de activación y envía el enlace de activación.

    Raises:
        ErrorNegocio: datos inválidos o correo ya registrado.
    """
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-08
    datos = _normalizar(datos)
    try:
        _verificar_correo_disponible(datos.correo)
        rol = _rol_por_codigo(datos.rol_codigo)
        momento = ahora()
        usuario = Usuario(
            nombre_completo=datos.nombre_completo,
            correo=datos.correo,
            rol_id=rol.id,
            estado_cuenta=ESTADO_PENDIENTE,
            intentos_fallidos=0,
            creado_en=momento,
            actualizado_en=momento,
        )
        db.session.add(usuario)
        db.session.flush()
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="usuarios",
            entidad_id=usuario.id,
            detalle=f"Creación de cuenta con rol {rol.codigo}",
        )
        enlaces_cuenta.enviar_enlace_activacion(usuario)
        db.session.commit()
        return usuario
    except Exception:
        db.session.rollback()
        raise


def reenviar_activacion(usuario_id: int, actor_id: int) -> Usuario:
    """Genera un enlace de activación nuevo para una cuenta pendiente (RF-08)."""
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-08
    try:
        usuario = obtener_usuario(usuario_id)
        if usuario.estado_cuenta != ESTADO_PENDIENTE:
            raise ErrorNegocio(
                "Solo se reenvía el enlace a cuentas pendientes de activación."
            )
        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="usuarios",
            entidad_id=usuario.id,
            detalle="Reenvío del enlace de activación",
        )
        enlaces_cuenta.enviar_enlace_activacion(usuario)
        db.session.commit()
        return usuario
    except Exception:
        db.session.rollback()
        raise


def modificar_cuenta(usuario_id: int, datos: DatosCuenta, actor_id: int) -> Usuario:
    """Modifica nombre, correo y rol de una cuenta (RF-10).

    El cambio de rol aplica desde el siguiente inicio de sesión: las sesiones
    abiertas conservan el rol con el que se iniciaron. No se puede quitar el rol
    al último administrador del sistema activo.

    Raises:
        ErrorNegocio: datos inválidos, correo duplicado o último administrador.
    """
    # Responsable: Sofi Celmar Galvis
    # RF-10
    datos = _normalizar(datos)
    try:
        usuario = db.session.get(Usuario, usuario_id, with_for_update=True)
        if usuario is None:
            raise ErrorNegocio("La cuenta solicitada no existe.")
        _verificar_correo_disponible(datos.correo, excluir_id=usuario.id)
        rol_nuevo = _rol_por_codigo(datos.rol_codigo)

        cambios = []
        if usuario.nombre_completo != datos.nombre_completo:
            cambios.append("nombre")
            usuario.nombre_completo = datos.nombre_completo
        if usuario.correo != datos.correo:
            cambios.append("correo")
            usuario.correo = datos.correo
            # Los enlaces enviados al correo anterior dejan de servir.
            enlaces_cuenta.invalidar_enlaces(usuario.id)
        if usuario.rol_id != rol_nuevo.id:
            if (
                usuario.rol.codigo == ROL_ADMINISTRADOR
                and _otros_administradores_activos(usuario.id) == 0
            ):
                raise ErrorNegocio(
                    "No se puede quitar el rol al último administrador del sistema."
                )
            cambios.append(f"rol ({usuario.rol.codigo} -> {rol_nuevo.codigo})")
            usuario.rol_id = rol_nuevo.id

        if cambios:
            bitacora.registrar_evento(
                bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
                usuario_id=actor_id,
                entidad="usuarios",
                entidad_id=usuario.id,
                detalle="Modificación de " + ", ".join(cambios),
            )
        db.session.commit()
        db.session.refresh(usuario)
        return usuario
    except Exception:
        db.session.rollback()
        raise


def cambiar_estado(usuario_id: int, accion: str, actor_id: int) -> Usuario:
    """Activa, desactiva, bloquea o desbloquea una cuenta (RF-11).

    - activar: inactiva -> activa (o pendiente de activación si nunca definió
      contraseña).
    - desactivar: activa, bloqueada o pendiente -> inactiva.
    - bloquear: activa -> bloqueada (bloqueo administrativo).
    - desbloquear: bloqueada -> activa; también levanta el bloqueo temporal por
      intentos fallidos (RF-05).

    Al desactivar o bloquear se cierran las sesiones abiertas y se invalidan los
    enlaces pendientes.

    Raises:
        ErrorNegocio: acción no permitida para el estado actual, sobre la propia
            cuenta o sobre el último administrador activo.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-11
    if accion not in ACCIONES_ESTADO:
        raise ErrorNegocio("Acción no válida.")
    try:
        usuario = db.session.get(Usuario, usuario_id, with_for_update=True)
        if usuario is None:
            raise ErrorNegocio("La cuenta solicitada no existe.")
        estado_anterior = usuario.estado_cuenta
        momento = ahora()

        if accion in (ACCION_DESACTIVAR, ACCION_BLOQUEAR):
            if usuario.id == actor_id:
                raise ErrorNegocio("No puede desactivar ni bloquear su propia cuenta.")
            if (
                usuario.rol.codigo == ROL_ADMINISTRADOR
                and usuario.estado_cuenta == ESTADO_ACTIVA
                and _otros_administradores_activos(usuario.id) == 0
            ):
                raise ErrorNegocio(
                    "No se puede desactivar ni bloquear al último administrador "
                    "del sistema activo."
                )

        if accion == ACCION_ACTIVAR:
            if estado_anterior != ESTADO_INACTIVA:
                raise ErrorNegocio("Solo se activan cuentas inactivas.")
            usuario.estado_cuenta = (
                ESTADO_ACTIVA if usuario.contrasena_hash else ESTADO_PENDIENTE
            )
        elif accion == ACCION_DESACTIVAR:
            if estado_anterior == ESTADO_INACTIVA:
                raise ErrorNegocio("La cuenta ya está inactiva.")
            usuario.estado_cuenta = ESTADO_INACTIVA
        elif accion == ACCION_BLOQUEAR:
            if estado_anterior != ESTADO_ACTIVA:
                raise ErrorNegocio("Solo se bloquean cuentas activas.")
            usuario.estado_cuenta = ESTADO_BLOQUEADA
        else:  # desbloquear
            bloqueo_temporal = (
                usuario.bloqueo_hasta is not None and usuario.bloqueo_hasta > momento
            )
            if estado_anterior != ESTADO_BLOQUEADA and not bloqueo_temporal:
                raise ErrorNegocio("La cuenta no está bloqueada.")
            if estado_anterior == ESTADO_BLOQUEADA:
                usuario.estado_cuenta = ESTADO_ACTIVA
            usuario.bloqueo_hasta = None
            usuario.intentos_fallidos = 0

        if accion in (ACCION_DESACTIVAR, ACCION_BLOQUEAR):
            motivo = (
                sesiones.MOTIVO_CUENTA_BLOQUEADA
                if accion == ACCION_BLOQUEAR
                else sesiones.MOTIVO_CUENTA_DESACTIVADA
            )
            sesiones.cerrar_sesiones_de_usuario(usuario.id, motivo)
            enlaces_cuenta.invalidar_enlaces(usuario.id, momento=momento)

        bitacora.registrar_evento(
            bitacora.EVENTO_CAMBIO_ADMINISTRATIVO,
            usuario_id=actor_id,
            entidad="usuarios",
            entidad_id=usuario.id,
            detalle=(f"Acción {accion}: {estado_anterior} -> {usuario.estado_cuenta}"),
        )
        db.session.commit()
        db.session.refresh(usuario)
        return usuario
    except Exception:
        db.session.rollback()
        raise
