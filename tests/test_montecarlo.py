"""Tests del motor Monte Carlo."""

from __future__ import annotations

import numpy as np
import pytest

from gbp.engine.montecarlo import simulate
from gbp.model.allocation import Allocation
from gbp.model.cashflows import CashFlow, FlowKind
from gbp.model.scenario import Scenario, SimulationSettings
from gbp.model.strategy import Strategy


def _strategy(name: str, weights: dict, **kwargs) -> Strategy:
    return Strategy(allocation=Allocation(name, weights), **kwargs)


def _scenario(cashflows=None, **kwargs) -> Scenario:
    """Escenario de prueba.

    `cashflows` es un atajo: los aplica a todas las estrategias, que es lo que
    hacían estos tests cuando los flujos vivían en el escenario.
    """
    defaults = dict(
        name="Test",
        initial_value=1_000_000.0,
        horizon=10,
        inflation=0.0,
        strategies=[_strategy("Fijo", {"Fijo": 1.0})],
    )
    defaults.update(kwargs)
    scenario = Scenario(**defaults)
    if cashflows:
        from copy import deepcopy

        for strategy in scenario.strategies:
            strategy.cashflows = [deepcopy(f) for f in cashflows]
    return scenario


def test_sin_volatilidad_crece_al_retorno_compuesto(deterministic_cmas, deterministic_corr):
    """Sin volatilidad ni flujos, el patrimonio sigue exactamente V0*(1+g)^n."""
    scenario = _scenario()
    result = simulate(
        scenario, deterministic_cmas, deterministic_corr, SimulationSettings(n_paths=200, seed=1)
    )
    wealth = result.strategies[0].wealth
    expected = 1_000_000.0 * 1.05 ** np.arange(1, 11)
    np.testing.assert_allclose(wealth.mean(axis=0), expected, rtol=1e-10)
    # Todos los caminos deben ser identicos: sin volatilidad no hay dispersion.
    assert wealth.std(axis=0).max() < 1e-6


def test_mediana_converge_al_crecimiento_compuesto(simple_cmas, simple_corr):
    """Con lognormales, la mediana del patrimonio es V0*(1+compuesto)^n."""
    scenario = _scenario(
        horizon=20, strategies=[_strategy("Acciones", {"Acciones": 1.0})]
    )
    result = simulate(
        scenario, simple_cmas, simple_corr, SimulationSettings(n_paths=60_000, seed=7)
    )
    median = np.median(result.strategies[0].wealth[:, -1])
    assert median == pytest.approx(1_000_000.0 * 1.07**20, rel=0.03)


def test_media_converge_al_retorno_aritmetico(simple_cmas, simple_corr):
    """La media del patrimonio sigue el retorno aritmetico, no el compuesto."""
    scenario = _scenario(
        horizon=15, strategies=[_strategy("Acciones", {"Acciones": 1.0})]
    )
    result = simulate(
        scenario, simple_cmas, simple_corr, SimulationSettings(n_paths=80_000, seed=11)
    )
    arithmetic = simple_cmas.by_name("Acciones").arithmetic_return
    expected = 1_000_000.0 * (1 + arithmetic) ** 15
    assert result.strategies[0].wealth[:, -1].mean() == pytest.approx(expected, rel=0.04)


def test_correlacion_simulada_reproduce_la_matriz(simple_cmas, simple_corr):
    """Los retornos sorteados respetan la correlacion pedida."""
    from gbp.engine.montecarlo import _simulate_asset_returns

    names = ["U.S. Cash", "Bonos", "Acciones"]
    rng = np.random.default_rng(3)
    gross = _simulate_asset_returns(
        names, simple_cmas, simple_corr.subset(names), 100_000, 1, rng
    )
    realized = np.corrcoef(np.log(gross[:, 0, :]).T)
    np.testing.assert_allclose(realized, simple_corr.subset(names), atol=0.02)


def test_aportes_y_retiros_se_aplican(deterministic_cmas, deterministic_corr):
    """Un aporte y un retiro deterministicos dan un resultado calculable a mano."""
    scenario = _scenario(
        horizon=2,
        initial_value=100.0,
        cashflows=[
            CashFlow("Aporte", FlowKind.INFLOW, 50.0, 1, 1, inflation_indexed=False),
            CashFlow("Retiro", FlowKind.OUTFLOW, 20.0, 2, 2, inflation_indexed=False),
        ],
    )
    result = simulate(
        scenario, deterministic_cmas, deterministic_corr, SimulationSettings(n_paths=200, seed=2)
    )
    wealth = result.strategies[0].wealth.mean(axis=0)
    # Ano 1: (100 + 50) * 1.05 = 157.5 ; ano 2: 157.5 * 1.05 - 20 = 145.375
    assert wealth[0] == pytest.approx(157.5)
    assert wealth[1] == pytest.approx(145.375)


def test_flujos_se_indexan_a_la_inflacion(deterministic_cmas, deterministic_corr):
    """Un retiro indexado crece con la inflacion desde el primer ano."""
    scenario = _scenario(
        horizon=2,
        initial_value=1000.0,
        inflation=0.10,
        cashflows=[CashFlow("Gasto", FlowKind.OUTFLOW, 100.0, 1, 2)],
    )
    result = simulate(
        scenario, deterministic_cmas, deterministic_corr, SimulationSettings(n_paths=200, seed=2)
    )
    wealth = result.strategies[0].wealth.mean(axis=0)
    # Ano 1: 1000*1.05 - 110 = 940 ; ano 2: 940*1.05 - 121 = 866
    assert wealth[0] == pytest.approx(940.0)
    assert wealth[1] == pytest.approx(866.0)


def test_misma_semilla_da_el_mismo_resultado(simple_cmas, simple_corr):
    scenario = _scenario(strategies=[_strategy("Mixto", {"Bonos": 0.4, "Acciones": 0.6})])
    settings = SimulationSettings(n_paths=1_000, seed=99)
    a = simulate(scenario, simple_cmas, simple_corr, settings)
    b = simulate(scenario, simple_cmas, simple_corr, settings)
    np.testing.assert_array_equal(a.strategies[0].wealth, b.strategies[0].wealth)


def test_estrategias_comparten_los_mismos_sorteos(simple_cmas, simple_corr):
    """Dos estrategias identicas con nombres distintos dan resultados identicos."""
    scenario = _scenario(
        strategies=[
            _strategy("A", {"Bonos": 0.5, "Acciones": 0.5}),
            _strategy("B", {"Bonos": 0.5, "Acciones": 0.5}),
        ]
    )
    result = simulate(
        scenario, simple_cmas, simple_corr, SimulationSettings(n_paths=500, seed=5)
    )
    np.testing.assert_allclose(result.by_name("A").wealth, result.by_name("B").wealth)


def test_probabilidad_de_exito_cae_con_retiros_grandes(simple_cmas, simple_corr):
    """Retirar mas de lo que rinde el portafolio agota el patrimonio."""
    modest = _scenario(
        horizon=20,
        strategies=[_strategy("Mixto", {"Bonos": 0.5, "Acciones": 0.5})],
        cashflows=[CashFlow("Gasto", FlowKind.OUTFLOW, 20_000.0, 1, 20)],
    )
    heavy = _scenario(
        horizon=20,
        strategies=[_strategy("Mixto", {"Bonos": 0.5, "Acciones": 0.5})],
        cashflows=[CashFlow("Gasto", FlowKind.OUTFLOW, 120_000.0, 1, 20)],
    )
    settings = SimulationSettings(n_paths=3_000, seed=13)
    p_modest = simulate(modest, simple_cmas, simple_corr, settings).strategies[0]
    p_heavy = simulate(heavy, simple_cmas, simple_corr, settings).strategies[0]
    assert p_modest.success_probability > 0.99
    assert p_heavy.success_probability < 0.5


def test_valores_reales_descuentan_la_inflacion(deterministic_cmas, deterministic_corr):
    scenario = _scenario(horizon=5, inflation=0.02)
    result = simulate(
        scenario, deterministic_cmas, deterministic_corr, SimulationSettings(n_paths=200, seed=2)
    )
    strategy = result.strategies[0]
    nominal = strategy.values(real=False)[:, -1].mean()
    real = strategy.values(real=True)[:, -1].mean()
    assert real == pytest.approx(nominal / 1.02**5)


def test_escenario_invalido_se_rechaza(simple_cmas, simple_corr):
    scenario = _scenario(strategies=[_strategy("Mala", {"Acciones": 0.8})])
    with pytest.raises(ValueError, match="sumar 100%"):
        simulate(scenario, simple_cmas, simple_corr, SimulationSettings(n_paths=100))


# --------------------------------------------------------------------------
# Estrategias independientes: cada una con sus flujos, credito y capital
# --------------------------------------------------------------------------


def test_cada_estrategia_usa_sus_propios_flujos(deterministic_cmas, deterministic_corr):
    """Dos estrategias identicas salvo por sus retiros dan resultados distintos."""
    con_retiro = _strategy(
        "Con retiro",
        {"Fijo": 1.0},
        cashflows=[CashFlow("Gasto", FlowKind.OUTFLOW, 100.0, 1, 2, inflation_indexed=False)],
    )
    sin_retiro = _strategy("Sin retiro", {"Fijo": 1.0})

    scenario = _scenario(horizon=2, initial_value=1000.0,
                         strategies=[con_retiro, sin_retiro])
    result = simulate(
        scenario, deterministic_cmas, deterministic_corr, SimulationSettings(n_paths=200, seed=1)
    )

    # Sin retiros: 1000*1.05^2 = 1102.5
    assert result.by_name("Sin retiro").wealth[:, -1].mean() == pytest.approx(1102.5)
    # Con retiro de 100 al final de cada ano:
    #   ano 1: 1000*1.05 - 100 = 950 ; ano 2: 950*1.05 - 100 = 897.5
    assert result.by_name("Con retiro").wealth[:, -1].mean() == pytest.approx(897.5)


def test_cada_estrategia_usa_su_propio_credito(deterministic_cmas, deterministic_corr):
    """Una estrategia apalancada y otra sin deuda, sobre los mismos sorteos."""
    from gbp.model.leverage import Amortization, InterestMode, LoanTerms

    loan = LoanTerms(
        principal=500.0,
        term_years=5,
        rate=0.0,
        interest_mode=InterestMode.PAID,
        amortization=Amortization.BULLET,
    )
    scenario = _scenario(
        horizon=3,
        initial_value=1000.0,
        strategies=[
            _strategy("Apalancada", {"Fijo": 1.0}, loan=loan),
            _strategy("Sin deuda", {"Fijo": 1.0}),
        ],
    )
    result = simulate(
        scenario, deterministic_cmas, deterministic_corr, SimulationSettings(n_paths=200, seed=1)
    )

    apalancada = result.by_name("Apalancada")
    sin_deuda = result.by_name("Sin deuda")

    assert apalancada.debt[:, 0].mean() == pytest.approx(500.0)
    assert sin_deuda.debt.max() == pytest.approx(0.0)
    # Con tasa cero y activo al 5%, apalancarse deja mas patrimonio.
    assert apalancada.wealth[:, -1].mean() > sin_deuda.wealth[:, -1].mean()


def test_capital_propio_manda_sobre_el_del_escenario(deterministic_cmas, deterministic_corr):
    scenario = _scenario(
        horizon=1,
        initial_value=1000.0,
        strategies=[
            _strategy("Hereda", {"Fijo": 1.0}),
            _strategy("Propio", {"Fijo": 1.0}, initial_value=4000.0),
        ],
    )
    result = simulate(
        scenario, deterministic_cmas, deterministic_corr, SimulationSettings(n_paths=200, seed=1)
    )
    assert result.by_name("Hereda").wealth[:, 0].mean() == pytest.approx(1050.0)
    assert result.by_name("Propio").wealth[:, 0].mean() == pytest.approx(4200.0)


def test_duplicar_una_estrategia_no_comparte_sus_flujos():
    """La copia debe ser independiente: editar una no puede tocar la otra."""
    original = _strategy(
        "Original",
        {"Fijo": 1.0},
        cashflows=[CashFlow("Gasto", FlowKind.OUTFLOW, 100.0, 1, 5)],
    )
    copia = original.copy("Copia")
    copia.cashflows[0].amount = 999.0
    copia.allocation.weights["Fijo"] = 0.5

    assert original.cashflows[0].amount == 100.0
    assert original.weights["Fijo"] == 1.0
    assert copia.name == "Copia"


def test_los_hitos_respetan_lo_configurado():
    """milestones_within ya no agrega el horizonte por su cuenta."""
    settings = SimulationSettings(milestone_years=[5, 10, 15, 20])
    assert settings.milestones_within(29) == [5, 10, 15, 20]
    assert settings.milestones_within(12) == [5, 10]


def test_una_estrategia_sin_capital_ni_aportes_se_rechaza(simple_cmas, simple_corr):
    scenario = _scenario(
        initial_value=0.0,
        strategies=[_strategy("Vacia", {"Acciones": 1.0})],
    )
    with pytest.raises(ValueError, match="Vacia"):
        scenario.validate(simple_cmas)


def test_clase_desconocida_se_rechaza(simple_cmas, simple_corr):
    scenario = _scenario(strategies=[_strategy("Rara", {"Cripto": 1.0})])
    with pytest.raises(ValueError, match="Cripto"):
        simulate(scenario, simple_cmas, simple_corr, SimulationSettings(n_paths=100))
