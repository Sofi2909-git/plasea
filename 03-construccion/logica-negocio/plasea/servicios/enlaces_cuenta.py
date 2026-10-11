"""Enlaces de un solo uso: activación de cuenta y restablecimiento de contraseña.

RF-06 y RF-07 (restablecimiento), RF-08 y RF-09 (activación).

El token se envía solo por correo; en la base de datos se guarda su SHA-256.
Cada enlace nuevo invalida los anteriores del mismo propósito y usuario.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from typing import Optional

from flask import current_app, render_template, url_for
from sqlalchemy import select, update

from plasea.modelos import SesionUsuario, TokenCuenta, Usuario, db
from plasea.servicios import contrasenas
from plasea.servicios.comunes import ErrorNegocio, ahora
from plasea.servicios.correo import enviar_correo

PROPOSITO_ACTIVACION = "activacion"
PROPOSITO_RESTABLECIMIENTO = "restablecimiento"

_PATRON_TOKEN_MAXIMO = 128
MENSAJE_ENLACE_INVALIDO = (
    "El enlace no es válido: ya se usó, venció o fue reemplazado por uno más reciente."
)


def calcular_hash_token(token: str) -> str:
    """Devuelve el SHA-256 en hexadecimal de un token."""
    # Responsable: Islender Arturo Alfonso
    # RF-06
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _crear_token(usuario: Usuario, proposito: str) -> str:
    """Invalida los enlaces pendientes y crea uno nuevo; devuelve el token en claro."""
    # Responsable: Islender Arturo Alfonso
    # RF-06 / RF-08
    momento = ahora()
    invalidar_enlaces(usuario.id, proposito, momento)
    minutos = current_app.config[
        (
            "VIGENCIA_ENLACE_ACTIVACION_MINUTOS"
            if proposito == PROPOSITO_ACTIVACION
            else "VIGENCIA_ENLACE_RESTABLECIMIENTO_MINUTOS"
        )
    ]
    token = secrets.token_urlsafe(32)
    db.session.add(
        TokenCuenta(
            usuario_id=usuario.id,
            proposito=proposito,
            token_hash=calcular_hash_token(token),
            creado_en=momento,
            vence_en=momento + dt.timedelta(minutes=minutos),
        )
    )
    return token


def invalidar_enlaces(
    usuario_id: int,
    proposito: Optional[str] = None,
    momento: Optional[dt.datetime] = None,
) -> None:
    """Invalida los enlaces vigentes de un usuario (de un propósito o de todos)."""
    # Responsable: Islender Arturo Alfonso
    # RF-06 / RF-08
    condiciones = [
        TokenCuenta.usuario_id == usuario_id,
        TokenCuenta.usado_en.is_(None),
        TokenCuenta.invalidado_en.is_(None),
    ]
    if proposito is not None:
        condiciones.append(TokenCuenta.proposito == proposito)
    db.session.execute(
        update(TokenCuenta)
        .where(*condiciones)
        .values(invalidado_en=momento or ahora())
        .execution_options(synchronize_session=False)
    )


def _url_enlace(endpoint: str, token: str) -> str:
    """Arma la URL absoluta del enlace con la URL base configurada."""
    # Responsable: Islender Arturo Alfonso
    # RF-06 / RF-08
    base = current_app.config["URL_BASE_ENLACES"].rstrip("/")
    return base + url_for(endpoint, token=token)


def enviar_enlace_activacion(usuario: Usuario) -> None:
    """Crea el enlace de activación y lo envía al correo del usuario.

    El llamador confirma la transacción.
    """
    # Responsable: Wilson D'Alessandro Saavedra Rolón
    # RF-08
    token = _crear_token(usuario, PROPOSITO_ACTIVACION)
    minutos = current_app.config["VIGENCIA_ENLACE_ACTIVACION_MINUTOS"]
    cuerpo = render_template(
        "correos/activacion_cuenta.txt",
        nombre=usuario.nombre_completo,
        enlace=_url_enlace("acceso_cuentas.activar_cuenta", token),
        minutos=minutos,
    )
    enviar_correo(usuario.correo, "PLASEA: active su cuenta", cuerpo)


def solicitar_restablecimiento(correo: str) -> None:
    """Envía el enlace de restablecimiento si el correo es de una cuenta activa.

    La respuesta al usuario es la misma exista o no el correo (RF-06), por eso
    esta función no informa el resultado.
    """
    # Responsable: Islender Arturo Alfonso
    # RF-06
    correo_normalizado = correo.strip().lower()
    usuario = db.session.scalar(
        select(Usuario).where(Usuario.correo == correo_normalizado)
    )
    if usuario is None or usuario.estado_cuenta != "activa":
        return
    token = _crear_token(usuario, PROPOSITO_RESTABLECIMIENTO)
    db.session.commit()
    cuerpo = render_template(
        "correos/restablecimiento_contrasena.txt",
        nombre=usuario.nombre_completo,
        enlace=_url_enlace("acceso_cuentas.restablecer_contrasena", token),
        minutos=current_app.config["VIGENCIA_ENLACE_RESTABLECIMIENTO_MINUTOS"],
    )
    enviar_correo(usuario.correo, "PLASEA: restablecimiento de contraseña", cuerpo)


def obtener_enlace_vigente(
    token: str, proposito: str, bloquear: bool = False
) -> TokenCuenta:
    """Devuelve el enlace vigente que corresponde al token.

    Args:
        token: token recibido en la URL.
        proposito: ``activacion`` o ``restablecimiento``.
        bloquear: si es ``True`` bloquea la fila hasta el fin de la transacción
            para garantizar el uso único.

    Raises:
        ErrorNegocio: si el enlace no existe, ya se usó, venció o fue invalidado.
    """
    # Responsable: Sofi Celmar Galvis
    # RF-07 / RF-09
    if not token or len(token) > _PATRON_TOKEN_MAXIMO:
        raise ErrorNegocio(MENSAJE_ENLACE_INVALIDO)
    consulta = select(TokenCuenta).where(
        TokenCuenta.token_hash == calcular_hash_token(token),
        TokenCuenta.proposito == proposito,
    )
    if bloquear:
        consulta = consulta.with_for_update()
    enlace = db.session.scalar(consulta)
    if (
        enlace is None
        or enlace.usado_en is not None
        or enlace.invalidado_en is not None
        or enlace.vence_en <= ahora()
    ):
        raise ErrorNegocio(MENSAJE_ENLACE_INVALIDO)
    return enlace


def restablecer_contrasena(token: str, contrasena: str, confirmacion: str) -> None:
    """Define una nueva contraseña desde un enlace de restablecimiento vigente.

    Marca el enlace como usado, cierra todas las sesiones abiertas del usuario y
    reinicia el contador de intentos fallidos y el bloqueo temporal.

    Raises:
        ErrorNegocio: enlace inválido, cuenta no activa o contraseña que no
            cumple la política.
    """
    # Responsable: Sofi Celmar Galvis
    # RF-07
    contrasenas.validar_politica(contrasena, confirmacion)
    try:
        enlace = obtener_enlace_vigente(
            token, PROPOSITO_RESTABLECIMIENTO, bloquear=True
        )
        usuario = db.session.get(Usuario, enlace.usuario_id, with_for_update=True)
        if usuario is None or usuario.estado_cuenta != "activa":
            raise ErrorNegocio(MENSAJE_ENLACE_INVALIDO)
        momento = ahora()
        usuario.contrasena_hash = contrasenas.generar_hash(contrasena)
        usuario.intentos_fallidos = 0
        usuario.bloqueo_hasta = None
        enlace.usado_en = momento
        invalidar_enlaces(usuario.id, PROPOSITO_RESTABLECIMIENTO, momento)
        db.session.execute(
            update(SesionUsuario)
            .where(
                SesionUsuario.usuario_id == usuario.id,
                SesionUsuario.cerrada_en.is_(None),
            )
            .values(cerrada_en=momento, motivo_cierre="restablecimiento_contrasena")
            .execution_options(synchronize_session=False)
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def activar_cuenta(token: str, contrasena: str, confirmacion: str) -> None:
    """Activa la cuenta y define la contraseña inicial desde el enlace de activación.

    Raises:
        ErrorNegocio: enlace inválido, cuenta que ya no está pendiente o
            contraseña que no cumple la política.
    """
    # Responsable: Yeferson Fabián Jaimes
    # RF-09
    contrasenas.validar_politica(contrasena, confirmacion)
    try:
        enlace = obtener_enlace_vigente(token, PROPOSITO_ACTIVACION, bloquear=True)
        usuario = db.session.get(Usuario, enlace.usuario_id, with_for_update=True)
        if usuario is None or usuario.estado_cuenta != "pendiente_activacion":
            raise ErrorNegocio(MENSAJE_ENLACE_INVALIDO)
        momento = ahora()
        usuario.contrasena_hash = contrasenas.generar_hash(contrasena)
        usuario.estado_cuenta = "activa"
        usuario.intentos_fallidos = 0
        usuario.bloqueo_hasta = None
        enlace.usado_en = momento
        invalidar_enlaces(usuario.id, PROPOSITO_ACTIVACION, momento)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
