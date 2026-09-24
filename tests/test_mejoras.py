"""Metas, solver, vista en COP y cifras completas.

Pocos tests y a propósito: cubren lo que protege las cifras que ve el cliente
—que nada cambie para quien no usa lo nuevo, que la conversión no mueva una
probabilidad, que el solver devuelva un valor que de verdad cumple— y no el
detalle de la interfaz, que se revisa a mano.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gbp.engine.montecarlo import draw_market, simulate, simulate_strategy
from gbp.engine.solver import CAPITAL, FLOW, SUCCESS, Metric, Variable, solve
from gbp.io.caseio import from_dict, to_dict
from gbp.io.report import ReportOptions, build_report
from gbp.model.allocation import Allocation
from gbp.model.cashflows import CashFlow, FlowKind
from gbp.model.goals import Goal, goal_probability
from gbp.model.scenario import PesoAssumptions, Scenario, SimulationSettings
from gbp.model.strategy import Strategy
from gbp.ui.theme import format_money

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def _caso(**extra) -> Scenario:
    return Scenario(
        name="Caso", initial_value=10_000_000.0, horizon=15, inflation=0.03,
        strategies=[
            Strategy(
                allocation=Allocation("Mixta", {"Acciones": 0.6, "Bonos": 0.4}),
                cashflows=[
                    CashFlow("Gasto", FlowKind.OUTFLOW, 700_000.0, 1, 15),
                    CashFlow("Aporte", FlowKind.INFLOW, 100_000.0, 1, 5),
                ],
            )
        ],
        **extra,
    )


SETTINGS = SimulationSettings(n_paths=2000, seed=7)


def test_las_cifras_del_motor_no_cambian():
    """Huella exacta del motor sobre tres casos que lo recorren entero.

    Protege lo que se prometió al optimizar: con la semilla 42, las mismas
    cifras bit a bit. Si un cambio legítimo del modelo las mueve, se regenera
    la referencia con `python tools/fingerprint.py --write` y se anota.
    """
    sys.path.insert(0, str(TOOLS))
    import fingerprint

    reference = json.loads(fingerprint.REFERENCE.read_text(encoding="utf-8"))
    assert fingerprint.compare(fingerprint.compute(reference["n_paths"]), reference) == []


def test_las_cifras_se_muestran_completas_con_punto_de_miles():
    assert format_money(25_000_000) == "25.000.000"
    assert format_money(-1_100_000.4) == "-1.100.000"
    assert format_money(999) == "999"
    assert format_money(-0.2) == "0"


def test_la_escala_de_lectura_divide_y_dice_su_unidad():
    from gbp.ui.theme import amount_unit, format_display, set_display_scale

    try:
        assert format_display(25_000_000) == "25.000.000" and amount_unit() == ""
        set_display_scale("millones")
        assert format_display(25_000_000) == "25,0"
        assert format_display(1_154_785) == "1,2"
        assert amount_unit("COP") == "millones de COP"
        set_display_scale("miles")
        assert format_display(1_154_785) == "1.154,8"
    finally:
        set_display_scale("normal")  # estado global: no se filtra a otros tests


def test_la_vista_en_cop_convierte_con_la_tasa_de_cada_anio(simple_cmas, simple_corr):
    peso = PesoAssumptions(spot=4_000.0, devaluation=0.03)
    usd = simulate(_caso(), simple_cmas, simple_corr, SETTINGS)
    cop = usd.in_currency(peso, 0.03)
    for a, b in zip(usd.strategies, cop.strategies):
        assert b.success_probability == a.success_probability
        # Patrimonio del año 15 a la tasa de cierre de ese año.
        np.testing.assert_allclose(b.percentiles([15])[50], a.percentiles([15])[50] * peso.rate(15))
        assert b.cvar(15) == pytest.approx(a.cvar(15) * peso.rate(15))
        # Flujos del año t a la tasa con que se pagan, S_(t−1).
        retiros = a.flow_history()["retiros"] * [peso.rate(t) for t in range(15)]
        np.testing.assert_allclose(b.flow_history()["retiros"], retiros)
    assert cop.currency == "COP" and usd.currency == ""


def test_un_activo_en_cop_rinde_en_dolares_neto_de_devaluacion():
    from gbp.model.assets import AssetClass

    tes = AssetClass("TES", 0.10, 0.08, origin="custom", asset_class="Renta fija",
                     currency="COP")
    usd = tes.in_usd(0.04)
    assert usd.compound_return == pytest.approx(1.10 / 1.04 - 1)
    # Dividir por una constante no cambia la dispersión en logaritmos.
    assert usd.sigma_log == pytest.approx(tes.sigma_log)
    assert tes.in_usd(0.0).compound_return == pytest.approx(0.10)


def test_un_flujo_en_cop_se_indexa_en_pesos_y_se_convierte_cada_anio():
    peso = PesoAssumptions(spot=4_000.0, devaluation=0.03, inflation=0.05)
    gasto = CashFlow("Gasto", FlowKind.OUTFLOW, 400_000_000.0, 1, 3, currency="COP")
    usd = -gasto.schedule(3, 0.02, peso)
    esperado = [400e6 * 1.05 ** k / (4_000 * 1.03 ** k) for k in range(3)]
    np.testing.assert_allclose(usd, esperado)
    # Con la inflación de paridad cuesta en dólares lo mismo que uno en USD.
    paridad = PesoAssumptions(spot=4_000.0, devaluation=0.03)
    en_usd = CashFlow("G", FlowKind.OUTFLOW, 100_000.0, 1, 3)
    np.testing.assert_allclose(
        CashFlow("G", FlowKind.OUTFLOW, 400_000_000.0, 1, 3, currency="COP")
        .schedule(3, 0.02, paridad),
        en_usd.schedule(3, 0.02),
    )


def test_un_caso_con_cifras_en_cop_sin_tasa_no_corre(simple_cmas, simple_corr):
    caso = _caso()
    caso.strategies[0].cashflows[0].currency = "COP"
    with pytest.raises(ValueError, match="tasa USD/COP"):
        simulate(caso, simple_cmas, simple_corr, SETTINGS)
    caso.peso = PesoAssumptions(spot=4_000.0)
    simulate(caso, simple_cmas, simple_corr, SETTINGS)


def test_una_meta_se_cumple_segun_el_patrimonio_de_su_anio(simple_cmas, simple_corr):
    result = simulate(_caso(), simple_cmas, simple_corr, SETTINGS).strategies[0]
    alcanzable = goal_probability(result, Goal("Cero", 0.0, year=10))
    imposible = goal_probability(result, Goal("Luna", 1e15, year=10))
    assert alcanzable == pytest.approx(float((result.wealth[:, :10] > 0).all(axis=1).mean()))
    assert imposible == 0.0
    # En moneda de hoy la misma cifra es más exigente que en nominal.
    real = goal_probability(result, Goal("R", 10_000_000.0, year=15, real=True))
    nominal = goal_probability(result, Goal("N", 10_000_000.0, year=15, real=False))
    assert real <= nominal
    assert np.isnan(goal_probability(result, Goal("Tarde", 1.0, year=40)))


def _probabilidad(scenario, cmas, corr, value, variable):
    """La probabilidad de éxito con la cifra cambiada, sobre el mismo mercado."""
    from copy import deepcopy

    market = draw_market(scenario, cmas, corr, SETTINGS)
    strategy = deepcopy(scenario.strategies[0])
    if variable.kind == CAPITAL:
        strategy.initial_value = value
    else:
        strategy.cashflows[variable.flow_index].amount = value
    r = simulate_strategy(strategy, scenario.horizon, scenario.inflation,
                          scenario.initial_value, cmas, market)
    return r.success_probability


def test_el_solver_encuentra_el_retiro_maximo_que_cumple(simple_cmas, simple_corr):
    caso = _caso()
    variable = Variable(FLOW, 0)
    r = solve(caso, "Mixta", variable, Metric(SUCCESS), 0.85, simple_cmas, simple_corr, SETTINGS)
    assert r.found and r.maximize
    assert _probabilidad(caso, simple_cmas, simple_corr, r.value, variable) >= 0.85
    # Un poco más de retiro ya no cumple: es el borde, no un valor cualquiera.
    assert _probabilidad(caso, simple_cmas, simple_corr, r.value * 1.01, variable) < 0.85
    # El caso no se tocó.
    assert caso.strategies[0].cashflows[0].amount == 700_000.0


def test_el_solver_encuentra_el_capital_minimo_que_cumple(simple_cmas, simple_corr):
    caso = _caso()
    variable = Variable(CAPITAL)
    r = solve(caso, "Mixta", variable, Metric(SUCCESS), 0.95, simple_cmas, simple_corr, SETTINGS)
    assert r.found and not r.maximize
    assert _probabilidad(caso, simple_cmas, simple_corr, r.value, variable) >= 0.95
    assert _probabilidad(caso, simple_cmas, simple_corr, r.value * 0.99, variable) < 0.95
    assert caso.strategies[0].initial_value is None


def test_el_solver_avisa_si_el_objetivo_es_inalcanzable(simple_cmas, simple_corr):
    caso = _caso()
    # Otro retiro, que el solver no ajusta, agota el portafolio por sí solo:
    # ni llevando a cero el que sí ajusta se llega al objetivo.
    caso.strategies[0].cashflows.append(
        CashFlow("Enorme", FlowKind.OUTFLOW, 5_000_000.0, 1, 15)
    )
    r = solve(caso, "Mixta", Variable(FLOW, 0), Metric(SUCCESS), 0.9,
              simple_cmas, simple_corr, SETTINGS)
    assert r.value is None and "cero" in r.message


def test_el_esquema_6_guarda_metas_pesos_y_monedas_y_el_4_abre_igual(simple_cmas, simple_corr):
    caso = _caso(goals=[Goal("Legado", 5_000_000.0)],
                 peso=PesoAssumptions(spot=4_150.5, devaluation=0.03))
    caso.strategies[0].cashflows[0].currency = "COP"
    guardado = json.loads(json.dumps(to_dict(caso)))
    guardado["scenario"]["fx_spot"] = 1.0  # de una versión intermedia: se ignora
    vuelta = from_dict(guardado)
    assert vuelta.goals[0].name == "Legado" and vuelta.goals[0].year is None
    assert vuelta.peso.spot == 4_150.5 and vuelta.peso.inflation is None
    assert vuelta.strategies[0].cashflows[0].currency == "COP"

    viejo = to_dict(_caso())
    viejo["schema"] = 4
    viejo["scenario"].pop("goals")
    abierto = from_dict(viejo)
    assert abierto.goals == []
    a = simulate(abierto, simple_cmas, simple_corr, SETTINGS).strategies[0].wealth
    b = simulate(_caso(), simple_cmas, simple_corr, SETTINGS).strategies[0].wealth
    assert np.array_equal(a, b)


def _paginas(path) -> int:
    return max(int(n) for n in re.findall(rb"/Count\s*(\d+)", path.read_bytes()))


def test_el_informe_solo_suma_laminas_si_se_piden(tmp_path, simple_cmas, simple_corr):
    caso = _caso()
    result = simulate(caso, simple_cmas, simple_corr, SETTINGS)
    base = _paginas(build_report(tmp_path / "base.pdf", ReportOptions(), caso, result, SETTINGS))

    # En COP es el mismo documento: mismas páginas, otras cifras.
    cop = build_report(tmp_path / "cop.pdf",
                       ReportOptions(peso=PesoAssumptions(spot=4_000.0, devaluation=0.03)),
                       caso, result, SETTINGS)
    assert _paginas(cop) == base

    con_meta = _caso(goals=[Goal("Legado", 1_000_000.0)])
    solve_result = solve(con_meta, "Mixta", Variable(FLOW, 0), Metric(SUCCESS), 0.8,
                         simple_cmas, simple_corr, SETTINGS)
    todo = build_report(
        tmp_path / "todo.pdf", ReportOptions(include_solve=True, solve=solve_result),
        con_meta, result, SETTINGS,
    )
    assert _paginas(todo) == base + 2
