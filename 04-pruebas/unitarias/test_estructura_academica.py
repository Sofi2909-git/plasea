"""Pruebas unitarias de reglas de E2 sin base de datos (RF-15 a RF-17, RF-19, RF-20)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest

from plasea.servicios.calendario import calcular_sesiones, horas_totales
from plasea.servicios.comunes import ErrorNegocio
from plasea.servicios.cursos import validar_bloque
from plasea.servicios.periodos import DatosCorte, semanas_calendario, validar_cortes
from plasea.servicios.umbrales import DatosUmbrales, validar_umbrales

LUNES = dt.date(2026, 8, 3)
FIN_16_SEMANAS = LUNES + dt.timedelta(days=111)
H = dt.time


# --- RF-19 ---------------------------------------------------------------------
def test_rf19_dos_sesiones_de_2_horas_en_16_semanas_suman_64_horas():
    bloques = [(1, H(7), H(9)), (3, H(7), H(9))]
    sesiones = calcular_sesiones(bloques, LUNES, FIN_16_SEMANAS, [])
    assert len(sesiones) == 32
    assert horas_totales(sesiones) == 64


def test_rf19_la_sesion_que_cae_en_festivo_se_omite():
    bloques = [(1, H(7), H(9)), (3, H(7), H(9))]
    festivo = LUNES + dt.timedelta(weeks=2)  # un lunes
    sesiones = calcular_sesiones(bloques, LUNES, FIN_16_SEMANAS, [festivo])
    assert len(sesiones) == 31
    assert horas_totales(sesiones) == 62
    assert festivo not in {s.fecha for s in sesiones}


def test_rf19_sin_bloques_no_hay_sesiones():
    assert calcular_sesiones([], LUNES, FIN_16_SEMANAS, []) == []


def test_rf19_sesiones_en_orden_cronologico():
    bloques = [(3, H(14), H(17)), (1, H(7), H(8))]
    sesiones = calcular_sesiones(bloques, LUNES, LUNES + dt.timedelta(days=6), [])
    assert [(s.fecha.isoweekday(), s.duracion_horas) for s in sesiones] == [
        (1, 1),
        (3, 3),
    ]


# --- RF-15 ---------------------------------------------------------------------
@pytest.mark.parametrize("fin", [H(8), H(9), H(10)])
def test_rf15_bloques_de_1_2_o_3_horas_son_validos(fin):
    validar_bloque(1, H(7), fin, [])


@pytest.mark.parametrize("fin", [H(7, 30), H(11), H(7)])
def test_rf15_otras_duraciones_se_rechazan(fin):
    with pytest.raises(ErrorNegocio):
        validar_bloque(1, H(7), fin, [])


def test_rf15_no_se_aceptan_bloques_solapados_en_el_mismo_dia():
    existentes = [(1, H(7), H(9))]
    with pytest.raises(ErrorNegocio, match="solapa"):
        validar_bloque(1, H(8), H(10), existentes)
    validar_bloque(1, H(9), H(11), existentes)  # contiguo: válido
    validar_bloque(2, H(8), H(10), existentes)  # otro día: válido


# --- RF-16 ---------------------------------------------------------------------
def test_rf16_semanas_calendario():
    assert semanas_calendario(LUNES, FIN_16_SEMANAS) == 16
    assert semanas_calendario(LUNES, LUNES + dt.timedelta(days=108)) == 16
    assert semanas_calendario(LUNES, LUNES + dt.timedelta(days=112)) == 17


# --- RF-17 ---------------------------------------------------------------------
def _periodo():
    return SimpleNamespace(fecha_inicio=LUNES, fecha_fin=FIN_16_SEMANAS)


def _cortes(pesos=("30", "30", "40")):
    tramos = [
        (LUNES, LUNES + dt.timedelta(days=34)),
        (LUNES + dt.timedelta(days=35), LUNES + dt.timedelta(days=69)),
        (LUNES + dt.timedelta(days=70), FIN_16_SEMANAS),
    ]
    return [
        DatosCorte(
            numero,
            Decimal(peso),
            inicio,
            fin,
            fin + dt.timedelta(days=3),
            fin + dt.timedelta(days=7),
        )
        for numero, peso, (inicio, fin) in zip((1, 2, 3), pesos, tramos)
    ]


def test_rf17_cortes_validos():
    validar_cortes(_periodo(), _cortes())


def test_rf17_los_pesos_deben_sumar_100():
    with pytest.raises(ErrorNegocio, match="100"):
        validar_cortes(_periodo(), _cortes(("30", "30", "30")))


def test_rf17_fechas_fuera_del_periodo_se_rechazan():
    cortes = _cortes()
    cortes[2] = DatosCorte(
        3,
        Decimal("40"),
        cortes[2].fecha_inicio,
        FIN_16_SEMANAS + dt.timedelta(days=1),
        FIN_16_SEMANAS + dt.timedelta(days=4),
        FIN_16_SEMANAS + dt.timedelta(days=8),
    )
    with pytest.raises(ErrorNegocio, match="dentro del período"):
        validar_cortes(_periodo(), cortes)


def test_rf17_cortes_solapados_se_rechazan():
    cortes = _cortes()
    cortes[1] = DatosCorte(
        2,
        Decimal("30"),
        cortes[0].fecha_fin,
        cortes[1].fecha_fin,
        cortes[1].limite_carga,
        cortes[1].limite_correccion,
    )
    with pytest.raises(ErrorNegocio, match="después del fin"):
        validar_cortes(_periodo(), cortes)


def test_rf17_limite_de_correccion_posterior_al_de_carga():
    cortes = _cortes()
    c = cortes[0]
    cortes[0] = DatosCorte(
        1,
        c.peso_porcentaje,
        c.fecha_inicio,
        c.fecha_fin,
        c.limite_carga,
        c.limite_carga,
    )
    with pytest.raises(ErrorNegocio, match="corrección"):
        validar_cortes(_periodo(), cortes)


# --- RF-20 ---------------------------------------------------------------------
def _umbrales(**cambios):
    valores = {
        "nota_aprobacion": Decimal("3.0"),
        "limite_perdida_inasistencia": Decimal("30"),
        "umbral_amarillo_inasistencia": Decimal("20"),
        "nota_amarilla_minima": Decimal("3.0"),
        "nota_amarilla_maxima": Decimal("3.4"),
    }
    valores.update(cambios)
    return DatosUmbrales(**valores)


def test_rf20_valores_por_defecto_validos():
    datos = validar_umbrales(_umbrales())
    assert datos.limite_perdida_inasistencia == Decimal("30.00")


@pytest.mark.parametrize(
    "cambios",
    [
        {"nota_aprobacion": Decimal("5.5")},
        {"nota_aprobacion": Decimal("3.05")},
        {"umbral_amarillo_inasistencia": Decimal("35")},
        {"limite_perdida_inasistencia": Decimal("101")},
        {
            "nota_amarilla_minima": Decimal("3.5"),
            "nota_amarilla_maxima": Decimal("3.4"),
        },
    ],
)
def test_rf20_valores_incoherentes_se_rechazan(cambios):
    with pytest.raises(ErrorNegocio):
        validar_umbrales(_umbrales(**cambios))


# --- Formato colombiano en la interfaz ------------------------------------------
@pytest.mark.parametrize(
    ("valor", "esperado"),
    [(Decimal("30.00"), "30"), (Decimal("30.50"), "30,5"), (Decimal("20.25"), "20,25")],
)
def test_porcentaje_con_coma_y_sin_ceros_sobrantes(valor, esperado):
    from plasea.web_comun import formato_porcentaje

    assert formato_porcentaje(valor) == esperado
