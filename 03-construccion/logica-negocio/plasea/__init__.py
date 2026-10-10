"""Paquete principal de PLASEA (Plataforma de Seguimiento Académico).

Contiene la fábrica de aplicación ``crear_app``. Uso desde la raíz del repositorio
(PowerShell)::

    flask run          # FLASK_APP se toma de .flaskenv
    flask seed         # datos predeterminados (03-construccion/scripts/seed.py)
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any, Optional

from flask import Flask
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect

from plasea import autorizacion, web_comun
from plasea.configuracion import cargar_configuracion
from plasea.modelos import db
from plasea.rutas import (
    acceso_cuentas,
    alertas_analitica,
    ayuda_informacion,
    bitacora_administracion,
    cierre_cortes,
    continuidad_desercion,
    estructura_academica,
    estudiantes_inscripciones,
    exportacion,
    graficos_tablero,
    notificaciones_correo,
    registro_asistencia_notas,
)

RUTA_CONSTRUCCION = Path(__file__).resolve().parents[2]
RUTA_PLANTILLAS = RUTA_CONSTRUCCION / "interfaz" / "plantillas"
RUTA_ESTATICOS = RUTA_CONSTRUCCION / "interfaz" / "estaticos"
RUTA_SCRIPT_SEED = RUTA_CONSTRUCCION / "scripts" / "seed.py"
RUTA_MIGRACIONES = Path(__file__).resolve().parent / "migraciones"


BLUEPRINTS_EPICAS = (
    (acceso_cuentas, ""),
    (estructura_academica, "/estructura"),
    (estudiantes_inscripciones, "/estudiantes"),
    (registro_asistencia_notas, "/registro"),
    (cierre_cortes, "/cortes"),
    (alertas_analitica, "/alertas"),
    (continuidad_desercion, "/continuidad"),
    (graficos_tablero, "/graficos"),
    (notificaciones_correo, "/notificaciones"),
    (exportacion, "/exportacion"),
    (bitacora_administracion, "/bitacora"),
    (ayuda_informacion, "/ayuda"),
)

csrf = CSRFProtect()
migrate = Migrate()
registro = logging.getLogger(__name__)


def crear_app(configuracion_extra: Optional[dict[str, Any]] = None) -> Flask:
    """Crea y configura la aplicación Flask de PLASEA.

    Args:
        configuracion_extra: valores que reemplazan la configuración leída del
            entorno (útil en pruebas).

    Returns:
        La aplicación configurada, con extensiones, blueprints y comandos CLI.
    """
    # Responsable: Sofi Celmar Galvis
    # RNF-03 / RNF-08
    app = Flask(
        __name__,
        template_folder=str(RUTA_PLANTILLAS),
        static_folder=str(RUTA_ESTATICOS),
        static_url_path="/estaticos",
    )
    app.config.update(cargar_configuracion())
    if configuracion_extra:
        app.config.update(configuracion_extra)
    _validar_configuracion(app)
    _configurar_registro()

    db.init_app(app)
    migrate.init_app(app, db, directory=str(RUTA_MIGRACIONES))
    csrf.init_app(app)

    autorizacion.registrar(app)
    web_comun.registrar(app)
    _registrar_blueprints(app)
    _registrar_comandos(app)
    return app


def _configurar_registro() -> None:
    """Muestra en consola los mensajes INFO de PLASEA (por ejemplo, los correos)."""
    # Responsable: Sofi Celmar Galvis
    # RF-06 / RF-08
    registro_plasea = logging.getLogger("plasea")
    if not registro_plasea.handlers:
        manejador = logging.StreamHandler()
        manejador.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        registro_plasea.addHandler(manejador)
    registro_plasea.setLevel(logging.INFO)


def _validar_configuracion(app: Flask) -> None:
    """Detiene el arranque si faltan variables de entorno obligatorias."""
    # Responsable: Sofi Celmar Galvis
    # RNF-01 / RNF-08
    faltantes = [
        variable
        for variable, clave in (
            ("CLAVE_SECRETA", "SECRET_KEY"),
            ("URL_BASE_DATOS", "SQLALCHEMY_DATABASE_URI"),
        )
        if not app.config.get(clave)
    ]
    if faltantes:
        raise RuntimeError(
            "Faltan variables de entorno: "
            + ", ".join(faltantes)
            + ". Copie .env.example a .env y complételas."
        )


def _registrar_blueprints(app: Flask) -> None:
    """Registra los 12 blueprints de las épicas E1 a E12."""
    # Responsable: Sofi Celmar Galvis
    # RNF-03
    for modulo, prefijo in BLUEPRINTS_EPICAS:
        app.register_blueprint(modulo.blueprint, url_prefix=prefijo or None)


def _registrar_comandos(app: Flask) -> None:
    """Registra el comando ``flask seed`` definido en 03-construccion/scripts/seed.py.

    La carpeta ``scripts`` no es un paquete importable (su ruta tiene guion), por
    eso el módulo se carga desde su archivo.
    """
    # Responsable: Sofi Celmar Galvis
    # RF-25
    if not RUTA_SCRIPT_SEED.is_file():
        registro.warning(
            "No se encontró %s; 'flask seed' no está disponible.", RUTA_SCRIPT_SEED
        )
        return
    especificacion = importlib.util.spec_from_file_location(
        "plasea_scripts_seed", RUTA_SCRIPT_SEED
    )
    if especificacion is None or especificacion.loader is None:
        registro.warning("No se pudo cargar %s.", RUTA_SCRIPT_SEED)
        return
    modulo_seed = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo_seed)
    app.cli.add_command(modulo_seed.comando_seed)
