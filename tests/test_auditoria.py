"""Regresiones de la auditoría: resultados obsoletos, monedas, memoria y ajustes."""

from __future__ import annotations

import json
import os
from copy import deepcopy

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gbp.engine.montecarlo import (
    MEMORY_BLOCK_BYTES,
    estimate_memory_bytes,
    simulate,
)
from gbp.io import library
from gbp.io.caseio import from_dict, to_dict
from gbp.model.allocation import Allocation
from gbp.model.assets import ORIGIN_CUSTOM, AssetClass
from gbp.model.goals import Goal, goal_probability
from gbp.model.groups import FIXED_INCOME
from gbp.model.leverage import LoanSimulator, LoanTerms
from gbp.model.scenario import PesoAssumptions, Scenario, SimulationSettings
from gbp.model.strategy import Strategy

PROPIO = dict(
    name="Renta Fija Colombiana",
    compound_return=0.06,
    volatility=0.10,
    origin=ORIGIN_CUSTOM,
    asset_class=FIXED_INCOME,
)


@pytest.fixture(autouse=True)
def libreria_aislada(tmp_path, monkeypatch):
    monkeypatch.setenv("GBP_DATA_DIR", str(tmp_path))


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    from gbp.ui.main_window import MainWindow

    win = MainWindow()
    yield win
    win.close()


# --------------------------------------------------------------------------
# 1. Resultados obsoletos al cambiar supuestos de mercado
# --------------------------------------------------------------------------


def test_editar_un_activo_propio_usado_deja_los_resultados_obsoletos(window):
    window.cmas.add(AssetClass(**PROPIO))
    window._on_assets_changed()
    window.scenario.strategies = [Strategy(Allocation(
        "Con propio", {"U.S. Large Cap": 0.6, "Renta Fija Colombiana": 0.4}
    ))]
    window._run_scenario = deepcopy(window.scenario)
    window._run_market = window._market_signature()
    assert not window.results_are_stale()

    window.cmas.by_name("Renta Fija Colombiana").compound_return = 0.09
    window._on_assets_changed()
    assert window.results_are_stale()


# --------------------------------------------------------------------------
# 2-3. Moneda de activos propios
# --------------------------------------------------------------------------


@pytest.mark.parametrize("antes, despues", [("USD", "COP"), ("COP", "USD")])
def test_editar_la_moneda_de_un_activo_propio_se_guarda(qapp, monkeypatch, antes, despues):
    import gbp.ui.custom_asset_dialog as dialog_mod
    from gbp.ui.panels.assets_panel import AssetsPanel

    cmas = library.seed_cmas()
    cmas.add(AssetClass(**PROPIO, currency=antes))
    library.save_cmas(cmas)
    panel = AssetsPanel(cmas, None)
    asset = cmas.by_name(PROPIO["name"])
    monkeypatch.setattr(type(panel), "selected", property(lambda self: asset))

    class Falso:
        DialogCode = dialog_mod.CustomAssetDialog.DialogCode

        def __init__(self, *a, **k):
            pass

        def exec(self):
            return self.DialogCode.Accepted

        def asset(self):
            return AssetClass(**PROPIO, currency=despues)

    monkeypatch.setattr(dialog_mod, "CustomAssetDialog", Falso)
    panel._edit_asset()

    assert asset.currency == despues
    assert library.load_cmas().by_name(PROPIO["name"]).currency == despues


def test_el_aviso_de_moneda_sigue_la_moneda_elegida():
    from gbp.ui.custom_asset_dialog import currency_note

    for code in ("USD", "COP"):
        assert "no convierte" not in currency_note(code)
        assert "descuenta tú" not in currency_note(code)
    assert "COP" in currency_note("COP")
    assert "riesgo cambiario" in currency_note("COP")


# --------------------------------------------------------------------------
# 4. Memoria
# --------------------------------------------------------------------------


def test_un_millon_de_caminos_con_60_activos_se_bloquea():
    need = estimate_memory_bytes(1_000_000, 60, 30, 3)
    assert need > MEMORY_BLOCK_BYTES
    assert estimate_memory_bytes(10_000, 60, 30, 3) < 1024**3


def test_la_ventana_no_corre_una_simulacion_que_agota_la_memoria(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: avisos.append(a))
    window.settings.n_paths = 1_000_000
    window.scenario.horizon = 100
    assert window._memory_ok() is False
    assert avisos


# --------------------------------------------------------------------------
# 5-6. Ajustes
# --------------------------------------------------------------------------


def test_restaurar_vuelve_todas_las_preferencias(qapp):
    from gbp.ui.panels.settings_panel import SettingsPanel

    settings = SimulationSettings(
        n_paths=50_000, milestone_years=[3], show_cop=True,
        display_scale="millones", chart_kind="abanico", show_percentile_labels=False,
    )
    panel = SettingsPanel(settings)
    panel._reset()
    d = SimulationSettings()
    assert (settings.n_paths, settings.milestone_years, settings.show_cop,
            settings.display_scale, settings.chart_kind,
            settings.show_percentile_labels) == (
        d.n_paths, d.milestone_years, d.show_cop, d.display_scale, d.chart_kind,
        d.show_percentile_labels)


def test_hitos_invalidos_se_informan_y_no_vuelven_a_los_de_fabrica(qapp):
    from gbp.ui.panels.settings_panel import SettingsPanel

    years, rejected = SettingsPanel.parse_milestones("5, diez, 0, 2.5, 40")
    assert years == [5, 40]
    assert rejected == ["diez", "0", "2.5"]

    settings = SimulationSettings(milestone_years=[7, 12])
    panel = SettingsPanel(settings)
    panel.set_horizon(30)
    panel.milestones.setText("basura")
    panel.commit()
    assert settings.milestone_years == [7, 12]
    assert "basura" in panel.milestone_note.text()

    panel.milestones.setText("5, 40")
    panel.commit()
    assert settings.milestone_years == [5, 40]
    assert "40" in panel.milestone_note.text()


# --------------------------------------------------------------------------
# 7. Metas y flujos fuera del horizonte
# --------------------------------------------------------------------------


def test_meta_fuera_del_horizonte_se_avisa(qapp):
    from gbp.ui.panels.goals_panel import GoalsPanel

    panel = GoalsPanel([Goal("Casa", 10.0, 50)])
    panel.set_horizon(30)
    assert not panel.horizon_note.isHidden()
    assert "Casa" in panel.horizon_note.text()
    panel.set_horizon(60)
    assert panel.horizon_note.isHidden()


# --------------------------------------------------------------------------
# 9. Moneda en metas y crédito
# --------------------------------------------------------------------------

PESO = PesoAssumptions(spot=4_000.0, devaluation=0.03)


def _resultado(simple_cmas, simple_corr, loan=None, peso=PESO):
    scenario = Scenario(
        initial_value=1_000_000.0, horizon=10, peso=peso,
        strategies=[Strategy(Allocation("A", {"Bonos": 0.5, "Acciones": 0.5}), loan=loan)],
    )
    settings = SimulationSettings(n_paths=2_000, seed=3)
    return simulate(scenario, simple_cmas, simple_corr, settings).strategies[0]


def test_meta_en_cop_equivale_a_la_meta_en_usd(simple_cmas, simple_corr):
    res = _resultado(simple_cmas, simple_corr)
    # Nominal: el umbral es el monto en pesos a la tasa del año.
    cop = Goal("Casa", 4_000.0 * 1_200_000.0, 8, real=False, currency="COP")
    usd = Goal("Casa", 4_000.0 * 1_200_000.0 / PESO.rate(8), 8, real=False)
    assert goal_probability(res, cop, PESO) == goal_probability(res, usd)
    # De hoy, con inflación de paridad: monto / spot en USD de hoy.
    cop_real = Goal("Legado", 4_000.0 * 900_000.0, None, currency="COP")
    usd_real = Goal("Legado", 900_000.0, None)
    assert goal_probability(res, cop_real, PESO) == goal_probability(res, usd_real)


def test_meta_en_cop_sin_tasa_es_un_error(simple_cmas, simple_corr):
    res = _resultado(simple_cmas, simple_corr, peso=None)
    with pytest.raises(ValueError):
        goal_probability(res, Goal("Casa", 1.0, 5, currency="COP"), None)


def test_credito_cop_sin_devaluacion_y_tasa_uno_es_el_credito_usd(simple_cmas, simple_corr):
    par = PesoAssumptions(spot=1.0, devaluation=0.0)
    terms = dict(principal=300_000.0, term_years=5, rate=0.06, max_ltv=0.5)
    usd = _resultado(simple_cmas, simple_corr, LoanTerms(**terms), peso=par)
    cop = _resultado(simple_cmas, simple_corr, LoanTerms(**terms, currency="COP"), peso=par)
    np.testing.assert_allclose(cop.wealth, usd.wealth)


def test_la_deuda_en_cop_pesa_menos_en_usd_con_devaluacion():
    peso = PesoAssumptions(spot=4_000.0, devaluation=0.05)
    terms = LoanTerms(principal=4_000_000.0, term_years=5, rate=0.0, currency="COP")
    ledger = LoanSimulator(terms, 1, 5, peso=peso)
    assert ledger.drawdown(1) == pytest.approx(1_000.0)
    assert ledger.balance_usd(1)[0] == pytest.approx(1_000.0 / 1.05)
    assert ledger.balance_usd(3)[0] == pytest.approx(1_000.0 / 1.05**3)


def test_meta_y_credito_en_cop_sobreviven_al_guardado():
    scenario = Scenario(
        initial_value=1.0, horizon=10, peso=PESO,
        goals=[Goal("Casa", 5.0, 3, currency="COP")],
        strategies=[Strategy(Allocation("A", {"Bonos": 1.0}),
                             loan=LoanTerms(principal=10.0, currency="COP"))],
    )
    data = to_dict(scenario)
    back = from_dict(json.loads(json.dumps(data)))
    assert back.goals[0].currency == "COP"
    assert back.strategies[0].loan.currency == "COP"

    # Un caso viejo, sin el campo, abre en USD.
    data["scenario"]["goals"][0].pop("currency")
    assert from_dict(data).goals[0].currency == "USD"


# --------------------------------------------------------------------------
# Cambiar la vista no recalcula la corrida
# --------------------------------------------------------------------------


def test_filtro_grafico_y_pantallas_no_recalculan_la_corrida(window, monkeypatch):
    """Ni simular de nuevo, ni convertir a COP, ni recalcular percentiles."""
    import gbp.engine.montecarlo as mc
    from gbp.model.results import SimulationResult

    window.scenario.peso = PesoAssumptions(spot=4_000.0, devaluation=0.03)
    window.settings.show_cop = True
    window.settings.n_paths = 2_000
    result = simulate(window.scenario, window.cmas.in_usd(0.03), window.correlations,
                      window.settings)
    window._run_scenario = deepcopy(window.scenario)
    window._on_finished(result)
    window._apply_result_view()

    llamadas = {"sim": 0, "fx": 0, "pct": 0}
    real_sim, real_fx, real_pct = mc.simulate, SimulationResult.in_currency, np.percentile
    monkeypatch.setattr(mc, "simulate", lambda *a, **k: llamadas.__setitem__(
        "sim", llamadas["sim"] + 1) or real_sim(*a, **k))
    monkeypatch.setattr(SimulationResult, "in_currency", lambda self, *a, **k: (
        llamadas.__setitem__("fx", llamadas["fx"] + 1) or real_fx(self, *a, **k)))
    monkeypatch.setattr(np, "percentile", lambda *a, **k: (
        llamadas.__setitem__("pct", llamadas["pct"] + 1) or real_pct(*a, **k)))

    # Una primera pasada por cada vista llena las cachés de lo que aún no se vio.
    nombres = [s.name for s in window.scenario.strategies]
    for kind in ("abanico", "medianas", "cajas"):
        window.results.set_chart_kind(kind)
    for i in range(window.results.count()):
        window.results.setCurrentIndex(i)
    window.strategy_filter.set_selected(nombres[:1])
    window.strategy_filter.set_selected(nombres)
    llamadas.update(sim=0, fx=0, pct=0)

    for _ in range(2):
        window.strategy_filter.set_selected(nombres[:1])
        window.strategy_filter.set_selected(nombres)
        for kind in ("abanico", "medianas", "cajas"):
            window.results.set_chart_kind(kind)
        for i in range(window.results.count()):
            window.results.setCurrentIndex(i)
        for i in range(window.inputs.count()):
            window._go_to_section(i)
        window.settings_panel.show_cop.setChecked(True)

    assert llamadas == {"sim": 0, "fx": 0, "pct": 0}
