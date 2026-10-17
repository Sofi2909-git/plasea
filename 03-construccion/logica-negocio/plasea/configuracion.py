"""Configuracion de PLASEA.

Los valores sensibles y de entorno se leen de variables de entorno (archivo ``.env``,
ver ``.env.example``). Los parametros tecnicos (RNF-09) viven aqui y se cambian
sin modificar la logica de la aplicacion.
"""

from __future__ import annotations

import os
from typing import Any


def _texto(nombre: str, por_defecto: str = "") -> str:
    """Lee una variable de entorno de texto."""
    return os.environ.get(nombre, por_defecto).strip()


def _entero(nombre: str, por_defecto: int) -> int:
    """Lee una variable de entorno entera; usa el valor por defecto si no existe."""
    valor = os.environ.get(nombre)
    return int(valor) if valor not in (None, "") else por_defecto


def _booleano(nombre: str, por_defecto: bool = False) -> bool:
    """Lee una variable de entorno booleana (true/false, 1/0, si/no)."""
    valor = os.environ.get(nombre)
    if valor in (None, ""):
        return por_defecto
    return valor.strip().lower() in ("1", "true", "si", "yes")


def cargar_configuracion() -> dict[str, Any]:
    """Construye el diccionario de configuracion de Flask a partir del entorno."""
    return {
        # --- Aplicacion ---
        "ENTORNO": _texto("ENTORNO", "desarrollo"),
        "SECRET_KEY": _texto("CLAVE_SECRETA"),
        "URL_BASE_ENLACES": _texto("URL_BASE_ENLACES", "http://localhost:5000"),
        "ZONA_HORARIA": "America/Bogota",
        # --- Base de datos (RNF-08: conexion por variable de entorno) ---
        "SQLALCHEMY_DATABASE_URI": _texto("URL_BASE_DATOS"),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "pool_pre_ping": True,
            "pool_recycle": 3600,
            # El esquema guarda fechas en hora de Colombia (UTC-5).
            "connect_args": {"init_command": "SET time_zone = '-05:00'"},
        },
        # --- Cookies de sesion (sin HTTPS en el prototipo local) ---
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": _booleano(
            "COOKIE_SEGURA", _texto("ENTORNO", "desarrollo").lower() == "produccion"
        ),
        # --- Proteccion CSRF (Flask-WTF) ---
        "WTF_CSRF_ENABLED": True,
        # --- Importacion CSV (RF-24: archivo de hasta 5 MB) ---
        "MAX_CONTENT_LENGTH": 5 * 1024 * 1024,
        # --- Parametros tecnicos (RNF-09) ---
        "TIEMPO_INACTIVIDAD_MINUTOS": 30,  # RF-04
        "INTENTOS_FALLIDOS_MAXIMOS": 3,  # RF-05
        "DURACION_BLOQUEO_MINUTOS": 15,  # RF-05
        "VIGENCIA_ENLACE_RESTABLECIMIENTO_MINUTOS": 60,  # RF-06
        # [SUPUESTO] RF-09 no fija el valor; se usa el mismo de RF-06 hasta definirlo.
        "VIGENCIA_ENLACE_ACTIVACION_MINUTOS": 60,
        # --- Correo (credenciales solo por variables de entorno) ---
        # consola = imprime los correos en la terminal (desarrollo); smtp = envio real.
        "CORREO_MODO": _texto("CORREO_MODO", "consola"),
        "CORREO_SERVIDOR": _texto("CORREO_SERVIDOR", "localhost"),
        "CORREO_PUERTO": _entero("CORREO_PUERTO", 1025),
        "CORREO_USA_TLS": _booleano("CORREO_USA_TLS", False),
        "CORREO_USUARIO": _texto("CORREO_USUARIO"),
        "CORREO_CLAVE_APLICACION": _texto("CORREO_CLAVE_APLICACION"),
        "CORREO_REMITENTE": _texto("CORREO_REMITENTE", "plasea@localhost"),
    }
