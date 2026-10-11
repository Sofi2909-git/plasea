"""Pruebas unitarias de RF-47, RF-50, RF-51, RF-53 y RF-58 (sin base de datos)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest

from plasea.servicios import calculos
from plasea.servicios import continuidad as c
from plasea.servicios.analitica import configuracion_del_periodo, resultado_final
from plasea.servicios.exportacion import generar_csv, neutralizar

D = Decimal
UMBRALES = SimpleNamespace(
    nota_aprobacion=D("3.0"), limite_perdida_inasistencia=D("30")
)


# --- RF-50 ---------------------------------------------------------------------
def test_rf50_indice_ejemplo_9_2():
    indice = c.indice_no_continuidad(30, 350, 20, 5)
    assert calculos.redondear(indice, 1) == D("9.2")
    assert c.indice_no_continuidad(0, 5, 3, 2) is None  # base 0


# --- RF-47 ---------------------------------------------------------------------
@pytest.mark.parametrize(
    ("acumulada", "inasistencia", "esperado"),
    [
        (D("3.0"), D("10"), ("aprobada", None)),  # 3,0 exacto aprueba
        (D("2.94"), D("10"), ("perdida", "nota")),  # 2,94 no se redondea
        (D("4.0"), D("30.01"), ("perdida", "inasistencia")),
        (D("4.0"), D("30"), ("aprobada", None)),  # 30 % exacto no pierde
        (D("2.0"), D("40"), ("perdida", "ambos")),
        (None, D("0"), ("perdida", "nota")),  # sin notas
    ],
)
def test_rf47_resultado_y_motivo(acumulada, inasistencia, esperado):
    assert resultado_final(acumulada, inasistencia, UMBRALES) == esperado


def test_rf47_usa_umbrales_vigentes_al_terminar_el_periodo():
    viejo = SimpleNamespace(vigente_desde=dt.datetime(2025, 1, 1), nota=D("3.0"))
    nuevo = SimpleNamespace(vigente_desde=dt.datetime(2026, 3, 1), nota=D("3.5"))
    periodo = SimpleNamespace(fecha_fin=dt.date(2025, 6, 30))
    abierto = [SimpleNamespace(cerrado_en=None)]
    assert configuracion_del_periodo(periodo, abierto, [viejo, nuevo]) is viejo
    periodo_nuevo = SimpleNamespace(fecha_fin=dt.date(2026, 6, 30))
    assert configuracion_del_periodo(periodo_nuevo, abierto, [viejo, nuevo]) is nuevo
    # Cerrado antes del cambio: conserva los umbrales del cierre.
    cerrados = [SimpleNamespace(cerrado_en=dt.datetime(2026, 2, 1))]
    assert configuracion_del_periodo(periodo_nuevo, cerrados, [viejo, nuevo]) is viejo
    # Ninguna vigente aún: la más antigua.
    previo = SimpleNamespace(fecha_fin=dt.date(2024, 6, 30))
    assert configuracion_del_periodo(previo, abierto, [viejo, nuevo]) is viejo


# --- RF-51 y RF-53 -------------------------------------------------------------
def _fila(n, clase, semestre, cohorte="2024-1", causa=None):
    return c.FilaContinuidad(
        n,
        n,
        f"C{n}",
        f"Estudiante {n}",
        "Ingeniería de Sistemas",
        cohorte,
        semestre,
        clase,
        causa,
        causa.title() if causa else None,
    )


FILAS = [
    _fila(1, c.CONTINUA, 1),
    _fila(2, c.NO_CONTINUA, 1, causa="economica"),
    _fila(3, c.NO_CONTINUA, 2),
    _fila(4, c.GRADUADO, 10, "2021-1"),
    _fila(5, c.APLAZADO, 2),
    _fila(6, c.CONTINUA, 2, "2023-2"),
]


def test_rf51_grupos_suman_lo_mismo_que_el_total():
    total = c.indicador("total", FILAS)
    for grupos in (
        c.por_grupo(FILAS, lambda f: f.semestre),
        c.por_grupo(FILAS, lambda f: f.cohorte),
    ):
        assert sum(g.inscritos for g in grupos) == total.inscritos
        assert sum(g.no_continuan for g in grupos) == total.no_continuan
        assert sum(g.base for g in grupos) == total.base
    assert total.indice == D("50")  # 2 / (6 - 1 - 1)


def test_rf52_rf53_filtros_y_sin_causa():
    assert [f.codigo for f in c.no_continuaron(FILAS)] == ["C2", "C3"]
    assert [f.codigo for f in c.no_continuaron(FILAS, causa=c.SIN_CAUSA)] == ["C3"]
    assert [f.codigo for f in c.no_continuaron(FILAS, causa="economica")] == ["C2"]
    assert [f.codigo for f in c.no_continuaron(FILAS, semestre=2)] == ["C3"]
    assert dict(c.por_causa(FILAS)) == {"Economica": 1, "Sin causa": 1}


# --- RF-58 ---------------------------------------------------------------------
@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("=HIPERVINCULO(1)", "'=HIPERVINCULO(1)"),
        ("+57 300", "'+57 300"),
        ("-1+1", "'-1+1"),
        ("@SUMA", "'@SUMA"),
        ("\tx", "'\tx"),
        ("Ana Rojas", "Ana Rojas"),
        (D("3.50"), "3,50"),
        (True, "Sí"),
        (None, ""),
    ],
)
def test_rf58_neutraliza_formulas(valor, esperado):
    assert neutralizar(valor) == esperado


def test_rf58_csv_con_bom_y_punto_y_coma():
    contenido = generar_csv(["A", "B"], [["=1", D("2.5")]])
    assert contenido.startswith("﻿".encode("utf-8"))
    assert contenido.decode("utf-8-sig") == "A;B\r\n'=1;2,5\r\n"
