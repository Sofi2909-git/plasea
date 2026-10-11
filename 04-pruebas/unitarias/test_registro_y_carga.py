"""Pruebas unitarias sin base de datos de RF-24, RF-26, RF-28 y RF-29."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest

from plasea.servicios import importacion_csv as carga
from plasea.servicios import registro_academico as registro
from plasea.servicios.comunes import ErrorNegocio

HOY = dt.date(2026, 10, 10)


def _corte(
    numero=2, inicio=dt.date(2026, 9, 7), fin=dt.date(2026, 10, 11), cerrado=None
):
    return SimpleNamespace(
        id=numero,
        numero=numero,
        fecha_inicio=inicio,
        fecha_fin=fin,
        limite_carga=fin + dt.timedelta(days=3),
        limite_correccion=fin + dt.timedelta(days=7),
        cerrado_en=cerrado,
    )


# --- RF-29: nota con un decimal entre 1,0 y 5,0 --------------------------------
@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("3,5", Decimal("3.5")),
        ("3.5", Decimal("3.5")),
        ("4", Decimal("4.0")),
        ("1,0", Decimal("1.0")),
        ("5", Decimal("5.0")),
        (" 2,9 ", Decimal("2.9")),
        ("", None),
        (None, None),
    ],
)
def test_rf29_notas_validas(texto, esperado):
    assert registro.interpretar_nota(texto) == esperado


@pytest.mark.parametrize(
    ("texto", "mensaje"),
    [
        ("5,5", "entre 1,0 y 5,0"),
        ("0,9", "entre 1,0 y 5,0"),
        ("3,45", "un solo decimal"),
        ("tres", "Escriba un número"),
        ("-3", "Escriba un número"),
        ("3,", "Escriba un número"),
    ],
)
def test_rf29_notas_invalidas(texto, mensaje):
    with pytest.raises(ErrorNegocio, match=mensaje):
        registro.interpretar_nota(texto)


# --- RF-26: estado de cada corte --------------------------------------------------
def test_rf26_estado_pendiente_enviado_y_cerrado():
    corte = _corte()
    assert registro.estado_del_corte(corte, None, HOY) == "pendiente"
    enviado = SimpleNamespace(estado="enviado")
    assert registro.estado_del_corte(corte, enviado, HOY) == "enviado"
    cerrado = _corte(cerrado=dt.datetime(2026, 10, 12, 8, 0))
    assert registro.estado_del_corte(cerrado, enviado, HOY) == "cerrado"


def test_rf26_rf37_limite_de_correccion_vencido_se_ve_cerrado():
    corte = _corte(inicio=dt.date(2026, 8, 3), fin=dt.date(2026, 9, 6))
    assert registro.estado_del_corte(corte, None, HOY) == "cerrado"


# --- RF-28 y RF-29: plazo de carga ------------------------------------------------
def test_rf29_plazo_de_carga():
    corte = _corte()
    assert registro.motivo_bloqueo_carga(corte, "pendiente", HOY) is None
    assert "inicia" in registro.motivo_bloqueo_carga(
        _corte(3, dt.date(2026, 10, 12), dt.date(2026, 11, 22)), "pendiente", HOY
    )
    vencido = _corte(inicio=dt.date(2026, 8, 31), fin=dt.date(2026, 10, 4))
    assert "Venció" in registro.motivo_bloqueo_carga(vencido, "pendiente", HOY)
    assert "ya se envió" in registro.motivo_bloqueo_carga(corte, "enviado", HOY)
    assert "cerrado" in registro.motivo_bloqueo_carga(corte, "cerrado", HOY)


def test_rf28_solo_sesiones_dictadas_dentro_de_un_corte():
    corte = _corte()
    pasada = SimpleNamespace(fecha=dt.date(2026, 10, 5))
    futura = SimpleNamespace(fecha=dt.date(2026, 10, 14))
    assert registro.motivo_bloqueo_asistencia(pasada, corte, "pendiente", HOY) is None
    assert "no se ha dictado" in registro.motivo_bloqueo_asistencia(
        futura, corte, "pendiente", HOY
    )
    assert "ningún corte" in registro.motivo_bloqueo_asistencia(pasada, None, None, HOY)


def test_rf28_corte_de_una_fecha():
    cortes = [
        _corte(1, dt.date(2026, 8, 3), dt.date(2026, 9, 6)),
        _corte(2, dt.date(2026, 9, 7), dt.date(2026, 10, 11)),
    ]
    assert registro.corte_de_fecha(cortes, dt.date(2026, 9, 6)).numero == 1
    assert registro.corte_de_fecha(cortes, dt.date(2026, 9, 7)).numero == 2
    assert registro.corte_de_fecha(cortes, dt.date(2026, 12, 1)) is None


# --- RF-24: lectura del CSV -------------------------------------------------------
ENCABEZADO = (
    "codigo;nombres;correo;periodo_ingreso;periodo;asignatura;curso;semestre_cursado"
)


def test_rf24_plantilla_con_bom_y_todas_las_columnas():
    plantilla = carga.generar_plantilla()
    assert plantilla.startswith("﻿".encode("utf-8"))
    texto = plantilla.decode("utf-8-sig")
    assert texto.splitlines()[0] == ENCABEZADO


def test_rf24_acepta_coma_utf8_con_bom_y_windows_1252():
    con_coma = (
        "﻿" + ENCABEZADO.replace(";", ",") + "\r\n1,Ana Peña,a@b.co,2026-1,,,,\r\n"
    )
    filas = carga.leer_filas(carga.decodificar(con_coma.encode("utf-8")))
    assert filas == [
        (
            2,
            {
                **{c: "" for c in carga.COLUMNAS},
                "codigo": "1",
                "nombres": "Ana Peña",
                "correo": "a@b.co",
                "periodo_ingreso": "2026-1",
            },
        )
    ]
    excel = (ENCABEZADO + "\r\n1;José Núñez;j@b.co;2026-1;;;;\r\n").encode("cp1252")
    assert carga.leer_filas(carga.decodificar(excel))[0][1]["nombres"] == "José Núñez"


def test_rf24_encabezado_incompleto_vacio_o_grande():
    with pytest.raises(ErrorNegocio, match="Faltan columnas"):
        carga.leer_filas("codigo;nombres\n1;Ana\n")
    with pytest.raises(ErrorNegocio, match="vacío"):
        carga.decodificar(b"   ")
    with pytest.raises(ErrorNegocio, match="5 MB"):
        carga.decodificar(b"x" * (carga.TAMANO_MAXIMO_BYTES + 1))
    with pytest.raises(ErrorNegocio, match="no tiene filas"):
        carga.leer_filas(ENCABEZADO + "\n;;;;;;;\n")
