"""Pruebas de seguridad de la épica E1 (RNF-01, OWASP Top 10 básico)."""

from __future__ import annotations

from conftest import iniciar

PROFE = "profe1@plasea.edu.co"


def test_csrf_rechaza_formularios_sin_token(app, crear_usuario):
    crear_usuario(PROFE)
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        cliente = app.test_client()
        respuesta = iniciar(cliente, PROFE)
        assert respuesta.status_code == 400
        assert cliente.post("/cerrar-sesion").status_code == 400
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_no_redirige_a_sitios_externos(cliente, crear_usuario):
    crear_usuario(PROFE)
    for destino in (
        "//sitio-externo.com",
        "https://sitio-externo.com",
        "/\\sitio-externo.com",
    ):
        respuesta = cliente.post(
            f"/iniciar-sesion?siguiente={destino}",
            data={"correo": PROFE, "contrasena": "Clave123*"},
        )
        assert respuesta.headers["Location"].endswith("/inicio")
        cliente.post("/cerrar-sesion")


def test_cabeceras_de_seguridad(cliente):
    respuesta = cliente.get("/iniciar-sesion")
    assert "default-src 'self'" in respuesta.headers["Content-Security-Policy"]
    assert respuesta.headers["X-Frame-Options"] == "DENY"
    assert respuesta.headers["X-Content-Type-Options"] == "nosniff"
    assert respuesta.headers["Referrer-Policy"] == "no-referrer"


def test_cookie_de_sesion_httponly_y_samesite(cliente, crear_usuario):
    crear_usuario(PROFE)
    respuesta = iniciar(cliente, PROFE)
    cookie = respuesta.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_la_cookie_no_contiene_el_hash_guardado(app, cliente, crear_usuario):
    from sqlalchemy import select

    from plasea.modelos import SesionUsuario, db

    crear_usuario(PROFE)
    iniciar(cliente, PROFE)
    with cliente.session_transaction() as sesion_web:
        identificador = sesion_web["id_sesion"]
    with app.app_context():
        guardado = db.session.scalar(select(SesionUsuario.token_hash))
    assert identificador != guardado and len(guardado) == 64
