"""Tests de la agregacion en clases de activo.

Lo que se protege no es el mapeo entero clase por clase —eso cambia cuando
cambie el LTCMA— sino las fronteras que son convencion y que, si se mueven sin
querer, cambian la lectura de un portafolio sin que nadie lo note.
"""

from __future__ import annotations

import json

import pytest

from gbp.model.correlation import data_dir
from gbp.model.groups import (
    ALTERNATIVES,
    CASH,
    EQUITY,
    FIXED_INCOME,
    GROUP_ORDER,
    OTHER,
    group_of,
    group_summary,
    group_weights,
)


def test_las_clases_del_ltcma_se_clasifican_todas():
    """Ninguna sub-clase real debe caer en 'Otros', salvo la inflacion.

    'U.S. Inflation' esta en la tabla del LTCMA pero no es un activo invertible:
    es el indice contra el que se miden los demas.
    """
    payload = json.loads((data_dir() / "ltcma_usd.json").read_text(encoding="utf-8"))
    sin_clasificar = [
        a["name"] for a in payload["assets"] if group_of(a["name"]) == OTHER
    ]
    assert sin_clasificar == ["U.S. Inflation"]


@pytest.mark.parametrize(
    "nombre, grupo",
    [
        # Las trampas de substring: 'Private Equity' contiene 'Equity' y
        # 'Commercial Mortgage Loans' contiene 'Loans'.
        ("Private Equity", ALTERNATIVES),
        ("Venture Capital", ALTERNATIVES),
        ("Commercial Mortgage Loans", ALTERNATIVES),
        ("U.S. Leveraged Loans", FIXED_INCOME),
        # Convenciones declaradas: credito privado e inmobiliario listado.
        ("Direct Lending", ALTERNATIVES),
        ("U.S. REITs", ALTERNATIVES),
        ("U.S. Core Real Estate", ALTERNATIVES),
        # Factores de renta variable siguen siendo renta variable.
        ("U.S. Equity Minimum Volatility Factor", EQUITY),
        ("U.S. Large Cap", EQUITY),
        # Renta fija de todo tipo.
        ("TIPS", FIXED_INCOME),
        ("Emerging Markets Local Currency Debt", FIXED_INCOME),
        ("Global Convertible Bonds hedged", FIXED_INCOME),
        ("U.S. Muni High Yield", FIXED_INCOME),
        ("U.S. Cash", CASH),
    ],
)
def test_fronteras_del_mapeo(nombre, grupo):
    assert group_of(nombre) == grupo


def test_los_pesos_se_agregan_y_normalizan():
    grouped = group_weights(
        {
            "U.S. Large Cap": 0.30,
            "AC World Equity": 0.20,
            "U.S. Aggregate Bonds": 0.25,
            "Private Equity": 0.15,
            "U.S. Cash": 0.10,
        }
    )
    assert grouped[EQUITY] == pytest.approx(0.50)
    assert grouped[FIXED_INCOME] == pytest.approx(0.25)
    assert grouped[ALTERNATIVES] == pytest.approx(0.15)
    assert grouped[CASH] == pytest.approx(0.10)
    assert sum(grouped.values()) == pytest.approx(1.0)


def test_se_normaliza_aunque_no_sumen_cien():
    """Mientras se carga un portafolio los pesos no suman 100%; la vista sigue."""
    grouped = group_weights({"U.S. Large Cap": 0.30, "U.S. Aggregate Bonds": 0.10})
    assert grouped[EQUITY] == pytest.approx(0.75)
    assert grouped[FIXED_INCOME] == pytest.approx(0.25)


def test_el_orden_es_el_de_lectura_y_otros_va_al_final():
    grouped = group_weights(
        {
            "U.S. Cash": 0.1,
            "U.S. Inflation": 0.1,
            "U.S. Aggregate Bonds": 0.3,
            "U.S. Large Cap": 0.5,
        }
    )
    assert list(grouped) == [EQUITY, FIXED_INCOME, CASH, OTHER]
    assert GROUP_ORDER[-1] == CASH


def test_un_grupo_vacio_no_aparece():
    grouped = group_weights({"U.S. Large Cap": 1.0})
    assert list(grouped) == [EQUITY]


def test_sin_pesos_no_hay_agregacion():
    assert group_weights({}) == {}
    assert group_weights({"U.S. Large Cap": 0.0}) == {}
    assert group_summary({}) == "sin pesos definidos"


def test_el_resumen_es_una_linea_legible():
    texto = group_summary({"U.S. Large Cap": 0.6, "U.S. Aggregate Bonds": 0.4})
    assert texto == "Renta variable 60.0% · Renta fija 40.0%"
