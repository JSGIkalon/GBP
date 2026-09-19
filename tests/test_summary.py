"""Tests de supuestos resumen, correlaciones, stress tests y persistencia."""

from __future__ import annotations

import numpy as np
import pytest

from gbp.engine.stress import StressScenario, default_scenarios, group_of, run_stress_tests
from gbp.engine.summary import summarize
from gbp.model.allocation import Allocation
from gbp.model.assets import AssetClass, CMASet
from gbp.model.correlation import CorrelationMatrix, cholesky_factor, covariance, is_psd


# --------------------------------------------------------------------------
# Conversion de supuestos
# --------------------------------------------------------------------------


def test_retorno_aritmetico_supera_al_compuesto():
    asset = AssetClass("Acciones", compound_return=0.07, volatility=0.16)
    assert asset.arithmetic_return > asset.compound_return
    # El arrastre es del orden de sigma^2/2.
    assert asset.arithmetic_return - asset.compound_return == pytest.approx(0.0116, abs=0.002)


def test_sin_volatilidad_ambos_retornos_coinciden():
    asset = AssetClass("Fijo", compound_return=0.05, volatility=0.0)
    assert asset.arithmetic_return == pytest.approx(0.05)
    assert asset.sigma_log == 0.0


def test_apreciacion_es_retorno_menos_yield():
    asset = AssetClass("Bonos", compound_return=0.04, volatility=0.05, yield_=0.038)
    assert asset.appreciation == pytest.approx(0.002)


def test_cma_rechaza_duplicados():
    with pytest.raises(ValueError, match="duplicad"):
        CMASet([AssetClass("A", 0.05, 0.1), AssetClass("A", 0.06, 0.1)])


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


def test_la_diversificacion_reduce_la_volatilidad(simple_cmas, simple_corr):
    """La volatilidad de la mezcla es menor que el promedio ponderado."""
    allocation = Allocation("Mixto", {"Bonos": 0.5, "Acciones": 0.5})
    corr = simple_corr.subset(allocation.asset_names)
    summary = summarize(allocation, simple_cmas, corr)
    promedio = 0.5 * 0.05 + 0.5 * 0.16
    assert summary.volatility < promedio


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


def test_la_matriz_embebida_trae_las_clases_del_ejemplo():
    matrix = CorrelationMatrix.load()
    for name in ("U.S. Cash", "U.S. Large Cap", "Private Equity", "Direct Lending"):
        assert name in matrix.names


def test_subset_respeta_el_orden_pedido():
    matrix = CorrelationMatrix.load()
    names = ["Private Equity", "U.S. Cash"]
    sub = matrix.subset(names)
    assert sub.shape == (2, 2)
    assert sub[0, 1] == pytest.approx(sub[1, 0])


def test_subset_avisa_si_falta_una_clase():
    matrix = CorrelationMatrix.load()
    with pytest.raises(KeyError, match="Cripto"):
        matrix.subset(["U.S. Cash", "Cripto"])


def test_matriz_asimetrica_se_rechaza():
    with pytest.raises(ValueError, match="simetrica|simétrica"):
        CorrelationMatrix(names=["A", "B"], matrix=np.array([[1.0, 0.5], [0.2, 1.0]]))


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


# --------------------------------------------------------------------------
# Stress tests
# --------------------------------------------------------------------------


def test_el_impacto_es_la_suma_ponderada_de_los_shocks():
    scenario = StressScenario(
        name="Test", shocks={"Acciones": -0.40, "Bonos": 0.05}
    )
    allocation = Allocation("Mixto", {"Acciones": 0.6, "Bonos": 0.4})
    assert scenario.impact(allocation) == pytest.approx(0.6 * -0.40 + 0.4 * 0.05)


def test_las_clases_sin_shock_explicito_usan_el_grupo():
    scenario = StressScenario(name="Test", default_by_group={"equity": -0.30})
    allocation = Allocation("Acciones", {"U.S. Large Cap": 1.0})
    assert scenario.impact(allocation) == pytest.approx(-0.30)


def test_la_clasificacion_por_grupo_reconoce_las_clases_del_ltcma():
    assert group_of("U.S. Cash") == "caja"
    assert group_of("U.S. Large Cap") == "equity"
    assert group_of("Private Equity") == "privados"
    assert group_of("U.S. Core Real Estate") == "real"
    assert group_of("Diversified Hedge Funds") == "hedge"


def test_una_cartera_mas_agresiva_cae_mas_en_las_crisis():
    conservadora = Allocation(
        "Conservadora", {"U.S. Aggregate Bonds": 0.7, "U.S. Large Cap": 0.3}
    )
    agresiva = Allocation("Agresiva", {"U.S. Large Cap": 0.8, "Private Equity": 0.2})
    for scenario in default_scenarios():
        if "tasas" in scenario.name.lower():
            continue  # en el shock de tasas la renta fija tambien cae
        assert scenario.impact(agresiva) < scenario.impact(conservadora), scenario.name


def test_run_stress_tests_escala_por_el_valor_del_portafolio():
    allocation = Allocation("Acciones", {"U.S. Large Cap": 1.0})
    scenario = StressScenario(name="Caida", default_by_group={"equity": -0.25})
    result = run_stress_tests([allocation], [scenario], initial_value=1_000_000.0)
    assert result["Caida"]["Acciones"] == pytest.approx(-250_000.0)


def test_el_desglose_suma_el_impacto_total():
    allocation = Allocation("Mixto", {"U.S. Large Cap": 0.6, "U.S. Aggregate Bonds": 0.4})
    scenario = default_scenarios()[0]
    desglose = scenario.breakdown(allocation)
    assert sum(row[3] for row in desglose) == pytest.approx(scenario.impact(allocation))


# --------------------------------------------------------------------------
# Persistencia de la librería de CMAs
# --------------------------------------------------------------------------


def test_la_libreria_se_siembra_desde_el_ltcma(tmp_path, monkeypatch):
    monkeypatch.setenv("GBP_DATA_DIR", str(tmp_path))
    from gbp.io import library

    cmas = library.load_cmas()
    assert len(cmas) > 50
    assert library.library_path().exists()
    # El LTCMA no publica yield: se deja en cero para completar a mano.
    assert all(a.yield_ == 0.0 for a in cmas)


def test_las_ediciones_manuales_sobreviven_a_una_recarga(tmp_path, monkeypatch):
    monkeypatch.setenv("GBP_DATA_DIR", str(tmp_path))
    from gbp.io import library

    cmas = library.load_cmas()
    cmas.by_name("U.S. Large Cap").yield_ = 0.017
    cmas.by_name("U.S. Large Cap").compound_return = 0.065
    library.save_cmas(cmas)

    recargada = library.load_cmas()
    assert recargada.by_name("U.S. Large Cap").yield_ == pytest.approx(0.017)
    assert recargada.by_name("U.S. Large Cap").compound_return == pytest.approx(0.065)


def test_agregar_una_clase_propia_persiste(tmp_path, monkeypatch):
    monkeypatch.setenv("GBP_DATA_DIR", str(tmp_path))
    from gbp.io import library

    cmas = library.load_cmas()
    cmas.add(AssetClass("Deuda privada Colombia", 0.09, 0.07, 0.08))
    library.save_cmas(cmas)
    assert "Deuda privada Colombia" in library.load_cmas().names


def test_reset_devuelve_los_supuestos_del_ltcma(tmp_path, monkeypatch):
    monkeypatch.setenv("GBP_DATA_DIR", str(tmp_path))
    from gbp.io import library

    cmas = library.load_cmas()
    cmas.by_name("U.S. Large Cap").compound_return = 0.99
    library.save_cmas(cmas)

    restaurada = library.reset_cmas_to_ltcma()
    assert restaurada.by_name("U.S. Large Cap").compound_return < 0.2


def test_la_configuracion_general_persiste(tmp_path, monkeypatch):
    monkeypatch.setenv("GBP_DATA_DIR", str(tmp_path))
    from gbp.io import library
    from gbp.model.scenario import SimulationSettings

    assert library.load_settings().n_paths == 10_000  # valor por defecto
    library.save_settings(SimulationSettings(n_paths=25_000, seed=7, show_real_values=True))
    recargada = library.load_settings()
    assert recargada.n_paths == 25_000
    assert recargada.seed == 7
    assert recargada.show_real_values is True


def test_una_configuracion_corrupta_no_rompe_la_app(tmp_path, monkeypatch):
    monkeypatch.setenv("GBP_DATA_DIR", str(tmp_path))
    from gbp.io import library

    path = library.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"n_paths": "muchas"}', encoding="utf-8")
    assert library.load_settings().n_paths == 10_000
