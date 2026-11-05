"""Pruebas unitarias de las reglas puras de RF-64 y RF-66 (sin base de datos)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from plasea.servicios import calculos, estadistica_profesor, perdida_reiterada
from plasea.servicios.calculos import ESTADO_AMARILLA, ESTADO_ROJA


class UmbralesPrueba:
    nota_aprobacion = Decimal("3.0")
    limite_perdida_inasistencia = Decimal("30")
    umbral_amarillo_inasistencia = Decimal("20")
    nota_amarilla_minima = Decimal("3.0")
    nota_amarilla_maxima = Decimal("3.4")


@pytest.mark.parametrize(
    "nota, inasistencia, esperado",
    [
        (True, True, "ambos"),
        (True, False, "nota"),
        (False, True, "inasistencia"),
        (False, False, None),
    ],
)
def test_rf64_motivo_de(nota, inasistencia, esperado):
    assert perdida_reiterada.motivo_de(nota, inasistencia) == esperado


def test_rf64_rojo_en_cortes_1_y_2_se_marca_con_motivo_de_cada_corte():
    filas = [(1, 1, True, False, True), (1, 2, False, True, False)]
    c1, c2 = perdida_reiterada.cortes_en_rojo(filas)
    assert (c1.motivo, c1.definitivo) == ("nota", True)
    assert (c2.motivo, c2.definitivo) == ("inasistencia", False)


def test_rf64_rojo_en_un_solo_corte_no_se_marca():
    assert perdida_reiterada.cortes_en_rojo([(1, 1, True, False, True)]) is None
    assert perdida_reiterada.cortes_en_rojo([(1, 2, True, True, True)]) is None


def test_rf64_el_corte_3_no_cuenta():
    filas = [(1, 1, True, False, True), (1, 3, True, False, True)]
    assert perdida_reiterada.cortes_en_rojo(filas) is None


@pytest.mark.parametrize(
    "acumulada, ritmo, esperado",
    [
        (Decimal("30.01"), None, ESTADO_ROJA),
        (Decimal("30"), None, ESTADO_AMARILLA),
        (Decimal("20"), None, ESTADO_AMARILLA),
        (Decimal("5"), Decimal("20"), ESTADO_AMARILLA),
        (Decimal("5"), Decimal("19.9"), estadistica_profesor.ESTADO_SIN_NOTA),
        (None, None, estadistica_profesor.ESTADO_SIN_NOTA),
    ],
)
def test_rf66_sin_nota_se_evalua_solo_por_inasistencia(acumulada, ritmo, esperado):
    estado = estadistica_profesor.estado_solo_inasistencia(
        UmbralesPrueba(), acumulada, ritmo
    )
    assert estado == esperado


def test_rf66_orden_de_estados_pone_rojo_primero_y_verde_al_final():
    orden = estadistica_profesor.ORDEN_ESTADO
    assert orden[calculos.ESTADO_ROJA] < orden[calculos.ESTADO_AMARILLA]
    assert orden[calculos.ESTADO_AMARILLA] < orden["sin_nota"]
    assert orden["sin_nota"] < orden[calculos.ESTADO_VERDE]
