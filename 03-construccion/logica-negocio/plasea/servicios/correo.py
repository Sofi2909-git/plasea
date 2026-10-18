"""Envío de correo (RF-06, RF-08 y, más adelante, RF-57).

Modos (variable de entorno ``CORREO_MODO``):
- ``consola`` (por defecto): el correo se escribe en la terminal. Es el modo de
  trabajo local; no se configura Gmail.
- ``smtp``: envío real con las credenciales de las variables ``CORREO_*``.

Un fallo de envío no rompe el flujo que lo origina: queda registrado en el log.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import threading
from email.message import EmailMessage
from typing import Any

from flask import current_app

registro = logging.getLogger("plasea.correo")

MODO_CONSOLA = "consola"
MODO_SMTP = "smtp"
_TIEMPO_ESPERA_SMTP = 15


def enviar_correo(destinatario: str, asunto: str, cuerpo: str) -> None:
    """Envía un correo de texto plano según el modo configurado.

    En modo SMTP el envío se hace en un hilo aparte para no demorar la respuesta
    (así el tiempo de respuesta no revela si el correo existe, RF-06).
    """
    # Responsable: Islender Arturo Alfonso
    # RF-06 / RF-08
    configuracion = current_app.config
    mensaje = EmailMessage()
    mensaje["From"] = configuracion["CORREO_REMITENTE"]
    mensaje["To"] = destinatario
    mensaje["Subject"] = asunto
    mensaje.set_content(cuerpo)

    if configuracion.get("CORREO_MODO", MODO_CONSOLA) != MODO_SMTP:
        registro.info(
            "\n===== CORREO (modo consola) =====\nPara: %s\nAsunto: %s\n\n%s\n"
            "=================================",
            destinatario,
            asunto,
            cuerpo,
        )
        return

    datos_smtp = {
        clave: configuracion[clave]
        for clave in (
            "CORREO_SERVIDOR",
            "CORREO_PUERTO",
            "CORREO_USA_TLS",
            "CORREO_USUARIO",
            "CORREO_CLAVE_APLICACION",
        )
    }
    threading.Thread(
        target=_enviar_smtp, args=(mensaje, datos_smtp), daemon=True
    ).start()


def _enviar_smtp(mensaje: EmailMessage, datos: dict[str, Any]) -> None:
    """Entrega el mensaje al servidor SMTP. Registra el fallo sin propagarlo."""
    # Responsable: Islender Arturo Alfonso
    # RF-06 / RF-08
    try:
        with smtplib.SMTP(
            datos["CORREO_SERVIDOR"],
            datos["CORREO_PUERTO"],
            timeout=_TIEMPO_ESPERA_SMTP,
        ) as servidor:
            if datos["CORREO_USA_TLS"]:
                servidor.starttls(context=ssl.create_default_context())
            if datos["CORREO_USUARIO"]:
                servidor.login(
                    datos["CORREO_USUARIO"], datos["CORREO_CLAVE_APLICACION"]
                )
            servidor.send_message(mensaje)
        registro.info("Correo enviado a %s (%s).", mensaje["To"], mensaje["Subject"])
    except (smtplib.SMTPException, OSError) as error:
        registro.exception(
            "No se pudo enviar el correo a %s (%s). Error: %s",
            mensaje["To"],
            mensaje["Subject"],
            error,
        )
