"""Prueba de humo: replica el caso "Lifestyle" del ejemplo de J.P. Morgan.

Lámina 9 del PDF de referencia: USD 25.0MM iniciales, retiro de USD 1.1MM al año
de 2027 a 2055, inflación 2.5%, horizonte de 29 años. Los percentiles publicados
por J.P. Morgan para el escenario A son, en millones:

    año 15: 74 / 33 / 10      año 20: 98 / 35 / 3
    año 25: 134 / 37 / -6     año 29: 168 / 37 / -15

No tienen por qué coincidir exactamente —J.P. Morgan usa su propia asignación
subyacente y convenciones de flujo— pero deben quedar en el mismo orden de
magnitud. Este script imprime la comparación.

Uso:
    python tools/smoke_pdf_case.py
"""

from __future__ import annotations

from gbp.engine.montecarlo import simulate
from gbp.model.allocation import Allocation
from gbp.model.cashflows import CashFlow, FlowKind
from gbp.model.correlation import CorrelationMatrix
from gbp.model.scenario import Scenario, SimulationSettings
from gbp.model.strategy import Strategy
from gbp.io.library import seed_cmas

MM = 1_000_000

# Asignación aproximada del "Portafolio on 3 June 2026" de la lámina 7-8,
# mapeada a las clases que sí existen en la tabla USD del LTCMA.
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

PUBLISHED = {15: (74, 33, 10), 20: (98, 35, 3), 25: (134, 37, -6), 29: (168, 37, -15)}


def main() -> None:
    cmas = seed_cmas()
    correlations = CorrelationMatrix.load()

    allocation = Allocation("Portafolio on 3 June 2026", dict(PORTFOLIO_2026))
    print(f"Pesos de la estrategia suman {allocation.total:.4f}")
    allocation = allocation.normalized()

    scenario = Scenario(
        name="Lifestyle (lámina 9 del PDF)",
        initial_value=25.0 * MM,
        horizon=29,
        inflation=0.025,
        strategies=[
            Strategy(
                allocation=allocation,
                cashflows=[
                    CashFlow(
                        name="Gasto de estilo de vida",
                        kind=FlowKind.OUTFLOW,
                        amount=1.1 * MM,
                        start_year=1,
                        end_year=29,
                        inflation_indexed=True,
                    )
                ],
            )
        ],
    )

    result = simulate(
        scenario, cmas, correlations, SimulationSettings(n_paths=10_000, seed=42)
    )
    strategy = result.strategies[0]
    s = strategy.summary

    print("\nSupuestos resumen (JPM reporta 7.2% / 9.7% / 6.6% / 0.42):")
    print(f"  retorno de largo plazo : {s.arithmetic_return:6.2%}")
    print(f"  volatilidad            : {s.volatility:6.2%}")
    print(f"  retorno compuesto      : {s.compound_return:6.2%}")
    print(f"  yield                  : {s.yield_:6.2%}  (cero hasta cargarlo a mano)")
    print(f"  Sharpe                 : {s.sharpe_ratio:6.2f}")

    years = sorted(PUBLISHED)
    # La app muestra 10/25/50/75/90, pero J.P. Morgan publica p5 y p95: se piden
    # explícitamente para no perder la comparación contra la fuente.
    pct = strategy.percentiles(years, percentiles=(5, 50, 95))
    print("\nPatrimonio neto en millones (simulado vs. publicado por JPM)")
    print(f"{'Año':>5} {'p95':>16} {'p50':>16} {'p5':>16}")
    for i, year in enumerate(years):
        pub95, pub50, pub5 = PUBLISHED[year]
        print(
            f"{year:>5} "
            f"{pct[95][i] / MM:8.0f} vs {pub95:<4} "
            f"{pct[50][i] / MM:8.0f} vs {pub50:<4} "
            f"{pct[5][i] / MM:8.0f} vs {pub5:<4}"
        )

    print(f"\nProbabilidad de éxito: {strategy.success_probability:.1%} (JPM reporta 83.6%)")


if __name__ == "__main__":
    main()
