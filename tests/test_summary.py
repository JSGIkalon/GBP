"""Tests de supuestos resumen, correlaciones y persistencia."""

from __future__ import annotations

import numpy as np
import pytest

from gbp.engine.summary import summarize
from gbp.model.allocation import Allocation
from gbp.model.assets import AssetClass, CMASet
from gbp.model.correlation import CorrelationMatrix, cholesky_factor, covariance, is_psd


# --------------------------------------------------------------------------
# Conversion de supuestos
# --------------------------------------------------------------------------


def test_retorno_aritmetico_supera_al_compuesto():
    """El arrastre de volatilidad es del orden de sigma^2/2 y desaparece sin ella.

    El caso sin volatilidad es el ancla de los tests determinísticos del motor:
    si ahí los dos retornos no coinciden, todos esos tests miden otra cosa.
    """
    asset = AssetClass("Acciones", compound_return=0.07, volatility=0.16)
    assert asset.arithmetic_return > asset.compound_return
    assert asset.arithmetic_return - asset.compound_return == pytest.approx(0.0116, abs=0.002)

    fijo = AssetClass("Fijo", compound_return=0.05, volatility=0.0)
    assert fijo.arithmetic_return == pytest.approx(0.05)
    assert fijo.sigma_log == 0.0


# --------------------------------------------------------------------------
# Supuestos resumen de una estrategia
# --------------------------------------------------------------------------


def test_resumen_de_un_solo_activo_devuelve_sus_propios_supuestos(simple_cmas, simple_corr):
    allocation = Allocation("Solo acciones", {"Acciones": 1.0})
    corr = simple_corr.subset(allocation.asset_names)
    summary = summarize(allocation, simple_cmas, corr)
    acciones = simple_cmas.by_name("Acciones")
    assert summary.arithmetic_return == pytest.approx(acciones.arithmetic_return)
    assert summary.volatility == pytest.approx(acciones.volatility)
    assert summary.compound_return == pytest.approx(acciones.compound_return, abs=1e-6)
    assert summary.yield_ == pytest.approx(acciones.yield_)


def test_el_sharpe_descuenta_la_tasa_de_caja(simple_cmas, simple_corr):
    allocation = Allocation("Mixto", {"Bonos": 0.5, "Acciones": 0.5})
    corr = simple_corr.subset(allocation.asset_names)
    summary = summarize(allocation, simple_cmas, corr)
    esperado = (summary.arithmetic_return - 0.03) / summary.volatility
    assert summary.sharpe_ratio == pytest.approx(esperado)


def test_el_yield_de_la_mezcla_es_el_promedio_ponderado(simple_cmas, simple_corr):
    allocation = Allocation("Mixto", {"Bonos": 0.25, "Acciones": 0.75})
    corr = simple_corr.subset(allocation.asset_names)
    summary = summarize(allocation, simple_cmas, corr)
    assert summary.yield_ == pytest.approx(0.25 * 0.038 + 0.75 * 0.02)


def test_la_correlacion_perfecta_no_diversifica():
    cmas = CMASet([AssetClass("A", 0.06, 0.10), AssetClass("B", 0.06, 0.20)])
    corr = np.array([[1.0, 1.0], [1.0, 1.0]])
    summary = summarize(Allocation("Mixto", {"A": 0.5, "B": 0.5}), cmas, corr)
    assert summary.volatility == pytest.approx(0.15)


# --------------------------------------------------------------------------
# Matriz de correlacion
# --------------------------------------------------------------------------


def test_la_matriz_embebida_del_ltcma_carga_y_es_psd():
    matrix = CorrelationMatrix.load()
    assert len(matrix.names) > 50
    assert not matrix.provisional
    assert is_psd(matrix.matrix)
    # La reparacion a PSD debe ser cosmetica, no reescribir los supuestos.
    assert matrix.psd_adjustment < 0.02


@pytest.mark.parametrize(
    ("build", "error", "match"),
    [
        pytest.param(
            lambda: CMASet([AssetClass("A", 0.05, 0.1), AssetClass("A", 0.06, 0.1)]),
            ValueError, "duplicad", id="cma_con_clase_duplicada",
        ),
        pytest.param(
            lambda: CorrelationMatrix.load().subset(["U.S. Cash", "Cripto"]),
            KeyError, "Cripto", id="subset_con_clase_faltante",
        ),
        pytest.param(
            lambda: CorrelationMatrix(
                names=["A", "B"], matrix=np.array([[1.0, 0.5], [0.2, 1.0]])
            ),
            ValueError, "simetrica|simétrica", id="matriz_asimetrica",
        ),
    ],
)
def test_supuestos_mal_formados_se_rechazan(build, error, match):
    """Un supuesto roto debe fallar al cargarse, nombrando el problema, y no
    producir en silencio una simulación con la clase o la correlación equivocada."""
    with pytest.raises(error, match=match):
        build()


def test_cholesky_ignora_activos_sin_volatilidad():
    cov = covariance(np.array([0.0, 0.2]), np.array([[1.0, 0.0], [0.0, 1.0]]))
    factor = cholesky_factor(cov)
    assert np.allclose(factor[0], 0.0)
    assert factor[1, 1] == pytest.approx(0.2)


def test_cholesky_repara_una_matriz_no_psd():
    corr = np.array([[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]])
    assert not is_psd(corr)
    factor = cholesky_factor(covariance(np.array([0.1, 0.1, 0.1]), corr))
    assert np.isfinite(factor).all()
