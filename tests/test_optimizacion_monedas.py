"""Metas sin prioridad, monedas, filtro de estrategias y optimización del portafolio."""

from __future__ import annotations

import os
from copy import deepcopy

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gbp.engine.montecarlo import simulate
from gbp.engine.optimizer import (
    MAX_EFFICIENCY,
    MAX_RETURN,
    MIN_VOLATILITY,
    OptimizationError,
    optimize,
    project_capped_simplex,
)
from gbp.io.caseio import from_dict, to_dict
from gbp.model.allocation import Allocation
from gbp.model.assets import ORIGIN_CUSTOM, AssetClass, CMASet
from gbp.model.correlation import CorrelationMatrix
from gbp.model.currency import (
    CurrencyError,
    check_rate,
    factor_to_base,
    from_base,
    to_base,
)
from gbp.model.goals import Goal
from gbp.model.groups import FIXED_INCOME
from gbp.model.scenario import PesoAssumptions, Scenario, SimulationSettings
from gbp.model.strategy import Strategy

SETTINGS = SimulationSettings(n_paths=2_000, seed=7)


@pytest.fixture(autouse=True)
def libreria_aislada(tmp_path, monkeypatch):
    monkeypatch.setenv("GBP_DATA_DIR", str(tmp_path))


def _case(simple_cmas, initial=1_000_000.0, currency="USD", peso=None, flows=None):
    return Scenario(
        name="Prueba",
        initial_value=initial,
        initial_currency=currency,
        horizon=10,
        peso=peso,
        strategies=[
            Strategy(Allocation("A", {"Bonos": 0.5, "Acciones": 0.5}), cashflows=flows or []),
            Strategy(Allocation("B", {"Bonos": 0.8, "Acciones": 0.2})),
        ],
    )


# --------------------------------------------------------------------------
# 1. Metas sin prioridad
# --------------------------------------------------------------------------


def test_la_meta_ya_no_tiene_prioridad():
    goal = Goal("Casa", 100.0, 5)
    assert not hasattr(goal, "priority")
    with pytest.raises(TypeError):
        Goal("Casa", 100.0, 5, True, "esencial")  # el quinto argumento ya no existe


def test_un_caso_viejo_con_prioridad_se_abre_y_se_guarda_sin_ella(simple_cmas):
    payload = to_dict(_case(simple_cmas))
    payload["scenario"]["goals"] = [
        {"name": "Legado", "amount": 5.0, "year": None, "real": True, "priority": "esencial"}
    ]
    case = from_dict(payload)
    assert case.goals[0].name == "Legado"
    assert "priority" not in to_dict(case)["scenario"]["goals"][0]


def test_tabla_de_metas_sin_prioridad_ni_campo_bajo_moneda_de_hoy(qapp):
    from PySide6.QtCore import Qt

    from gbp.ui.panels.goals_panel import COL_REAL, COLUMNS, GoalsPanel

    goals = [Goal("Meta", 10.0, 3)]
    panel = GoalsPanel(goals)
    assert "Prioridad" not in COLUMNS
    # Meta, Monto, Moneda (USD/COP), Año, Moneda de hoy.
    assert panel.table.columnCount() == 5
    real = panel.table.item(0, COL_REAL)
    # Una casilla, no un campo de texto: no es editable como texto.
    assert real.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert not real.flags() & Qt.ItemFlag.ItemIsEditable
    assert real.text() == ""
    assert panel.table.cellWidget(0, COL_REAL) is None
    real.setCheckState(Qt.CheckState.Unchecked)
    assert goals[0].real is False


# --------------------------------------------------------------------------
# 2. Monedas
# --------------------------------------------------------------------------


def test_misma_moneda_no_convierte():
    assert factor_to_base("USD", None) == 1.0
    assert to_base(123.456, "USD", None) == 123.456


def test_conversion_cop_a_usd_y_vuelta():
    peso = PesoAssumptions(spot=4_000.0)
    assert to_base(4_000_000.0, "COP", peso) == pytest.approx(1_000.0)
    assert from_base(1_000.0, "COP", peso) == pytest.approx(4_000_000.0)


@pytest.mark.parametrize("rate", [0, -5, float("nan"), float("inf"), "abc", None])
def test_tasa_invalida(rate):
    with pytest.raises(CurrencyError):
        check_rate(rate)


def test_tasa_invalida_no_crea_supuestos_del_peso():
    with pytest.raises(ValueError):
        PesoAssumptions(spot=float("nan"))
    with pytest.raises(ValueError):
        PesoAssumptions(spot=0.0)


def test_moneda_desconocida():
    with pytest.raises(CurrencyError):
        factor_to_base("EUR", None)
    with pytest.raises(ValueError):
        Scenario(initial_currency="EUR")


def test_capital_en_cop_sin_tasa_no_simula(simple_cmas):
    case = _case(simple_cmas, initial=4_000_000_000.0, currency="COP")
    with pytest.raises(ValueError, match="tasa USD/COP"):
        case.validate(simple_cmas)
    with pytest.raises(CurrencyError):
        case.initial_in_base()


def test_capital_en_cop_simula_igual_que_su_equivalente_en_usd(simple_cmas, simple_corr):
    peso = PesoAssumptions(spot=4_000.0, devaluation=0.03)
    en_cop = _case(simple_cmas, initial=4_000_000_000.0, currency="COP", peso=peso)
    en_usd = _case(simple_cmas, initial=1_000_000.0, currency="USD", peso=peso)
    a = simulate(en_cop, simple_cmas, simple_corr, SETTINGS)
    b = simulate(en_usd, simple_cmas, simple_corr, SETTINGS)
    for sa, sb in zip(a.strategies, b.strategies):
        assert sa.initial_value == pytest.approx(1_000_000.0)
        np.testing.assert_allclose(sa.wealth, sb.wealth, rtol=1e-12)


def test_capital_en_usd_queda_identico_bit_a_bit(simple_cmas, simple_corr):
    """Un caso en USD no pasa por ninguna multiplicación nueva."""
    case = _case(simple_cmas)
    assert case.capital_factor == 1.0
    result = simulate(case, simple_cmas, simple_corr, SETTINGS)
    assert result.strategies[0].initial_value == 1_000_000.0


def test_la_moneda_del_capital_viaja_con_el_caso(simple_cmas):
    case = _case(simple_cmas, currency="COP", peso=PesoAssumptions(spot=4_100.0))
    again = from_dict(to_dict(case))
    assert again.initial_currency == "COP"
    # Un caso viejo sin el campo queda en USD.
    payload = to_dict(_case(simple_cmas))
    payload["scenario"].pop("initial_currency")
    assert from_dict(payload).initial_currency == "USD"


# --------------------------------------------------------------------------
# 4. Filtro de estrategias
# --------------------------------------------------------------------------


def test_subset_filtra_sin_tocar_cifras(simple_cmas, simple_corr):
    result = simulate(_case(simple_cmas), simple_cmas, simple_corr, SETTINGS)
    only_b = result.subset(["B"])
    assert only_b.names == ["B"]
    assert only_b.strategies[0] is result.by_name("B")
    assert len(result.subset([])) == 0


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    from gbp.ui.main_window import MainWindow

    win = MainWindow()
    yield win
    win.close()


def _finish_run(window):
    """Corre la simulación sin hilo y entrega el resultado como lo haría el worker."""
    window._pending_scenario = deepcopy(window.scenario)
    result = simulate(window.scenario, window.cmas, window.correlations,
                      SimulationSettings(n_paths=1_000, seed=42))
    window._on_finished(result)
    return result


def test_filtro_de_estrategias_actualiza_tablas_indicadores_y_vacio(window):
    _finish_run(window)
    names = [s.name for s in window.scenario.strategies]
    assert len(names) >= 2
    assert window.results.result.names == names  # estado inicial: todas

    window.strategy_filter.set_selected([names[1]])
    assert window.results.result.names == [names[1]]
    assert window.results.summary_table.columnCount() == 2
    assert names[1] in window.kpis.success.unit.text()
    expected = window.results.base_result.by_name(names[1]).success_probability
    assert window.kpis.success.value.text() == f"{expected:.1%}"

    window.strategy_filter.set_selected([])
    assert len(window.results.result) == 0
    assert window.results.summary_table.rowCount() == 0
    assert window.results.allocation_table.rowCount() == 0

    window.strategy_filter.select_all()
    assert window.results.result.names == names


def test_una_estrategia_nueva_aparece_seleccionada(window):
    window.strategy_filter.set_selected([window.scenario.strategies[0].name])
    nueva = window.scenario.strategies[0].copy("Nueva")
    window.scenario.strategies.append(nueva)
    window._refresh_dependent_views(force=True)
    assert "Nueva" in window.strategy_filter.selected


def test_graficos_responsivos_se_redibujan_al_cambiar_de_tamano(window):
    _finish_run(window)
    for canvas in (window.results.box_canvas, window.results.allocation_canvas,
                   window.results.debt_canvas):
        assert canvas._redraw is not None
    calls = []
    window.results.allocation_canvas.set_redraw(lambda: calls.append(1))
    window.results.allocation_canvas._on_resized()
    assert calls


def test_filtro_salta_de_linea_en_pantallas_angostas(qapp):
    from gbp.ui.strategy_filter import StrategyFilter

    f = StrategyFilter()
    f.set_strategies([f"Estrategia número {i}" for i in range(8)])
    narrow = f._flow.heightForWidth(220)
    wide = f._flow.heightForWidth(2_000)
    assert narrow > wide  # en angosto usa más líneas en vez de desbordarse


# --------------------------------------------------------------------------
# 3. Visibilidad de los campos
# --------------------------------------------------------------------------


def test_hoja_de_estilos_da_contraste_al_texto_de_los_campos():
    from gbp.ui.theme import INK, PRIMARY, STYLESHEET, WHITE

    campos = STYLESHEET.split("/* --- Campos")[1].split("/* --- Botones")[0]
    assert f"color: {INK}" in campos
    assert f"selection-background-color: {PRIMARY}" in campos
    assert f"selection-color: {WHITE}" in campos
    assert "placeholder-text-color" in campos
    # El editor dentro de una celda no hereda el padding que recortaba el texto.
    assert "QTableView QLineEdit" in campos and "padding: 0px 6px" in campos


def test_contraste_texto_fondo_cumple_wcag_aa():
    from gbp.ui.theme import INK, INK_SOFT, PRIMARY, WHITE

    def luminance(hex_color):
        rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    def ratio(a, b):
        la, lb = sorted((luminance(a), luminance(b)), reverse=True)
        return (la + 0.05) / (lb + 0.05)

    assert ratio(INK, WHITE) >= 4.5           # texto escrito
    assert ratio(WHITE, PRIMARY) >= 4.5       # texto seleccionado
    assert ratio(INK_SOFT, WHITE) >= 4.0      # placeholder y campos apagados


# --------------------------------------------------------------------------
# 6-9. Optimización
# --------------------------------------------------------------------------


def _opt(simple_cmas, simple_corr, assets, bounds=None, case=None, cmas=None, corr=None):
    case = case or _case(simple_cmas)
    return optimize(case, "A", assets, cmas or simple_cmas, corr or simple_corr, bounds)


def _check_constraints(weights, assets, bounds=None):
    total = sum(weights.values())
    assert total == pytest.approx(1.0, abs=1e-9)
    assert all(w >= 0 for w in weights.values())
    assert set(weights) <= set(assets)
    for name, (lo, hi) in (bounds or {}).items():
        w = weights.get(name, 0.0)
        assert lo - 1e-9 <= w <= hi + 1e-9


def test_proyeccion_sobre_el_simplex_con_limites():
    lo, hi = np.array([0.1, 0.0, 0.0]), np.array([0.5, 0.5, 0.5])
    w = project_capped_simplex(np.array([3.0, -1.0, 0.2]), lo, hi)
    assert w.sum() == pytest.approx(1.0)
    assert np.all(w >= lo - 1e-12) and np.all(w <= hi + 1e-12)


def test_las_tres_estrategias_y_sus_restricciones(simple_cmas, simple_corr):
    assets = ["Bonos", "Acciones", "U.S. Cash"]
    report = _opt(simple_cmas, simple_corr, assets)
    for key in (MAX_RETURN, MIN_VOLATILITY, MAX_EFFICIENCY):
        assert report.outcomes[key].ok
        _check_constraints(report.outcomes[key].stats.weights, assets)
    # Máximo retorno: todo al activo de mayor retorno.
    assert report.outcomes[MAX_RETURN].stats.weights == {"Acciones": pytest.approx(1.0)}

    # Contra una búsqueda exhaustiva en una grilla fina.
    mu = np.array([simple_cmas.by_name(n).arithmetic_return for n in assets])
    sig = np.array([simple_cmas.by_name(n).volatility for n in assets])
    cov = np.outer(sig, sig) * simple_corr.subset(assets)
    grid = [(a, b, 1 - a - b) for a in np.linspace(0, 1, 201) for b in np.linspace(0, 1, 201)
            if a + b <= 1 + 1e-12]
    W = np.array(grid)
    vols = np.sqrt(np.einsum("ij,jk,ik->i", W, cov, W))
    rets = W @ mu
    assert report.outcomes[MIN_VOLATILITY].stats.volatility <= vols.min() + 1e-9
    assert report.outcomes[MAX_EFFICIENCY].stats.ratio >= (rets / vols).max() - 1e-9
    assert report.outcomes[MAX_RETURN].stats.expected_return >= rets.max() - 1e-12


def test_solo_usa_los_activos_seleccionados(simple_cmas, simple_corr):
    report = _opt(simple_cmas, simple_corr, ["Bonos", "U.S. Cash"])
    for outcome in report.outcomes.values():
        assert "Acciones" not in outcome.stats.weights
        _check_constraints(outcome.stats.weights, ["Bonos", "U.S. Cash"])


def test_respeta_minimos_y_maximos(simple_cmas, simple_corr):
    assets = ["Bonos", "Acciones", "U.S. Cash"]
    bounds = {"Acciones": (0.10, 0.40), "U.S. Cash": (0.0, 0.05), "Bonos": (0.2, 1.0)}
    report = _opt(simple_cmas, simple_corr, assets, bounds)
    for outcome in report.outcomes.values():
        _check_constraints(outcome.stats.weights, assets, bounds)
    assert report.outcomes[MAX_RETURN].stats.weights["Acciones"] == pytest.approx(0.40)


@pytest.mark.parametrize(
    "bounds, match",
    [
        ({"Bonos": (0.7, 1.0), "Acciones": (0.6, 1.0)}, "mínimos suman"),
        ({"Bonos": (0.0, 0.3), "Acciones": (0.0, 0.3)}, "máximos suman"),
        ({"Bonos": (0.5, 0.2)}, "supera al máximo"),
        ({"Bonos": (-0.1, 1.0)}, "entre 0% y 100%"),
    ],
)
def test_limites_imposibles_no_dan_pesos(simple_cmas, simple_corr, bounds, match):
    with pytest.raises(OptimizationError, match=match):
        _opt(simple_cmas, simple_corr, ["Bonos", "Acciones"], bounds)


def test_datos_insuficientes(simple_cmas, simple_corr):
    with pytest.raises(OptimizationError, match="al menos un activo"):
        _opt(simple_cmas, simple_corr, [])
    with pytest.raises(OptimizationError, match="supuestos"):
        _opt(simple_cmas, simple_corr, ["Bonos", "No existe"])
    with pytest.raises(OptimizationError, match="estrategia"):
        optimize(_case(simple_cmas), "Z", ["Bonos"], simple_cmas, simple_corr)


def test_un_solo_activo_es_cien_por_ciento(simple_cmas, simple_corr):
    report = _opt(simple_cmas, simple_corr, ["Bonos"])
    for outcome in report.outcomes.values():
        assert outcome.stats.weights == {"Bonos": pytest.approx(1.0)}


def test_volatilidad_cero_no_divide_por_cero(deterministic_cmas, deterministic_corr):
    case = Scenario(initial_value=1.0, strategies=[
        Strategy(Allocation("A", {"Fijo": 1.0}))
    ])
    report = optimize(case, "A", ["Fijo", "U.S. Cash"], deterministic_cmas, deterministic_corr)
    assert report.outcomes[MIN_VOLATILITY].ok
    assert report.outcomes[MIN_VOLATILITY].stats.volatility == pytest.approx(0.0, abs=1e-6)
    assert not report.outcomes[MIN_VOLATILITY].stats.ratio_defined
    eff = report.outcomes[MAX_EFFICIENCY]
    assert not eff.ok and eff.stats is None
    assert "volatilidad cero" in eff.message


def test_retornos_negativos_no_dan_eficiencia_enganosa(simple_corr):
    cmas = CMASet([
        AssetClass("U.S. Cash", compound_return=-0.02, volatility=0.01),
        AssetClass("Bonos", compound_return=-0.03, volatility=0.05),
        AssetClass("Acciones", compound_return=-0.05, volatility=0.10),
    ])
    case = Scenario(initial_value=1.0, strategies=[Strategy(Allocation("A", {"Bonos": 1.0}))])
    report = optimize(case, "A", ["Bonos", "Acciones"], cmas, simple_corr)
    assert not report.outcomes[MAX_EFFICIENCY].ok
    assert "retorno" in report.outcomes[MAX_EFFICIENCY].message


def _cop_setup(simple_cmas, simple_corr):
    cop = AssetClass("TES", compound_return=0.10, volatility=0.08, origin=ORIGIN_CUSTOM,
                     asset_class=FIXED_INCOME, currency="COP")
    cmas = CMASet([*simple_cmas.assets, cop])
    m = np.eye(4)
    m[:3, :3] = simple_corr.matrix
    corr = CorrelationMatrix(names=[*simple_corr.names, "TES"], matrix=m)
    return cmas, corr


def test_activos_en_cop_se_convierten_antes_de_optimizar(simple_cmas, simple_corr):
    cmas, corr = _cop_setup(simple_cmas, simple_corr)
    sin_tasa = _case(simple_cmas)
    with pytest.raises(OptimizationError, match="tasa"):
        optimize(sin_tasa, "A", ["TES", "Bonos"], cmas, corr)

    peso = PesoAssumptions(spot=4_000.0, devaluation=0.05)
    report = optimize(_case(simple_cmas, peso=peso), "A", ["TES"], cmas, corr)
    stats = report.outcomes[MAX_RETURN].stats
    usd = cmas.by_name("TES").in_usd(0.05)
    assert stats.expected_return == pytest.approx(usd.arithmetic_return)
    assert stats.volatility == pytest.approx(usd.volatility)
    assert report.cop_assets == ["TES"]
    assert any("riesgo cambiario NO" in a for a in report.assumptions)


def test_optimizar_no_toca_el_caso(simple_cmas, simple_corr):
    case = _case(simple_cmas)
    before = to_dict(case)
    _opt(simple_cmas, simple_corr, ["Bonos", "Acciones"], case=case)
    assert to_dict(case) == before


def test_comparacion_con_el_portafolio_actual(simple_cmas, simple_corr):
    from gbp.engine.summary import summarize

    report = _opt(simple_cmas, simple_corr, ["Bonos", "Acciones"])
    current = summarize(Allocation("A", {"Bonos": 0.5, "Acciones": 0.5}), simple_cmas,
                        simple_corr.subset(["Bonos", "Acciones"]))
    assert report.current.expected_return == pytest.approx(current.arithmetic_return)
    assert report.current.volatility == pytest.approx(current.volatility)
    assert report.outcomes[MAX_EFFICIENCY].stats.ratio >= report.current.ratio - 1e-12


# --------------------------------------------------------------------------
# Aplicar una alternativa
# --------------------------------------------------------------------------


def test_aplicar_actualiza_pesos_marca_y_probabilidad_de_exito(window):
    _finish_run(window)
    strategy = window.scenario.strategies[0]
    before = window.results.base_result.by_name(strategy.name).success_probability
    flows = deepcopy(strategy.cashflows)

    assets = [n for n in strategy.asset_names][:4]
    report = optimize(window.scenario, strategy.name, assets, window.cmas, window.correlations)
    outcome = report.outcomes[MIN_VOLATILITY]
    window.apply_optimization(strategy.name, outcome.stats.weights, outcome.label,
                              simulate=False)

    assert strategy.optimization == outcome.label
    assert strategy.allocation.total == pytest.approx(1.0)
    assert set(strategy.asset_names) <= set(assets)
    assert strategy.cashflows == flows  # solo cambian los pesos
    assert window.optimized_banner.isVisibleTo(window)
    assert "★" in window.strategy_filter._buttons[strategy.name].text()

    _finish_run(window)
    after = window.results.base_result.by_name(strategy.name).success_probability
    assert window.kpis.success.value.text() == f"{after:.1%}"
    # Pesos de mínima volatilidad: otra corrida, otra probabilidad.
    assert after != before


def test_editar_a_mano_quita_la_marca_de_optimizado(window):
    strategy = window.scenario.strategies[0]
    window.apply_optimization(strategy.name, dict(strategy.weights), "Maximizar retorno",
                              simulate=False)
    assert strategy.optimization
    assert window.strategies_panel.current is strategy
    window.strategies_panel._normalize()
    assert strategy.optimization is None
    assert not window.optimized_banner.isVisibleTo(window)


def test_aplicar_como_nueva_conserva_la_original(window):
    original = window.scenario.strategies[0]
    weights = dict(original.weights)
    n = len(window.scenario.strategies)
    name = window.apply_optimization(original.name, {"U.S. Large Cap": 1.0},
                                     "Maximizar retorno", as_new=True, simulate=False)
    assert len(window.scenario.strategies) == n + 1
    assert dict(original.weights) == weights and original.optimization is None
    assert window.scenario.strategies[-1].name == name
    assert name in window.strategy_filter.selected


def test_dialogo_de_optimizacion_muestra_y_no_aplica_solo(window):
    from gbp.ui.optimizer_dialog import OptimizerDialog

    before = to_dict(window.scenario)
    dialog = OptimizerDialog(window)
    dialog.run()
    assert dialog.report is not None
    assert dialog.results_table.rowCount() > 4
    assert "Moneda base:" in dialog.context_label.text()
    assert dialog.apply_button.isEnabled()
    assert to_dict(window.scenario) == before  # nada cambia sin «Aplicar»

    dialog.set_checked([])
    dialog.run()
    assert dialog.report is None
    assert "No hay activos seleccionados" in dialog.message_label.text()
    assert not dialog.apply_button.isEnabled()
    dialog.close()
