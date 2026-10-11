"""Pruebas unitarias de la política de contraseñas (RF-07 y RF-09)."""

from __future__ import annotations

import pytest

from plasea.servicios.comunes import ErrorNegocio
from plasea.servicios.contrasenas import validar_politica, verificar


@pytest.mark.parametrize("valida", ["Clave123", "ABCDEFG1", "Ñandú2026x"])
def test_contrasenas_validas(valida):
    validar_politica(valida, valida)


@pytest.mark.parametrize(
    "invalida",
    ["Clave12", "clave1234", "CLAVESINNUMERO", "A1" + "x" * 127],
)
def test_contrasenas_invalidas(invalida):
    with pytest.raises(ErrorNegocio):
        validar_politica(invalida, invalida)


def test_confirmacion_distinta():
    with pytest.raises(ErrorNegocio, match="no coinciden"):
        validar_politica("Clave123", "Clave124")


def test_verificar_sin_hash_es_falso():
    assert verificar("Clave123", None) is False
