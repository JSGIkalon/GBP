"""Tests del apalancamiento: amortizacion, capitalizacion y margin call."""

from __future__ import annotations

import numpy as np
import pytest

from gbp.engine.montecarlo import simulate
from gbp.model.allocation import Allocation
from gbp.model.leverage import (
    Amortization,
    InterestMode,
    LoanSimulator,
    LoanTerms,
    RateMode,
)
from gbp.model.scenario import Scenario, SimulationSettings
from gbp.model.strategy import Strategy


# --------------------------------------------------------------------------
# Cronograma de amortizacion
# --------------------------------------------------------------------------


def test_bullet_no_amortiza_hasta_el_vencimiento():
    terms = LoanTerms(principal=100.0, term_years=5, amortization=Amortization.BULLET)
    fractions = terms.amortization_fractions()
    np.testing.assert_allclose(fractions, [0, 0, 0, 0, 1.0])


def test_lineal_amortiza_en_partes_iguales():
    terms = LoanTerms(principal=100.0, term_years=4, amortization=Amortization.LINEAR)
    np.testing.assert_allclose(terms.amortization_fractions(), [0.25] * 4)


def test_cuota_fija_reproduce_una_tabla_calculada_a_mano():
    """Credito de 100 a 10% por 3 anos: cuota = 40.2115, principal creciente."""
    terms = LoanTerms(
        principal=100.0, term_years=3, rate=0.10, amortization=Amortization.FRENCH
    )
    fractions = terms.amortization_fractions()
    # Cuota = 100 * 0.1 / (1 - 1.1^-3) = 40.21148
    # Ano 1: interes 10.00 -> principal 30.2115
    # Ano 2: interes  6.98 -> principal 33.2326
    # Ano 3: interes  3.66 -> principal 36.5559
    np.testing.assert_allclose(fractions, [0.302115, 0.332326, 0.365559], atol=1e-5)
    assert fractions.sum() == pytest.approx(1.0)


def test_todas_las_amortizaciones_suman_el_principal():
    for amortization in Amortization:
        terms = LoanTerms(principal=100.0, term_years=7, rate=0.06, amortization=amortization)
        assert terms.amortization_fractions().sum() == pytest.approx(1.0)


def test_tasa_de_referencia_usa_el_spread_sobre_caja():
    terms = LoanTerms(rate_mode=RateMode.SPREAD_OVER_CASH, spread=0.02)
    assert terms.reference_rate(cash_return=0.03) == pytest.approx(0.05)


# --------------------------------------------------------------------------
# Devengo y saldo
# --------------------------------------------------------------------------


def test_interes_pagado_sale_del_portafolio_y_no_engorda_el_saldo():
    terms = LoanTerms(
        principal=1000.0,
        term_years=3,
        rate=0.05,
        interest_mode=InterestMode.PAID,
        amortization=Amortization.BULLET,
    )
    sim = LoanSimulator(terms, n_paths=1, horizon=3)
    sim.drawdown(1)
    outflow = sim.accrue_and_amortize(1, np.array([0.05]))
    assert outflow[0] == pytest.approx(50.0)  # solo interes
    assert sim.balance[0] == pytest.approx(1000.0)  # el saldo no cambia


def test_interes_capitalizado_engorda_el_saldo_y_no_sale_del_portafolio():
    terms = LoanTerms(
        principal=1000.0,
        term_years=3,
        rate=0.05,
        interest_mode=InterestMode.CAPITALIZED,
        amortization=Amortization.BULLET,
    )
    sim = LoanSimulator(terms, n_paths=1, horizon=3)
    sim.drawdown(1)
    outflow = sim.accrue_and_amortize(1, np.array([0.05]))
    assert outflow[0] == pytest.approx(0.0)
    assert sim.balance[0] == pytest.approx(1050.0)


def test_el_saldo_queda_en_cero_al_vencimiento_con_interes_capitalizado():
    """El ultimo pago cancela tambien los intereses capitalizados."""
    terms = LoanTerms(
        principal=1000.0,
        term_years=3,
        rate=0.05,
        interest_mode=InterestMode.CAPITALIZED,
        amortization=Amortization.BULLET,
    )
    sim = LoanSimulator(terms, n_paths=1, horizon=3)
    sim.drawdown(1)
    total_out = 0.0
    for year in (1, 2, 3):
        total_out += sim.accrue_and_amortize(year, np.array([0.05]))[0]
    assert sim.balance[0] == pytest.approx(0.0)
    assert total_out == pytest.approx(1000.0 * 1.05**3)


def test_el_saldo_queda_en_cero_al_vencimiento_con_amortizacion_lineal():
    terms = LoanTerms(
        principal=900.0,
        term_years=3,
        rate=0.04,
        interest_mode=InterestMode.PAID,
        amortization=Amortization.LINEAR,
    )
    sim = LoanSimulator(terms, n_paths=1, horizon=3)
    sim.drawdown(1)
    for year in (1, 2, 3):
        sim.accrue_and_amortize(year, np.array([0.04]))
    assert sim.balance[0] == pytest.approx(0.0)


def test_no_devenga_fuera_del_plazo():
    terms = LoanTerms(principal=100.0, start_year=2, term_years=2, rate=0.05)
    sim = LoanSimulator(terms, n_paths=1, horizon=5)
    assert sim.accrue_and_amortize(1, np.array([0.05]))[0] == pytest.approx(0.0)
    sim.drawdown(2)
    assert sim.accrue_and_amortize(2, np.array([0.05]))[0] > 0
    sim.accrue_and_amortize(3, np.array([0.05]))
    assert sim.accrue_and_amortize(4, np.array([0.05]))[0] == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Margin call
# --------------------------------------------------------------------------


def test_margin_call_devuelve_el_ltv_al_objetivo():
    """Con deuda 70 y activos 100 y LTV maximo 0.6, se liquida hasta LTV 0.6."""
    terms = LoanTerms(principal=70.0, term_years=5, max_ltv=0.6)
    sim = LoanSimulator(terms, n_paths=1, horizon=5)
    sim.drawdown(1)
    assets = np.array([100.0])
    sale = sim.margin_call(assets)
    # d = (70 - 0.6*100) / (1 - 0.6) = 25
    assert sale[0] == pytest.approx(25.0)
    assert sim.balance[0] == pytest.approx(45.0)
    assert (sim.balance[0] / (assets[0] - sale[0])) == pytest.approx(0.6)
    assert sim.margin_calls[0] == 1


def test_margin_call_respeta_un_objetivo_mas_conservador():
    terms = LoanTerms(principal=70.0, term_years=5, max_ltv=0.6, target_ltv=0.5)
    sim = LoanSimulator(terms, n_paths=1, horizon=5)
    sim.drawdown(1)
    assets = np.array([100.0])
    sale = sim.margin_call(assets)
    # d = (70 - 0.5*100) / (1 - 0.5) = 40
    assert sale[0] == pytest.approx(40.0)
    assert sim.balance[0] / (assets[0] - sale[0]) == pytest.approx(0.5)


def test_no_hay_margin_call_dentro_del_limite():
    terms = LoanTerms(principal=40.0, term_years=5, max_ltv=0.6)
    sim = LoanSimulator(terms, n_paths=1, horizon=5)
    sim.drawdown(1)
    sale = sim.margin_call(np.array([100.0]))
    assert sale[0] == pytest.approx(0.0)
    assert sim.margin_calls[0] == 0


def test_sin_ltv_maximo_no_se_liquida_nunca():
    terms = LoanTerms(principal=95.0, term_years=5, max_ltv=None)
    sim = LoanSimulator(terms, n_paths=1, horizon=5)
    sim.drawdown(1)
    assert sim.margin_call(np.array([100.0]))[0] == pytest.approx(0.0)


def test_margin_call_no_vende_mas_de_lo_que_hay():
    """Si la deuda supera los activos, se liquida todo y no mas."""
    terms = LoanTerms(principal=150.0, term_years=5, max_ltv=0.6)
    sim = LoanSimulator(terms, n_paths=1, horizon=5)
    sim.drawdown(1)
    sale = sim.margin_call(np.array([100.0]))
    assert sale[0] == pytest.approx(100.0)
    assert sim.balance[0] == pytest.approx(50.0)


def test_margin_call_es_independiente_por_camino():
    terms = LoanTerms(principal=70.0, term_years=5, max_ltv=0.6)
    sim = LoanSimulator(terms, n_paths=3, horizon=5)
    sim.drawdown(1)
    # Solo el primer camino incumple el LTV.
    sale = sim.margin_call(np.array([100.0, 200.0, 300.0]))
    assert sale[0] > 0
    assert sale[1] == pytest.approx(0.0)
    assert sale[2] == pytest.approx(0.0)
    np.testing.assert_array_equal(sim.margin_calls, [1, 0, 0])


# --------------------------------------------------------------------------
# Integracion con el motor
# --------------------------------------------------------------------------


def _leveraged_scenario(loan: LoanTerms) -> Scenario:
    return Scenario(
        name="Con deuda",
        initial_value=1000.0,
        horizon=5,
        inflation=0.0,
        strategies=[
            Strategy(allocation=Allocation("Fijo", {"Fijo": 1.0}), loan=loan)
        ],
    )


def test_el_desembolso_entra_al_portafolio(deterministic_cmas, deterministic_corr):
    loan = LoanTerms(
        principal=500.0,
        start_year=1,
        term_years=5,
        rate=0.0,
        interest_mode=InterestMode.PAID,
        amortization=Amortization.BULLET,
    )
    result = simulate(
        _leveraged_scenario(loan),
        deterministic_cmas,
        deterministic_corr,
        SimulationSettings(n_paths=200, seed=1),
    )
    strategy = result.strategies[0]
    # Con tasa cero, los activos son (1000+500)*1.05 y la deuda sigue en 500.
    assert strategy.assets[:, 0].mean() == pytest.approx(1500.0 * 1.05)
    assert strategy.debt[:, 0].mean() == pytest.approx(500.0)
    assert strategy.wealth[:, 0].mean() == pytest.approx(1500.0 * 1.05 - 500.0)


def test_el_apalancamiento_amplifica_el_resultado(deterministic_cmas, deterministic_corr):
    """Si el portafolio rinde mas que la tasa, apalancarse deja mas patrimonio."""
    loan = LoanTerms(
        principal=500.0,
        term_years=5,
        rate=0.02,  # menor que el 5% del activo
        interest_mode=InterestMode.PAID,
        amortization=Amortization.BULLET,
    )
    settings = SimulationSettings(n_paths=200, seed=1)
    con = simulate(
        _leveraged_scenario(loan), deterministic_cmas, deterministic_corr, settings
    ).strategies[0]
    sin = simulate(
        _leveraged_scenario(LoanTerms(principal=0.0)),
        deterministic_cmas,
        deterministic_corr,
        settings,
    ).strategies[0]
    assert con.wealth[:, -1].mean() > sin.wealth[:, -1].mean()


def test_la_deuda_queda_saldada_al_final_del_plazo(deterministic_cmas, deterministic_corr):
    loan = LoanTerms(
        principal=500.0,
        term_years=5,
        rate=0.03,
        interest_mode=InterestMode.CAPITALIZED,
        amortization=Amortization.BULLET,
    )
    result = simulate(
        _leveraged_scenario(loan),
        deterministic_cmas,
        deterministic_corr,
        SimulationSettings(n_paths=200, seed=1),
    )
    assert result.strategies[0].debt[:, -1].max() == pytest.approx(0.0)


def test_margin_call_se_reporta_en_el_resultado(simple_cmas, simple_corr):
    """Un credito agresivo sobre un portafolio volatil dispara liquidaciones."""
    loan = LoanTerms(
        principal=900.0,
        term_years=10,
        rate=0.05,
        interest_mode=InterestMode.CAPITALIZED,
        amortization=Amortization.BULLET,
        max_ltv=0.5,
    )
    scenario = Scenario(
        name="Apalancado",
        initial_value=1000.0,
        horizon=10,
        inflation=0.0,
        strategies=[
            Strategy(allocation=Allocation("Acciones", {"Acciones": 1.0}), loan=loan)
        ],
    )
    result = simulate(
        scenario, simple_cmas, simple_corr, SimulationSettings(n_paths=2_000, seed=4)
    )
    strategy = result.strategies[0]
    assert strategy.margin_call_probability > 0.5
    assert strategy.forced_sales.max() > 0


def test_la_llamada_a_margen_no_crea_patrimonio(deterministic_cmas, deterministic_corr):
    """Vender activos para pagar deuda es neutro sobre el patrimonio neto.

    El motor descartaba el monto liquidado que devuelve `margin_call`, asi que
    bajaba la deuda pero dejaba los activos intactos: el patrimonio neto SUBIA
    al recibir una llamada a margen, y los anos siguientes capitalizaban sobre
    un portafolio que ya se habia vendido.
    """
    deterministic_cmas.by_name("Fijo").compound_return = -0.25
    loan = LoanTerms(
        principal=6_000_000.0, start_year=1, term_years=10, rate=0.05,
        max_ltv=0.60, target_ltv=0.50,
    )
    scenario = Scenario(
        name="Margen", initial_value=10_000_000.0, horizon=6, inflation=0.0,
        strategies=[Strategy(allocation=Allocation("Fijo", {"Fijo": 1.0}), loan=loan)],
    )
    result = simulate(
        scenario, deterministic_cmas, deterministic_corr,
        SimulationSettings(n_paths=100, seed=1),
    )
    s = result.strategies[0]
    assert s.margin_calls[0] > 0, "El caso no llego a disparar una llamada a margen"

    # El patrimonio neto nunca sube en un escenario que solo pierde valor.
    neto = s.wealth[0]
    assert np.all(np.diff(neto) <= 1e-6), (
        f"El patrimonio neto subio pese a que el portafolio solo cae: {neto}"
    )

    # Y tras la liquidacion el LTV queda en el objetivo, con activos reales.
    con_deuda = s.debt[0] > 0
    ltv = s.debt[0][con_deuda] / s.assets[0][con_deuda]
    assert ltv.max() <= 0.60 + 1e-9
