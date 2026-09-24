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
from gbp.model.scenario import Scenario, SimulationSettings
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


def test_la_vista_en_cop_escala_montos_y_no_toca_probabilidades(simple_cmas, simple_corr):
    usd = simulate(_caso(), simple_cmas, simple_corr, SETTINGS)
    cop = usd.in_currency(4_000.0)
    for a, b in zip(usd.strategies, cop.strategies):
        assert b.success_probability == a.success_probability
        assert b.last_year_change(True) == pytest.approx(a.last_year_change(True))
        np.testing.assert_allclose(b.percentiles([5, 15])[50], a.percentiles([5, 15])[50] * 4_000)
        assert b.cvar(15) == pytest.approx(a.cvar(15) * 4_000)
        np.testing.assert_allclose(b.flow_history()["retiros"], a.flow_history()["retiros"] * 4_000)
    assert cop.currency == "COP" and usd.currency == ""


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


def test_el_esquema_5_guarda_metas_y_tasa_y_el_4_abre_igual(simple_cmas, simple_corr):
    caso = _caso(goals=[Goal("Legado", 5_000_000.0)], fx_spot=4_150.5)
    vuelta = from_dict(json.loads(json.dumps(to_dict(caso))))
    assert vuelta.fx_spot == 4_150.5
    assert vuelta.goals[0].name == "Legado" and vuelta.goals[0].year is None

    viejo = to_dict(_caso())
    viejo["schema"] = 4
    viejo["scenario"].pop("goals")
    viejo["scenario"].pop("fx_spot")
    abierto = from_dict(viejo)
    assert abierto.goals == [] and abierto.fx_spot is None
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
    cop = build_report(tmp_path / "cop.pdf", ReportOptions(fx_spot=4_000.0), caso, result,
                       SETTINGS)
    assert _paginas(cop) == base

    con_meta = _caso(goals=[Goal("Legado", 1_000_000.0)])
    solve_result = solve(con_meta, "Mixta", Variable(FLOW, 0), Metric(SUCCESS), 0.8,
                         simple_cmas, simple_corr, SETTINGS)
    todo = build_report(
        tmp_path / "todo.pdf", ReportOptions(include_solve=True, solve=solve_result),
        con_meta, result, SETTINGS,
    )
    assert _paginas(todo) == base + 2
