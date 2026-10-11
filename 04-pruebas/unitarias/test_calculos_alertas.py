"""Pruebas unitarias de RF-40 a RF-43 y de la regla de plazos RF-30 a RF-32.

Usan los ejemplos numéricos de REQUERIMIENTOS.txt y de la sección 5 de las
instrucciones del proyecto (3,1; 3,43; 12,5 % y 33,3 %).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest

from plasea.servicios import calculos
from plasea.servicios.correcciones import modo_segun_reglas

D = Decimal
UMBRALES = SimpleNamespace(
    nota_aprobacion=D("3.0"),
    limite_perdida_inasistencia=D("30"),
    umbral_amarillo_inasistencia=D("20"),
    nota_amarilla_minima=D("3.0"),
    nota_amarilla_maxima=D("3.4"),
)
PESOS = (D("30"), D("30"), D("40"))


# --- RF-40 ---------------------------------------------------------------------
def test_rf40_acumulada_final_3_1():
    assert calculos.nota_acumulada(zip((D("3.0"), D("2.0"), D("4.0")), PESOS)) == D(
        "3.1"
    )


def test_rf40_acumulada_parcial_y_sin_notas():
    assert calculos.nota_acumulada([(D("2.0"), D("30"))]) == D("0.6")
    assert calculos.nota_acumulada([(None, D("30"))]) is None


def test_rf40_sin_redondeo_3_exacto_aprueba_y_2_95_no():
    # 3,0 exacto: 3,0 3,0 3,0 → 3,0
    final = calculos.nota_acumulada(zip((D("3.0"),) * 3, PESOS))
    assert final == D("3.0") and final >= UMBRALES.nota_aprobacion
    # 2,9 2,9 3,0 = 0,87 + 0,87 + 1,2 = 2,94 (se mostraría 2,9 pero no aprueba)
    casi = calculos.nota_acumulada(zip((D("2.9"), D("2.9"), D("3.0")), PESOS))
    assert casi == D("2.94") and casi < UMBRALES.nota_aprobacion


# --- RF-41 ---------------------------------------------------------------------
def test_rf41_requerida_3_43_tras_corte_1_con_2_0():
    requerida = calculos.nota_requerida(D("3.0"), D("0.6"), D("70"))
    assert calculos.redondear(requerida) == D("3.43")


def test_rf41_perdida_y_aprobada_por_nota():
    perdida = calculos.evaluar_alerta(
        UMBRALES, [(D("1.0"), D("30")), (D("1.0"), D("30"))], D("40"), 0, 64, 40
    )
    assert perdida.nota_requerida > 5 and perdida.perdida_por_nota
    assert perdida.estado == "roja" and perdida.motivo == "nota"
    aprobada = calculos.evaluar_alerta(
        UMBRALES, [(D("5.0"), D("30")), (D("5.0"), D("30"))], D("40"), 0, 64, 40
    )
    assert aprobada.nota_requerida <= 1 and aprobada.aprobada_por_nota
    assert calculos.nota_requerida(D("3.0"), D("3.1"), D("0")) is None


# --- RF-42 ---------------------------------------------------------------------
def test_rf42_acumulada_12_5_y_ritmo_33_3():
    assert calculos.porcentaje(8, 64) == D("12.5")
    assert calculos.redondear(calculos.porcentaje(8, 24), 1) == D("33.3")
    assert calculos.porcentaje(3, 0) is None


# --- RF-43 ---------------------------------------------------------------------
def _alerta(nota=D("4.0"), ausentes=0, totales=64, dictadas=40):
    return calculos.evaluar_alerta(
        UMBRALES, [(nota, D("30"))], D("70"), ausentes, totales, dictadas
    )


@pytest.mark.parametrize(
    ("nota", "ausentes", "estado", "motivo"),
    [
        (D("2.9"), 0, "roja", "nota"),
        (D("3.0"), 0, "amarilla", "nota"),
        (D("3.4"), 0, "amarilla", "nota"),
        (D("3.5"), 0, "verde", None),
        (D("4.0"), 20, "roja", "inasistencia"),  # 31,25 % > 30 %
        (D("4.0"), 8, "amarilla", "inasistencia"),  # ritmo 20 %
        (D("2.0"), 20, "roja", "ambos"),
        (D("3.2"), 8, "amarilla", "ambos"),
    ],
)
def test_rf43_semaforo_y_motivo(nota, ausentes, estado, motivo):
    resultado = _alerta(nota, ausentes)
    assert resultado.estado == estado
    assert resultado.motivo == motivo


def test_rf43_ritmo_de_inasistencia_dispara_amarilla():
    # 8 h de 64 = 12,5 % acumulada, pero 8 de 24 dictadas = 33,3 % de ritmo.
    resultado = _alerta(D("4.0"), 8, 64, 24)
    assert resultado.estado == "amarilla" and resultado.motivo == "inasistencia"


def test_rf43_30_por_ciento_exacto_no_es_roja():
    assert _alerta(D("4.0"), 19, 64, 64).estado == "amarilla"  # 29,7 %
    assert _alerta(D("4.0"), 30, 100, 100).estado == "amarilla"  # 30 % exacto


def test_rf43_umbrales_vienen_de_la_configuracion():
    estrictos = SimpleNamespace(
        **{**vars(UMBRALES), "umbral_amarillo_inasistencia": D("10")}
    )
    resultado = calculos.evaluar_alerta(
        estrictos, [(D("4.0"), D("30"))], D("70"), 8, 64, 64
    )
    assert resultado.estado == "amarilla"  # 12,5 % ≥ 10 %


def test_rf43_sin_notas_no_concluye_por_nota():
    resultado = calculos.evaluar_alerta(UMBRALES, [(None, D("30"))], D("70"), 0, 64, 10)
    assert resultado.estado == "verde" and resultado.nota_requerida is None


# --- RF-30 a RF-32 y RF-38: modo de edición --------------------------------------
def _corte(cerrado=None):
    fin = dt.date(2026, 10, 11)
    return SimpleNamespace(
        numero=2,
        fecha_inicio=dt.date(2026, 9, 7),
        fecha_fin=fin,
        limite_carga=fin + dt.timedelta(days=3),
        limite_correccion=fin + dt.timedelta(days=7),
        cerrado_en=cerrado,
    )


@pytest.mark.parametrize(
    ("estado", "hoy", "reapertura", "modo"),
    [
        ("pendiente", dt.date(2026, 10, 12), False, "carga"),
        ("pendiente", dt.date(2026, 10, 15), False, "bloqueado"),  # venció la carga
        ("enviado", dt.date(2026, 10, 15), False, "correccion"),
        ("enviado", dt.date(2026, 10, 19), False, "bloqueado"),  # venció la corrección
        ("cerrado", dt.date(2026, 10, 16), False, "bloqueado"),
        ("cerrado", dt.date(2026, 10, 20), True, "reapertura"),
    ],
)
def test_rf32_modo_de_edicion(estado, hoy, reapertura, modo):
    assert modo_segun_reglas(_corte(), estado, reapertura, hoy)[0] == modo


def test_rf32_mensaje_al_rechazar_fuera_de_plazo():
    _modo, mensaje = modo_segun_reglas(
        _corte(), "cerrado", False, dt.date(2026, 10, 20)
    )
    assert "cerrado" in mensaje and "reabrir" in mensaje
