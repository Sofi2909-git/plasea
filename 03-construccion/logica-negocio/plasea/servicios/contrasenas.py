"""Política y almacenamiento de contraseñas (RF-07, RF-09; RNF-01)."""

from __future__ import annotations

import re

from werkzeug.security import check_password_hash, generate_password_hash

from plasea.servicios.comunes import ErrorNegocio

LONGITUD_MINIMA = 8
LONGITUD_MAXIMA = 128  # Evita cálculos de hash costosos con textos enormes.
MENSAJE_POLITICA = (
    "La contraseña debe tener mínimo 8 caracteres, al menos una letra mayúscula "
    "y al menos un número."
)

# Hash fijo para igualar el tiempo de respuesta cuando el correo no existe (RF-01).
_HASH_SIMULADO = generate_password_hash("contrasena-simulada-plasea")


def validar_politica(contrasena: str, confirmacion: str) -> None:
    """Verifica la política de contraseñas y que la confirmación coincida.

    Raises:
        ErrorNegocio: si la contraseña no cumple la política o no coincide.
    """
    # Responsable: Sofi Celmar Galvis
    # RF-07 / RF-09
    if contrasena != confirmacion:
        raise ErrorNegocio("La contraseña y su confirmación no coinciden.")
    cumple = (
        LONGITUD_MINIMA <= len(contrasena) <= LONGITUD_MAXIMA
        and re.search(r"[A-ZÁÉÍÓÚÑ]", contrasena) is not None
        and re.search(r"\d", contrasena) is not None
    )
    if not cumple:
        raise ErrorNegocio(MENSAJE_POLITICA)


def generar_hash(contrasena: str) -> str:
    """Devuelve el hash de la contraseña (werkzeug, scrypt)."""
    # Responsable: Sofi Celmar Galvis
    # RF-07 / RF-09
    return generate_password_hash(contrasena)


def verificar(contrasena: str, contrasena_hash: str | None) -> bool:
    """Compara una contraseña con su hash en tiempo similar exista o no el hash."""
    # Responsable: Andrés Camilo Anaya García
    # RF-01
    if not contrasena_hash or len(contrasena) > LONGITUD_MAXIMA:
        check_password_hash(_HASH_SIMULADO, contrasena[:LONGITUD_MAXIMA])
        return False
    return check_password_hash(contrasena_hash, contrasena)
