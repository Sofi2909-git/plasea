"""Configuración compartida de pytest para PLASEA.

Las pruebas funcionales y de seguridad usan una base de datos MariaDB de pruebas,
distinta de la de desarrollo, indicada en la variable ``URL_BASE_DATOS_PRUEBAS``
(ejemplo: mysql+pymysql://usuario:clave@localhost:3306/plasea_pruebas?charset=utf8mb4).
Si la variable no existe, esas pruebas se omiten. Las tablas se crean desde los
modelos y se vacían antes de cada prueba: NUNCA apunte esta variable a la base de
datos de desarrollo.
"""

from __future__ import annotations

import os
import re
from typing import Any, Iterator

import pytest
from sqlalchemy import delete

URL_PRUEBAS = os.environ.get("URL_BASE_DATOS_PRUEBAS", "")

ROLES = (
    ("profesor", "Profesor"),
    ("auditor_academico", "Auditor académico"),
    ("administrador_sistema", "Administrador del sistema"),
)
EVENTOS = (
    "inicio_sesion",
    "cierre_sesion",
    "intento_fallido",
    "cambio_administrativo",
)
CONTRASENA_PRUEBA = "Clave123*"


@pytest.fixture(scope="session")
def app() -> Iterator[Any]:
    """Aplicación de pruebas con la base de datos de pruebas recién creada."""
    if not URL_PRUEBAS:
        pytest.skip("Defina URL_BASE_DATOS_PRUEBAS para ejecutar las pruebas con BD.")
    if not URL_PRUEBAS.rsplit("/", 1)[-1].split("?")[0].endswith("_pruebas"):
        pytest.exit("URL_BASE_DATOS_PRUEBAS debe apuntar a una base *_pruebas.")
    os.environ.setdefault("CLAVE_SECRETA", "clave-solo-para-pruebas")
    os.environ.setdefault("URL_BASE_DATOS", URL_PRUEBAS)

    from plasea import crear_app
    from plasea.modelos import Rol, TipoEventoBitacora, db

    aplicacion = crear_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": URL_PRUEBAS,
            "WTF_CSRF_ENABLED": False,
            "CORREO_MODO": "consola",
            "URL_BASE_ENLACES": "http://localhost",
        }
    )
    with aplicacion.app_context():
        db.drop_all()
        db.create_all()
        db.session.add_all(Rol(codigo=c, nombre=n) for c, n in ROLES)
        db.session.add_all(TipoEventoBitacora(codigo=c, descripcion=c) for c in EVENTOS)
        db.session.commit()
    yield aplicacion


@pytest.fixture(autouse=True)
def limpiar_datos(request: pytest.FixtureRequest) -> Iterator[None]:
    """Vacía las tablas de cuentas antes de cada prueba que usa la base de datos."""
    if "app" not in request.fixturenames:
        yield
        return
    aplicacion = request.getfixturevalue("app")
    from plasea.modelos import Bitacora, SesionUsuario, TokenCuenta, Usuario, db

    with aplicacion.app_context():
        for modelo in (Bitacora, SesionUsuario, TokenCuenta, Usuario):
            db.session.execute(delete(modelo))
        db.session.commit()
    yield


@pytest.fixture()
def cliente(app: Any) -> Any:
    """Cliente HTTP de pruebas."""
    return app.test_client()


@pytest.fixture()
def correos(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """Captura los correos enviados en lugar de escribirlos en consola."""
    enviados: list[dict[str, str]] = []

    def capturar(destinatario: str, asunto: str, cuerpo: str) -> None:
        enviados.append({"para": destinatario, "asunto": asunto, "cuerpo": cuerpo})

    monkeypatch.setattr("plasea.servicios.enlaces_cuenta.enviar_correo", capturar)
    return enviados


def token_del_correo(correo: dict[str, str]) -> str:
    """Extrae el token del enlace incluido en un correo capturado."""
    coincidencia = re.search(
        r"/(?:activar-cuenta|restablecer-contrasena)/(\S+)", correo["cuerpo"]
    )
    assert coincidencia, "El correo no contiene un enlace"
    return coincidencia.group(1)


@pytest.fixture()
def crear_usuario(app: Any) -> Any:
    """Fábrica de usuarios de prueba (por defecto activos)."""
    from werkzeug.security import generate_password_hash

    from plasea.modelos import Rol, Usuario, db

    def _crear(
        correo: str,
        rol: str = "profesor",
        estado: str = "activa",
        nombre: str = "Usuario de Prueba",
        contrasena: str | None = CONTRASENA_PRUEBA,
    ) -> int:
        with app.app_context():
            rol_obj = db.session.scalar(db.select(Rol).where(Rol.codigo == rol))
            usuario = Usuario(
                nombre_completo=nombre,
                correo=correo,
                rol_id=rol_obj.id,
                estado_cuenta=estado,
                contrasena_hash=(
                    generate_password_hash(contrasena) if contrasena else None
                ),
                intentos_fallidos=0,
            )
            db.session.add(usuario)
            db.session.commit()
            return usuario.id

    return _crear


def iniciar(cliente: Any, correo: str, contrasena: str = CONTRASENA_PRUEBA) -> Any:
    """Inicia sesión con el cliente de pruebas."""
    return cliente.post(
        "/iniciar-sesion", data={"correo": correo, "contrasena": contrasena}
    )
