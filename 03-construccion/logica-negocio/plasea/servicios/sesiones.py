"""Inicio, validación y cierre de sesiones (RF-01, RF-03, RF-04 y RF-05).

Las sesiones viven en el servidor (tabla ``sesiones_usuario``). La cookie del
navegador solo guarda un identificador opaco; en la base de datos se guarda su
SHA-256. El rol de la sesión es el vigente al iniciarla (RF-10).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import secrets
from dataclasses import dataclass
from typing import Optional

from flask import current_app
from sqlalchemy import select

from plasea.modelos import SesionUsuario, Usuario, db
from plasea.servicios import bitacora, contrasenas
from plasea.servicios.comunes import ErrorNegocio, ahora

MENSAJE_CREDENCIALES_INVALIDAS = "Correo o contraseña incorrectos."
MENSAJE_CUENTA_NO_HABILITADA = (
    "Su cuenta no está habilitada para iniciar sesión. "
    "Comuníquese con el administrador del sistema."
)

MOTIVO_CIERRE_VOLUNTARIO = "cierre_voluntario"
MOTIVO_INACTIVIDAD = "inactividad"
MOTIVO_CUENTA_DESACTIVADA = "cuenta_desactivada"
MOTIVO_CUENTA_BLOQUEADA = "cuenta_bloqueada"

# La marca de última actividad se escribe como máximo una vez por minuto.
_INTERVALO_ACTUALIZACION = dt.timedelta(seconds=60)


@dataclass(frozen=True)
class ResultadoValidacion:
    """Resultado de validar la sesión de una petición."""

    sesion: Optional[SesionUsuario]
    expirada_por_inactividad: bool = False


def _hash_identificador(identificador: str) -> str:
    """Devuelve el SHA-256 del identificador de sesión."""
    # Responsable: Andrés Camilo Anaya García
    # RF-01
    return hashlib.sha256(identificador.encode("utf-8")).hexdigest()


def _minutos_restantes(hasta: dt.datetime, momento: dt.datetime) -> int:
    """Minutos completos que faltan (redondeo hacia arriba, mínimo 1)."""
    # Responsable: Sofi Celmar Galvis
    # RF-05
    return max(1, math.ceil((hasta - momento).total_seconds() / 60))


def iniciar_sesion(correo: str, contrasena: str) -> str:
    """Autentica al usuario y abre una sesión en el servidor.

    Reglas: mensaje genérico si las credenciales fallan (RF-01); bloqueo
    temporal tras los intentos fallidos configurados (RF-05); una cuenta que no
    está activa no inicia sesión (RF-01, RF-11).

    Returns:
        El identificador de sesión en claro, para guardarlo en la cookie.

    Raises:
        ErrorNegocio: con el mensaje que se debe mostrar.
    """
    # Responsable: Andrés Camilo Anaya García
    # RF-01 / RF-05
    correo_normalizado = (correo or "").strip().lower()
    try:
        usuario = db.session.scalar(
            select(Usuario)
            .where(Usuario.correo == correo_normalizado)
            .with_for_update()
        )
        momento = ahora()

        if usuario is None:
            contrasenas.verificar(contrasena, None)
            bitacora.registrar_evento(
                bitacora.EVENTO_INTENTO_FALLIDO,
                detalle="Intento con un correo no registrado",
            )
            db.session.commit()
            raise ErrorNegocio(MENSAJE_CREDENCIALES_INVALIDAS)

        # RF-05: bloqueo temporal vigente.
        if usuario.bloqueo_hasta is not None and usuario.bloqueo_hasta > momento:
            bitacora.registrar_evento(
                bitacora.EVENTO_INTENTO_FALLIDO,
                usuario_id=usuario.id,
                entidad="usuarios",
                entidad_id=usuario.id,
                detalle="Intento durante bloqueo temporal",
            )
            db.session.commit()
            raise ErrorNegocio(_mensaje_bloqueo(usuario.bloqueo_hasta, momento))

        # RF-05: el contador se reinicia al vencer el bloqueo.
        if usuario.bloqueo_hasta is not None:
            usuario.bloqueo_hasta = None
            usuario.intentos_fallidos = 0

        if not contrasenas.verificar(contrasena, usuario.contrasena_hash):
            mensaje = _registrar_fallo(usuario, momento)
            db.session.commit()
            raise ErrorNegocio(mensaje)

        if usuario.estado_cuenta != "activa":
            bitacora.registrar_evento(
                bitacora.EVENTO_INTENTO_FALLIDO,
                usuario_id=usuario.id,
                entidad="usuarios",
                entidad_id=usuario.id,
                detalle=f"Cuenta en estado {usuario.estado_cuenta}",
            )
            db.session.commit()
            raise ErrorNegocio(MENSAJE_CUENTA_NO_HABILITADA)

        usuario.intentos_fallidos = 0
        usuario.bloqueo_hasta = None
        identificador = secrets.token_urlsafe(32)
        sesion = SesionUsuario(
            usuario_id=usuario.id,
            rol_id=usuario.rol_id,
            token_hash=_hash_identificador(identificador),
            creada_en=momento,
            ultima_actividad_en=momento,
        )
        db.session.add(sesion)
        db.session.flush()
        bitacora.registrar_evento(
            bitacora.EVENTO_INICIO_SESION,
            usuario_id=usuario.id,
            entidad="sesiones_usuario",
            entidad_id=sesion.id,
        )
        db.session.commit()
        return identificador
    except ErrorNegocio:
        raise
    except Exception:
        db.session.rollback()
        raise


def _registrar_fallo(usuario: Usuario, momento: dt.datetime) -> str:
    """Suma un intento fallido y bloquea la cuenta si llega al máximo (RF-05)."""
    # Responsable: Sofi Celmar Galvis
    # RF-05
    configuracion = current_app.config
    usuario.intentos_fallidos = (usuario.intentos_fallidos or 0) + 1
    detalle = f"Contraseña incorrecta (intento {usuario.intentos_fallidos})"
    mensaje = MENSAJE_CREDENCIALES_INVALIDAS
    if usuario.intentos_fallidos >= configuracion["INTENTOS_FALLIDOS_MAXIMOS"]:
        usuario.bloqueo_hasta = momento + dt.timedelta(
            minutes=configuracion["DURACION_BLOQUEO_MINUTOS"]
        )
        detalle += "; cuenta bloqueada temporalmente"
        mensaje = _mensaje_bloqueo(usuario.bloqueo_hasta, momento)
    bitacora.registrar_evento(
        bitacora.EVENTO_INTENTO_FALLIDO,
        usuario_id=usuario.id,
        entidad="usuarios",
        entidad_id=usuario.id,
        detalle=detalle,
    )
    return mensaje


def _mensaje_bloqueo(hasta: dt.datetime, momento: dt.datetime) -> str:
    """Mensaje de bloqueo temporal con el tiempo restante (RF-05)."""
    # Responsable: Sofi Celmar Galvis
    # RF-05
    minutos = _minutos_restantes(hasta, momento)
    unidad = "minuto" if minutos == 1 else "minutos"
    return (
        "La cuenta está bloqueada temporalmente por varios intentos fallidos. "
        f"Intente de nuevo en {minutos} {unidad}."
    )


def validar_sesion(identificador: Optional[str]) -> ResultadoValidacion:
    """Valida la sesión de la petición y registra la actividad.

    Cierra la sesión si superó el tiempo de inactividad (RF-04) o si la cuenta
    dejó de estar activa (RF-11).
    """
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-04
    if not identificador or len(identificador) > 128:
        return ResultadoValidacion(sesion=None)
    sesion = db.session.scalar(
        select(SesionUsuario).where(
            SesionUsuario.token_hash == _hash_identificador(identificador),
            SesionUsuario.cerrada_en.is_(None),
        )
    )
    if sesion is None:
        return ResultadoValidacion(sesion=None)

    momento = ahora()
    limite = dt.timedelta(minutes=current_app.config["TIEMPO_INACTIVIDAD_MINUTOS"])
    try:
        if momento - sesion.ultima_actividad_en > limite:
            _cerrar(sesion, MOTIVO_INACTIVIDAD, momento)
            db.session.commit()
            return ResultadoValidacion(sesion=None, expirada_por_inactividad=True)

        estado = sesion.usuario.estado_cuenta
        if estado != "activa":
            motivo = (
                MOTIVO_CUENTA_BLOQUEADA
                if estado == "bloqueada"
                else MOTIVO_CUENTA_DESACTIVADA
            )
            _cerrar(sesion, motivo, momento)
            db.session.commit()
            return ResultadoValidacion(sesion=None)

        if momento - sesion.ultima_actividad_en >= _INTERVALO_ACTUALIZACION:
            sesion.ultima_actividad_en = momento
            db.session.commit()
        return ResultadoValidacion(sesion=sesion)
    except Exception:
        db.session.rollback()
        raise


def _cerrar(sesion: SesionUsuario, motivo: str, momento: dt.datetime) -> None:
    """Marca la sesión como cerrada y deja el evento en la bitácora."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-03 / RF-04
    sesion.cerrada_en = momento
    sesion.motivo_cierre = motivo
    bitacora.registrar_evento(
        bitacora.EVENTO_CIERRE_SESION,
        usuario_id=sesion.usuario_id,
        entidad="sesiones_usuario",
        entidad_id=sesion.id,
        detalle=f"Motivo: {motivo}",
    )


def cerrar_sesion(identificador: Optional[str]) -> None:
    """Cierra voluntariamente la sesión indicada (RF-03). Es idempotente."""
    # Responsable: Yeferson Fabián Jaimes
    # RF-03
    if not identificador or len(identificador) > 128:
        return
    try:
        sesion = db.session.scalar(
            select(SesionUsuario)
            .where(
                SesionUsuario.token_hash == _hash_identificador(identificador),
                SesionUsuario.cerrada_en.is_(None),
            )
            .with_for_update()
        )
        if sesion is not None:
            _cerrar(sesion, MOTIVO_CIERRE_VOLUNTARIO, ahora())
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def cerrar_sesiones_de_usuario(usuario_id: int, motivo: str) -> int:
    """Cierra todas las sesiones abiertas de un usuario (RF-11).

    No confirma la transacción: la confirma el caso de uso que la llama.

    Returns:
        Número de sesiones cerradas.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-11
    momento = ahora()
    sesiones = db.session.scalars(
        select(SesionUsuario).where(
            SesionUsuario.usuario_id == usuario_id,
            SesionUsuario.cerrada_en.is_(None),
        )
    ).all()
    for sesion in sesiones:
        _cerrar(sesion, motivo, momento)
    return len(sesiones)
