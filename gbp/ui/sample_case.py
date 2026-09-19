"""Caso de ejemplo que se carga al abrir la app por primera vez.

Reproduce el caso del PDF de referencia de J.P. Morgan, mapeado a las clases de
activo que existen en la tabla USD del LTCMA, para que la app abra con algo
funcionando en vez de una pantalla vacía.
"""

from __future__ import annotations

from ..model.allocation import Allocation
from ..model.cashflows import CashFlow, FlowKind
from ..model.scenario import Scenario
from ..model.strategy import Strategy

MM = 1_000_000

PORTFOLIO_2026 = {
    "Emerging Markets Corporate Bonds": 0.032,
    "World Government Bonds hedged": 0.147,
    "U.S. High Yield Bonds": 0.018,
    "U.S. Cash": 0.073,
    "U.S. Muni 1-15 Yr Blend": 0.029,
    "U.S. Short Duration Government/Credit": 0.009,
    "AC World Equity": 0.078,
    "EAFE Equity": 0.005,
    "Emerging Markets Equity": 0.119,
    "U.S. Large Cap": 0.234,
    "Direct Lending": 0.184,
    "Global Core Infrastructure": 0.065,
    "U.S. Core Real Estate": 0.007,
}

BALANCED_30_PI = {
    "World Government Bonds hedged": 0.315,
    "AC World Equity": 0.385,
    "Direct Lending": 0.150,
    "Global Core Infrastructure": 0.050,
    "Global Core Transport": 0.050,
    "U.S. Core Real Estate": 0.050,
}

GROWTH_20_PI = {
    "U.S. Aggregate Bonds": 0.250,
    "AC World Equity": 0.550,
    "Private Equity": 0.140,
    "Venture Capital": 0.060,
}


def _lifestyle_spending() -> CashFlow:
    """El gasto de estilo de vida del ejemplo: 1.1MM al año, indexado."""
    return CashFlow(
        name="Gasto de estilo de vida",
        kind=FlowKind.OUTFLOW,
        amount=1.1 * MM,
        start_year=1,
        end_year=29,
        inflation_indexed=True,
    )


def build_sample_case() -> Scenario:
    """Caso de ejemplo: tres estrategias con el mismo gasto de estilo de vida.

    Cada estrategia lleva su propia copia del gasto, así que se puede cambiar el
    de una sin tocar las otras — que es justamente para lo que sirve tener los
    flujos por estrategia.
    """
    return Scenario(
        name="Ejemplo — Lifestyle (basado en el PDF de referencia)",
        initial_value=25.0 * MM,
        horizon=29,
        inflation=0.025,
        strategies=[
            Strategy(
                allocation=Allocation("Portafolio actual", dict(PORTFOLIO_2026)),
                cashflows=[_lifestyle_spending()],
            ),
            Strategy(
                allocation=Allocation("Balanceado con 30% PI", dict(BALANCED_30_PI)),
                cashflows=[_lifestyle_spending()],
            ),
            Strategy(
                allocation=Allocation("Growth con 20% PI", dict(GROWTH_20_PI)),
                cashflows=[_lifestyle_spending()],
            ),
        ],
    )


def empty_case() -> Scenario:
    return Scenario(
        name="Caso sin título",
        initial_value=0.0,
        horizon=30,
        inflation=0.025,
        strategies=[Strategy(allocation=Allocation("Estrategia 1", {}))],
    )
