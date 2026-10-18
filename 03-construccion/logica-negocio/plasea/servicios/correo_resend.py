"""Envio de correo mediante la API HTTPS de Resend.

Alternativa a SMTP para la nube: Railway bloquea los puertos SMTP en los
planes Free, Trial y Hobby, pero permite HTTPS (puerto 443).
Aplica a los tres correos del sistema: RF-06, RF-08 y RF-57.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Optional

registro = logging.getLogger("plasea.correo")

URL_API_RESEND = "https://api.resend.com/emails"
TIEMPO_ESPERA_RESEND = 15
_AGENTE_USUARIO = "plasea/1.0"
_LONGITUD_MAXIMA_DETALLE = 300


class ErrorResend(Exception):
    """Error al enviar un correo mediante la API de Resend."""


def enviar_resend(
    destinatario: str,
    asunto: str,
    cuerpo_texto: str,
    cuerpo_html: Optional[str] = None,
    *,
    clave_api: str,
    remitente: str,
) -> None:
    """Envia un correo a un destinatario usando la API HTTPS de Resend.

    Args:
        destinatario: Correo del destinatario.
        asunto: Asunto del mensaje.
        cuerpo_texto: Contenido en texto plano.
        cuerpo_html: Contenido HTML opcional.
        clave_api: Clave de la API de Resend (variable de entorno).
        remitente: Remitente, por ejemplo "PLASEA <onboarding@resend.dev>".

    Raises:
        ErrorResend: Si falta la clave, el remitente o la API rechaza el envio.
    """
    if not clave_api or not remitente:
        raise ErrorResend("Falta RESEND_API_KEY o CORREO_REMITENTE.")

    carga: dict = {
        "from": remitente,
        "to": [destinatario],
        "subject": asunto,
        "text": cuerpo_texto,
    }
    if cuerpo_html:
        carga["html"] = cuerpo_html

    solicitud = urllib.request.Request(
        URL_API_RESEND,
        data=json.dumps(carga).encode("utf-8"),
        method="POST",
    )
    solicitud.add_header("Authorization", f"Bearer {clave_api}")
    solicitud.add_header("Content-Type", "application/json")
    # Resend rechaza solicitudes sin User-Agent.
    solicitud.add_header("User-Agent", _AGENTE_USUARIO)

    try:
        with urllib.request.urlopen(
            solicitud, timeout=TIEMPO_ESPERA_RESEND
        ) as respuesta:
            cuerpo = json.loads(respuesta.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        detalle = error.read().decode("utf-8", errors="replace")
        raise ErrorResend(
            f"Resend respondio {error.code}: " f"{detalle[:_LONGITUD_MAXIMA_DETALLE]}"
        ) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise ErrorResend(f"No se pudo contactar a Resend: {error}") from error

    registro.info("Correo enviado por Resend (id=%s).", cuerpo.get("id"))
