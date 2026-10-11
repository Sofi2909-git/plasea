"""Pruebas funcionales de la épica E1 (RF-01 a RF-12).

Derivadas de los criterios de aceptación de REQUERIMIENTOS.txt. Requieren
URL_BASE_DATOS_PRUEBAS (ver 04-pruebas/conftest.py).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from conftest import CONTRASENA_PRUEBA, iniciar, token_del_correo
from sqlalchemy import func, select

from plasea.modelos import (
    Bitacora,
    SesionUsuario,
    TipoEventoBitacora,
    TokenCuenta,
    Usuario,
    db,
)
from plasea.servicios.comunes import ahora

ADMIN = "admin@plasea.edu.co"
PROFE = "profe1@plasea.edu.co"


def _usuario(app: Any, correo: str) -> Usuario:
    with app.app_context():
        usuario = db.session.scalar(select(Usuario).where(Usuario.correo == correo))
        db.session.expunge(usuario)
        return usuario


def _eventos(app: Any, codigo: str) -> int:
    with app.app_context():
        return db.session.scalar(
            select(func.count(Bitacora.id))
            .join(TipoEventoBitacora, TipoEventoBitacora.id == Bitacora.tipo_evento_id)
            .where(TipoEventoBitacora.codigo == codigo)
        )


# --- RF-01 -----------------------------------------------------------------
def test_rf01_inicio_exitoso_lleva_a_la_pagina_del_rol(app, cliente, crear_usuario):
    crear_usuario(PROFE)
    respuesta = iniciar(cliente, PROFE)
    assert respuesta.status_code == 302
    assert respuesta.headers["Location"].endswith("/inicio")
    pagina = cliente.get("/inicio")
    assert pagina.status_code == 200
    assert "Profesor" in pagina.get_data(as_text=True)
    assert _eventos(app, "inicio_sesion") == 1


def test_rf01_mensaje_generico_no_revela_el_dato_que_fallo(app, cliente, crear_usuario):
    crear_usuario(PROFE)
    clave_mala = iniciar(cliente, PROFE, "Incorrecta1")
    correo_malo = iniciar(cliente, "noexiste@plasea.edu.co")
    assert clave_mala.status_code == correo_malo.status_code == 401
    texto = "Correo o contraseña incorrectos."
    assert texto in clave_mala.get_data(as_text=True)
    assert texto in correo_malo.get_data(as_text=True)


def test_rf01_correo_sin_distinguir_mayusculas(cliente, crear_usuario):
    crear_usuario(PROFE)
    assert iniciar(cliente, "  PROFE1@Plasea.edu.co ").status_code == 302


def test_rf01_cuenta_inactiva_o_bloqueada_no_inicia(cliente, crear_usuario):
    crear_usuario("inactiva@plasea.edu.co", estado="inactiva")
    crear_usuario("bloqueada@plasea.edu.co", estado="bloqueada")
    for correo in ("inactiva@plasea.edu.co", "bloqueada@plasea.edu.co"):
        respuesta = iniciar(cliente, correo)
        assert respuesta.status_code == 401
        assert "no está habilitada" in respuesta.get_data(as_text=True)


# --- RF-02 -----------------------------------------------------------------
def test_rf02_profesor_recibe_403_en_funcion_de_administracion(cliente, crear_usuario):
    crear_usuario(PROFE)
    iniciar(cliente, PROFE)
    respuesta = cliente.get("/cuentas")
    assert respuesta.status_code == 403
    assert "Acceso denegado" in respuesta.get_data(as_text=True)
    assert cliente.post("/cuentas/1/estado/desactivar").status_code == 403


def test_rf02_sin_sesion_redirige_al_inicio_de_sesion(cliente):
    respuesta = cliente.get("/cuentas")
    assert respuesta.status_code == 302
    assert "/iniciar-sesion" in respuesta.headers["Location"]


def test_rf02_menu_solo_muestra_opciones_permitidas(cliente, crear_usuario):
    crear_usuario(PROFE)
    crear_usuario(ADMIN, rol="administrador_sistema")
    iniciar(cliente, PROFE)
    assert "Cuentas de usuario" not in cliente.get("/inicio").get_data(as_text=True)
    cliente.post("/cerrar-sesion")
    iniciar(cliente, ADMIN)
    assert "Cuentas de usuario" in cliente.get("/inicio").get_data(as_text=True)


# --- RF-03 -----------------------------------------------------------------
def test_rf03_cerrar_sesion_invalida_la_sesion_y_evita_cache(
    app, cliente, crear_usuario
):
    crear_usuario(PROFE)
    iniciar(cliente, PROFE)
    pagina = cliente.get("/inicio")
    assert "no-store" in pagina.headers["Cache-Control"]
    with cliente.session_transaction() as sesion_web:
        cookie_anterior = dict(sesion_web)
    assert cliente.post("/cerrar-sesion").status_code == 302
    assert cliente.get("/inicio").status_code == 302
    # Reutilizar la cookie anterior no recupera la sesión.
    with cliente.session_transaction() as sesion_web:
        sesion_web.update(cookie_anterior)
    assert cliente.get("/inicio").status_code == 302
    with app.app_context():
        sesion = db.session.scalar(select(SesionUsuario))
        assert sesion.motivo_cierre == "cierre_voluntario"
    assert _eventos(app, "cierre_sesion") == 1


# --- RF-04 -----------------------------------------------------------------
def test_rf04_cierre_por_inactividad(app, cliente, crear_usuario):
    crear_usuario(PROFE)
    iniciar(cliente, PROFE)
    with app.app_context():
        sesion = db.session.scalar(select(SesionUsuario))
        sesion.ultima_actividad_en = ahora() - dt.timedelta(minutes=31)
        db.session.commit()
    respuesta = cliente.get("/inicio")
    assert respuesta.status_code == 302
    assert "/iniciar-sesion" in respuesta.headers["Location"]
    with app.app_context():
        assert db.session.scalar(select(SesionUsuario)).motivo_cierre == "inactividad"


def test_rf04_actividad_reciente_mantiene_la_sesion(app, cliente, crear_usuario):
    crear_usuario(PROFE)
    iniciar(cliente, PROFE)
    with app.app_context():
        sesion = db.session.scalar(select(SesionUsuario))
        sesion.ultima_actividad_en = ahora() - dt.timedelta(minutes=29)
        db.session.commit()
    assert cliente.get("/inicio").status_code == 200


# --- RF-05 -----------------------------------------------------------------
def test_rf05_bloqueo_tras_tres_intentos_y_tiempo_restante(app, cliente, crear_usuario):
    crear_usuario(PROFE)
    iniciar(cliente, PROFE, "Mala1111")
    iniciar(cliente, PROFE, "Mala1111")
    tercero = iniciar(cliente, PROFE, "Mala1111").get_data(as_text=True)
    assert "bloqueada temporalmente" in tercero and "15 minutos" in tercero
    # Durante el bloqueo, ni la contraseña correcta permite entrar.
    assert iniciar(cliente, PROFE).status_code == 401
    # Al vencer el bloqueo el contador se reinicia y se puede entrar.
    with app.app_context():
        usuario = db.session.scalar(select(Usuario).where(Usuario.correo == PROFE))
        usuario.bloqueo_hasta = ahora() - dt.timedelta(seconds=1)
        db.session.commit()
    assert iniciar(cliente, PROFE).status_code == 302
    assert _usuario(app, PROFE).intentos_fallidos == 0


def test_rf05_acceso_exitoso_reinicia_el_contador(app, cliente, crear_usuario):
    crear_usuario(PROFE)
    iniciar(cliente, PROFE, "Mala1111")
    iniciar(cliente, PROFE, "Mala1111")
    assert iniciar(cliente, PROFE).status_code == 302
    assert _usuario(app, PROFE).intentos_fallidos == 0


# --- RF-06 y RF-07 -----------------------------------------------------------
def test_rf06_respuesta_igual_exista_o_no_el_correo(
    app, cliente, crear_usuario, correos
):
    crear_usuario(PROFE)
    existe = cliente.post(
        "/recuperar-contrasena", data={"correo": PROFE}, follow_redirects=True
    )
    no_existe = cliente.post(
        "/recuperar-contrasena",
        data={"correo": "otro@plasea.edu.co"},
        follow_redirects=True,
    )
    assert existe.status_code == no_existe.status_code == 200
    assert "Si el correo corresponde" in existe.get_data(as_text=True)
    assert "Si el correo corresponde" in no_existe.get_data(as_text=True)
    assert len(correos) == 1 and correos[0]["para"] == PROFE
    with app.app_context():
        enlace = db.session.scalar(select(TokenCuenta))
        assert enlace.proposito == "restablecimiento"
        assert enlace.vence_en - enlace.creado_en == dt.timedelta(minutes=60)
        # Solo se guarda el hash, nunca el token.
        assert token_del_correo(correos[0]) != enlace.token_hash


def test_rf07_restablecer_contrasena_completo(app, cliente, crear_usuario, correos):
    crear_usuario(PROFE)
    otro_cliente = app.test_client()
    iniciar(otro_cliente, PROFE)
    cliente.post("/recuperar-contrasena", data={"correo": PROFE})
    token = token_del_correo(correos[0])
    ruta = f"/restablecer-contrasena/{token}"
    assert cliente.get(ruta).status_code == 200
    debil = cliente.post(ruta, data={"contrasena": "corta", "confirmacion": "corta"})
    assert "mínimo 8 caracteres" in debil.get_data(as_text=True)
    ok = cliente.post(
        ruta, data={"contrasena": "NuevaClave9", "confirmacion": "NuevaClave9"}
    )
    assert ok.status_code == 302
    # Sesiones anteriores invalidadas.
    assert otro_cliente.get("/inicio").status_code == 302
    # El enlace es de un solo uso.
    assert cliente.get(ruta).status_code == 410
    assert iniciar(cliente, PROFE).status_code == 401
    assert iniciar(cliente, PROFE, "NuevaClave9").status_code == 302


def test_rf07_enlace_vencido_se_rechaza(app, cliente, crear_usuario, correos):
    crear_usuario(PROFE)
    cliente.post("/recuperar-contrasena", data={"correo": PROFE})
    token = token_del_correo(correos[0])
    with app.app_context():
        enlace = db.session.scalar(select(TokenCuenta))
        enlace.creado_en = ahora() - dt.timedelta(minutes=120)
        enlace.vence_en = ahora() - dt.timedelta(minutes=60)
        db.session.commit()
    assert cliente.get(f"/restablecer-contrasena/{token}").status_code == 410


def test_rf07_enlace_nuevo_reemplaza_el_anterior(cliente, crear_usuario, correos):
    crear_usuario(PROFE)
    cliente.post("/recuperar-contrasena", data={"correo": PROFE})
    cliente.post("/recuperar-contrasena", data={"correo": PROFE})
    primero, segundo = (token_del_correo(c) for c in correos)
    assert cliente.get(f"/restablecer-contrasena/{primero}").status_code == 410
    assert cliente.get(f"/restablecer-contrasena/{segundo}").status_code == 200


# --- RF-08 y RF-09 -----------------------------------------------------------
def test_rf08_rf09_crear_y_activar_cuenta(app, cliente, crear_usuario, correos):
    crear_usuario(ADMIN, rol="administrador_sistema")
    iniciar(cliente, ADMIN)
    respuesta = cliente.post(
        "/cuentas/nueva",
        data={
            "nombre_completo": "Nueva Docente",
            "correo": "Nueva@Plasea.edu.co",
            "rol": "profesor",
        },
    )
    assert respuesta.status_code == 302
    nueva = _usuario(app, "nueva@plasea.edu.co")
    assert nueva.estado_cuenta == "pendiente_activacion"
    assert nueva.contrasena_hash is None
    assert correos[0]["para"] == "nueva@plasea.edu.co"
    cliente.post("/cerrar-sesion")

    token = token_del_correo(correos[0])
    ruta = f"/activar-cuenta/{token}"
    assert (
        cliente.post(
            ruta, data={"contrasena": "Docente123", "confirmacion": "Docente123"}
        ).status_code
        == 302
    )
    assert _usuario(app, "nueva@plasea.edu.co").estado_cuenta == "activa"
    assert cliente.get(ruta).status_code == 410
    assert iniciar(cliente, "nueva@plasea.edu.co", "Docente123").status_code == 302


def test_rf08_correo_unico_sin_distinguir_mayusculas(cliente, crear_usuario, correos):
    crear_usuario(ADMIN, rol="administrador_sistema")
    crear_usuario(PROFE)
    iniciar(cliente, ADMIN)
    respuesta = cliente.post(
        "/cuentas/nueva",
        data={
            "nombre_completo": "Duplicado",
            "correo": "PROFE1@plasea.edu.co",
            "rol": "profesor",
        },
    )
    assert "Ya existe una cuenta con ese correo." in respuesta.get_data(as_text=True)
    assert correos == []


def test_rf08_reenviar_activacion(cliente, crear_usuario, correos):
    crear_usuario(ADMIN, rol="administrador_sistema")
    pendiente = crear_usuario(
        "pendiente@plasea.edu.co", estado="pendiente_activacion", contrasena=None
    )
    iniciar(cliente, ADMIN)
    cliente.post(f"/cuentas/{pendiente}/reenviar-activacion")
    assert len(correos) == 1


# --- RF-10 -------------------------------------------------------------------
def test_rf10_modificar_cuenta_y_rol_aplica_en_siguiente_inicio(
    app, cliente, crear_usuario
):
    crear_usuario(ADMIN, rol="administrador_sistema")
    profe = crear_usuario(PROFE)
    cliente_profe = app.test_client()
    iniciar(cliente_profe, PROFE)
    iniciar(cliente, ADMIN)
    respuesta = cliente.post(
        f"/cuentas/{profe}/editar",
        data={
            "nombre_completo": "Profesora Editada",
            "correo": PROFE,
            "rol": "auditor_academico",
        },
    )
    assert respuesta.status_code == 302
    # La sesión abierta conserva el rol anterior.
    assert "Profesor" in cliente_profe.get("/inicio").get_data(as_text=True)
    cliente_profe.post("/cerrar-sesion")
    iniciar(cliente_profe, PROFE)
    assert "Auditor académico" in cliente_profe.get("/inicio").get_data(as_text=True)
    assert _usuario(app, PROFE).nombre_completo == "Profesora Editada"


def test_rf10_no_se_quita_el_rol_al_ultimo_administrador(app, cliente, crear_usuario):
    admin = crear_usuario(ADMIN, rol="administrador_sistema")
    iniciar(cliente, ADMIN)
    respuesta = cliente.post(
        f"/cuentas/{admin}/editar",
        data={"nombre_completo": "Admin", "correo": ADMIN, "rol": "profesor"},
    )
    assert "último administrador" in respuesta.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Usuario, admin).rol.codigo == "administrador_sistema"


# --- RF-11 -------------------------------------------------------------------
def test_rf11_desactivar_cierra_sesiones_e_impide_inicio(app, cliente, crear_usuario):
    crear_usuario(ADMIN, rol="administrador_sistema")
    profe = crear_usuario(PROFE)
    cliente_profe = app.test_client()
    iniciar(cliente_profe, PROFE)
    iniciar(cliente, ADMIN)
    cliente.post(f"/cuentas/{profe}/estado/desactivar")
    assert _usuario(app, PROFE).estado_cuenta == "inactiva"
    assert cliente_profe.get("/inicio").status_code == 302
    assert iniciar(cliente_profe, PROFE).status_code == 401
    cliente.post(f"/cuentas/{profe}/estado/activar")
    assert iniciar(cliente_profe, PROFE).status_code == 302


def test_rf11_bloquear_y_desbloquear(app, cliente, crear_usuario):
    crear_usuario(ADMIN, rol="administrador_sistema")
    profe = crear_usuario(PROFE)
    iniciar(cliente, ADMIN)
    cliente.post(f"/cuentas/{profe}/estado/bloquear")
    assert _usuario(app, PROFE).estado_cuenta == "bloqueada"
    cliente.post(f"/cuentas/{profe}/estado/desbloquear")
    assert _usuario(app, PROFE).estado_cuenta == "activa"


def test_rf11_desbloquear_levanta_bloqueo_temporal(app, cliente, crear_usuario):
    crear_usuario(ADMIN, rol="administrador_sistema")
    profe = crear_usuario(PROFE)
    for _ in range(3):
        iniciar(app.test_client(), PROFE, "Mala1111")
    iniciar(cliente, ADMIN)
    cliente.post(f"/cuentas/{profe}/estado/desbloquear")
    assert _usuario(app, PROFE).bloqueo_hasta is None
    assert iniciar(app.test_client(), PROFE).status_code == 302


def test_rf11_no_puede_desactivar_su_propia_cuenta(app, cliente, crear_usuario):
    admin = crear_usuario(ADMIN, rol="administrador_sistema")
    iniciar(cliente, ADMIN)
    respuesta = cliente.post(
        f"/cuentas/{admin}/estado/desactivar", follow_redirects=True
    )
    assert "propia cuenta" in respuesta.get_data(as_text=True)
    assert _usuario(app, ADMIN).estado_cuenta == "activa"


def test_rf11_cambios_quedan_en_bitacora(app, cliente, crear_usuario):
    crear_usuario(ADMIN, rol="administrador_sistema")
    profe = crear_usuario(PROFE)
    iniciar(cliente, ADMIN)
    cliente.post(f"/cuentas/{profe}/estado/bloquear")
    assert _eventos(app, "cambio_administrativo") == 1


# --- RF-12 -------------------------------------------------------------------
def test_rf12_filtros_y_busqueda_sin_mayusculas_ni_tildes(cliente, crear_usuario):
    crear_usuario(ADMIN, rol="administrador_sistema", nombre="Administración General")
    crear_usuario(PROFE, nombre="José Peñaranda Ávila")
    crear_usuario("auditor@plasea.edu.co", rol="auditor_academico", nombre="Lucía Mora")
    crear_usuario("inactivo@plasea.edu.co", estado="inactiva", nombre="Pedro Inactivo")
    iniciar(cliente, ADMIN)

    texto = cliente.get("/cuentas?q=JOSE").get_data(as_text=True)
    assert "José Peñaranda Ávila" in texto and "Lucía Mora" not in texto
    assert "José Peñaranda" in cliente.get("/cuentas?q=avila").get_data(as_text=True)
    assert "Lucía Mora" in cliente.get("/cuentas?q=LUCIA").get_data(as_text=True)

    por_rol = cliente.get("/cuentas?rol=auditor_academico").get_data(as_text=True)
    assert "Lucía Mora" in por_rol and "José Peñaranda" not in por_rol
    por_estado = cliente.get("/cuentas?estado=inactiva").get_data(as_text=True)
    assert "Pedro Inactivo" in por_estado and "Lucía Mora" not in por_estado
    vacio = cliente.get("/cuentas?q=%25").get_data(as_text=True)
    assert "No hay cuentas que coincidan" in vacio


def test_rf12_listado_200_cuentas_en_menos_de_2_segundos(app, cliente, crear_usuario):
    import time

    from werkzeug.security import generate_password_hash

    from plasea.modelos import Rol

    crear_usuario(ADMIN, rol="administrador_sistema")
    with app.app_context():
        rol_id = db.session.scalar(select(Rol.id).where(Rol.codigo == "profesor"))
        hash_comun = generate_password_hash(CONTRASENA_PRUEBA)
        db.session.add_all(
            Usuario(
                nombre_completo=f"Docente {numero:03d}",
                correo=f"docente{numero:03d}@plasea.edu.co",
                rol_id=rol_id,
                estado_cuenta="activa",
                contrasena_hash=hash_comun,
                intentos_fallidos=0,
            )
            for numero in range(199)
        )
        db.session.commit()
    iniciar(cliente, ADMIN)
    inicio = time.perf_counter()
    respuesta = cliente.get("/cuentas?q=docente")
    assert respuesta.status_code == 200
    assert time.perf_counter() - inicio < 2
    assert "199 cuentas" in respuesta.get_data(as_text=True)
