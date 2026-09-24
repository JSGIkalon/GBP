"""Figuras de MODELO.md, generadas con el motor real de la app.

Cada figura sale de las mismas funciones que usa GBP —el sorteo, la proyección
de una estrategia, el crédito, el solver—, no de una ilustración aparte. Si el
modelo cambia, se vuelve a correr y el documento muestra lo que la app hace.

    python tools/make_modelo_figures.py

Escribe los PNG en docs/img/ e imprime las cifras de los ejemplos resueltos a
mano del documento, para poder contrastarlas.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from gbp.engine.montecarlo import Market, draw_market, simulate, simulate_strategy  # noqa: E402
from gbp.engine.solver import FLOW, SUCCESS, Metric, Variable, solve  # noqa: E402
from gbp.io.library import seed_cmas  # noqa: E402
from gbp.model.allocation import Allocation  # noqa: E402
from gbp.model.assets import AssetClass, CMASet  # noqa: E402
from gbp.model.cashflows import CashFlow, FlowBasis, FlowKind  # noqa: E402
from gbp.model.correlation import CorrelationMatrix  # noqa: E402
from gbp.model.leverage import Amortization, LoanSimulator, LoanTerms  # noqa: E402
from gbp.model.scenario import Scenario, SimulationSettings  # noqa: E402
from gbp.model.strategy import Strategy  # noqa: E402
from gbp.ui.sample_case import build_sample_case  # noqa: E402
from gbp.ui.theme import (  # noqa: E402
    BLUE_LIGHT,
    CYAN,
    INK,
    INK_SOFT,
    LEADER,
    NAVY,
    NEUTRAL,
    SERIES_FOURTH,
    apply_matplotlib_style,
    clean_axes,
    format_money,
    money_axis,
)

OUT = ROOT / "docs" / "img"
MM = 1_000_000


def _save(fig, name: str):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT / name, dpi=130)
    plt.close(fig)
    print(f"  docs/img/{name}")


def fig_normal_vs_lognormal():
    """Mismo retorno esperado y volatilidad: la normal permite perder más del 100%."""
    mean, vol = 0.08, 0.35
    x = np.linspace(-1.6, 2.2, 800)
    normal = np.exp(-0.5 * ((x - mean) / vol) ** 2) / (vol * np.sqrt(2 * np.pi))
    sigma_log = np.sqrt(np.log1p((vol / (1 + mean)) ** 2))
    mu_log = np.log(1 + mean) - sigma_log**2 / 2
    g = 1 + x
    logn = np.where(g > 0, np.exp(-0.5 * ((np.log(np.clip(g, 1e-12, None)) - mu_log) / sigma_log) ** 2)
                    / (np.clip(g, 1e-12, None) * sigma_log * np.sqrt(2 * np.pi)), 0.0)
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.plot(x * 100, normal, color=LEADER, linewidth=2, label="Normal")
    ax.plot(x * 100, logn, color=NAVY, linewidth=2, label="Lognormal (la de GBP)")
    ax.fill_between(x * 100, 0, normal, where=x < -1, color=CYAN, alpha=0.5,
                    label="Pérdidas mayores al 100%: imposibles")
    ax.axvline(-100, color=INK_SOFT, linewidth=1, linestyle="--")
    ax.set_xlabel("Retorno en un año (%)")
    ax.set_yticks([])
    ax.legend(loc="upper right")
    clean_axes(ax)
    _save(fig, "01_normal_vs_lognormal.png")


def fig_volatility_drag():
    """Mismo retorno aritmético, distinta volatilidad: compone distinto."""
    years = np.arange(0, 31)
    arith = 0.08
    fig, ax = plt.subplots(figsize=(8, 3.6))
    for vol, color in ((0.0, LEADER), (0.10, CYAN), (0.20, NAVY), (0.30, SERIES_FOURTH)):
        sigma_log_sq = np.log1p((vol / (1 + arith)) ** 2)
        compound = np.exp(np.log1p(arith) - sigma_log_sq / 2) - 1
        ax.plot(years, 100 * (1 + compound) ** years, color=color, linewidth=2,
                label=f"Volatilidad {vol:.0%} → compone al {compound:.2%}")
    ax.set_xlabel("Año")
    ax.set_ylabel("Valor de 100 invertidos (mediana)")
    ax.legend(loc="upper left")
    clean_axes(ax)
    _save(fig, "02_arrastre_volatilidad.png")


def fig_correlation():
    """60/40 con correlación 0, la estimada y 1: la dispersión cambia con ella."""
    cmas = CMASet([
        AssetClass("U.S. Cash", 0.03, 0.005),
        AssetClass("Acciones", 0.07, 0.16),
        AssetClass("Bonos", 0.045, 0.06),
    ])
    fig, ax = plt.subplots(figsize=(8, 3.6))
    # «Correlación» con letras: la tipografía de la marca no trae la rho griega.
    for rho, color, label in ((0.0, LEADER, "Correlación 0"), (0.3, CYAN, "Correlación 0,3"),
                              (0.95, NAVY, "Correlación 0,95")):
        corr = CorrelationMatrix(["U.S. Cash", "Acciones", "Bonos"], np.array(
            [[1, 0, 0], [0, 1, rho], [0, rho, 1]], dtype=float))
        sc = Scenario(initial_value=100.0, horizon=1, strategies=[Strategy(
            Allocation("60/40", {"Acciones": 0.6, "Bonos": 0.4}))])
        r = simulate(sc, cmas, corr, SimulationSettings(n_paths=200_000)).strategies[0]
        ret = r.wealth[:, 0] / 100 - 1
        ax.hist(ret * 100, bins=160, histtype="step", linewidth=1.8, color=color, density=True,
                label=f"{label}: volatilidad {ret.std():.1%}")
    ax.set_xlabel("Retorno del portafolio 60/40 en un año (%)")
    ax.set_yticks([])
    ax.legend()
    clean_axes(ax)
    _save(fig, "03_correlacion.png")


def fig_fan(result):
    """Caminos individuales y percentiles del caso de ejemplo."""
    s = result.strategies[0]
    years = np.arange(0, s.horizon + 1)
    wealth = np.column_stack([np.full(s.n_paths, s.initial_value), s.wealth])
    fig, ax = plt.subplots(figsize=(8, 4))
    for path in wealth[:40]:
        ax.plot(years, path, color=NEUTRAL, linewidth=0.8, zorder=1)
    p = np.percentile(wealth, [10, 25, 50, 75, 90], axis=0)
    ax.fill_between(years, p[0], p[4], color=BLUE_LIGHT, alpha=0.45, label="p10–p90", zorder=2)
    ax.fill_between(years, p[1], p[3], color=CYAN, alpha=0.45, label="p25–p75", zorder=3)
    ax.plot(years, p[2], color=NAVY, linewidth=2.2, label="Mediana", zorder=4)
    ax.axhline(0, color=INK_SOFT, linewidth=1)
    ax.set_xlabel("Año")
    ax.set_ylabel("Patrimonio neto")
    money_axis(ax)
    ax.legend(loc="upper left")
    clean_axes(ax)
    _save(fig, "04_abanico_caminos.png")


def fig_box_reading(result):
    """Cómo se lee una caja del gráfico de distribución."""
    s = result.strategies[0]
    data = s.wealth[:, 19]
    p10, p25, p50, p75, p90 = np.percentile(data, [10, 25, 50, 75, 90])
    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.bxp([{"med": p50, "q1": p25, "q3": p75, "whislo": p10, "whishi": p90, "fliers": []}],
           positions=[0], widths=0.35, showfliers=False, patch_artist=True,
           boxprops=dict(facecolor=NAVY, linewidth=0), medianprops=dict(color="white", linewidth=2),
           whiskerprops=dict(color=NAVY, linewidth=1.4), capprops=dict(color=NAVY, linewidth=1.4))
    for value, text in ((p90, "p90: 9 de cada 10 caminos terminan por debajo"),
                        (p75, "p75: borde superior de la caja"),
                        (p50, "Mediana: la mitad arriba, la mitad abajo"),
                        (p25, "p25: borde inferior de la caja"),
                        (p10, "p10: solo 1 de cada 10 caminos queda por debajo")):
        ax.annotate(f"{text}\n{format_money(value)}", xy=(0.18, value), xytext=(0.32, value),
                    va="center", fontsize=8.5, color=INK,
                    arrowprops=dict(arrowstyle="-", color=LEADER))
    ax.set_xlim(-0.4, 1.6)
    ax.set_xticks([])
    ax.set_ylabel("Patrimonio neto en el año 20")
    money_axis(ax)
    clean_axes(ax)
    _save(fig, "05_leer_box_plot.png")


def fig_amortization():
    fig, ax = plt.subplots(figsize=(8, 3.6))
    for amort, color, label in ((Amortization.BULLET, NAVY, "Bullet"),
                                (Amortization.LINEAR, CYAN, "Lineal"),
                                (Amortization.FRENCH, SERIES_FOURTH, "Cuota fija (francesa)")):
        terms = LoanTerms(principal=10 * MM, term_years=10, rate=0.07, amortization=amort)
        sim = LoanSimulator(terms, 1, 10)
        balance = []
        for year in range(1, 11):
            sim.drawdown(year)
            sim.accrue_and_amortize(year, np.array([0.07]))
            balance.append(sim.balance[0])
        ax.plot(range(0, 11), [10 * MM, *balance], color=color, linewidth=2, marker="o",
                markersize=3.5, label=label)
    ax.set_xlabel("Año")
    ax.set_ylabel("Saldo al cierre")
    money_axis(ax)
    ax.legend()
    clean_axes(ax)
    _save(fig, "06_amortizaciones.png")


def fig_margin_call(cmas, corr):
    """Un camino con llamada a margen: activos, deuda y LTV."""
    loan = LoanTerms(principal=12 * MM, start_year=1, term_years=10, rate=0.06,
                     max_ltv=0.55, target_ltv=0.45)
    sc = Scenario(initial_value=15 * MM, horizon=12, inflation=0.03, strategies=[Strategy(
        Allocation("Apalancada", {"AC World Equity": 0.7, "U.S. Aggregate Bonds": 0.3}),
        cashflows=[CashFlow("Gasto", FlowKind.OUTFLOW, 0.6 * MM, 1, 12)], loan=loan)])
    r = simulate(sc, cmas, corr, SimulationSettings(n_paths=3000)).strategies[0]
    i = int(np.argmax(r.margin_calls))
    years = np.arange(1, sc.horizon + 1)
    assets, debt = r.assets[i], r.debt[i]
    ltv = np.where(assets > 0, debt / np.maximum(assets, 1), np.nan)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 5), sharex=True,
                                 gridspec_kw={"height_ratios": [2, 1]})
    a1.plot(years, assets, color=NAVY, linewidth=2, label="Activos")
    a1.plot(years, debt, color=CYAN, linewidth=2, label="Deuda")
    a1.fill_between(years, debt, assets, color=BLUE_LIGHT, alpha=0.35, label="Patrimonio neto")
    money_axis(a1)
    a1.legend(loc="upper right")
    clean_axes(a1)
    a2.plot(years, ltv * 100, color=NAVY, linewidth=2, marker="o", markersize=3)
    a2.axhline(55, color=INK_SOFT, linestyle="--", linewidth=1)
    a2.text(years[-1], 55.4, "LTV máximo 55%", ha="right", fontsize=8, color=INK_SOFT)
    a2.axhline(45, color=LEADER, linestyle=":", linewidth=1)
    a2.text(years[-1], 45.4, "objetivo tras la llamada 45%", ha="right", fontsize=8,
            color=INK_SOFT)
    a2.set_ylim(30, 62)
    a2.set_ylabel("LTV (%)")
    a2.set_xlabel("Año")
    clean_axes(a2)
    _save(fig, "07_llamada_a_margen.png")
    print(f"    camino {i}: {int(r.margin_calls[i])} llamada(s), "
          f"venta forzada total {format_money(r.forced_sales[i])}")


def fig_fixed_vs_percentage(cmas, corr):
    base = dict(initial_value=20 * MM, horizon=30, inflation=0.025)
    weights = {"AC World Equity": 0.6, "U.S. Aggregate Bonds": 0.4}
    sc = Scenario(**base, strategies=[
        Strategy(Allocation("Monto fijo 1.000.000 indexado", dict(weights)),
                 cashflows=[CashFlow("Gasto", FlowKind.OUTFLOW, 1 * MM, 1, 30)]),
        Strategy(Allocation("5% del patrimonio", dict(weights)),
                 cashflows=[CashFlow("Gasto", FlowKind.OUTFLOW, 0.05, 1, 30,
                                     basis=FlowBasis.PORTFOLIO_PCT)]),
    ])
    r = simulate(sc, cmas, corr, SimulationSettings(n_paths=5000))
    years = np.arange(1, 31)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.8))
    for s, color in zip(r.strategies, (NAVY, CYAN)):
        p = np.percentile(s.wealth, [10, 50], axis=0)
        a1.plot(years, p[1], color=color, linewidth=2, label=f"{s.name} · mediana")
        a1.plot(years, p[0], color=color, linewidth=1.2, linestyle="--",
                label=f"p10 · éxito {s.success_probability:.0%}")
        w = np.broadcast_to(s.withdrawals, s.wealth.shape)
        q = np.percentile(w, [10, 50, 90], axis=0)
        a2.plot(years, q[1], color=color, linewidth=2, label=s.name)
        a2.fill_between(years, q[0], q[2], color=color, alpha=0.18)
    a1.set_title("Patrimonio neto", fontsize=10)
    a2.set_title("Retiro de cada año (mediana y p10–p90)", fontsize=10)
    for a in (a1, a2):
        a.set_xlabel("Año")
        money_axis(a)
        clean_axes(a)
    a1.legend(fontsize=7.5)
    a2.legend(fontsize=7.5)
    _save(fig, "08_fijo_vs_porcentual.png")


def fig_solver(cmas, corr, sample):
    settings = SimulationSettings()
    res = solve(sample, "Portafolio actual", Variable(FLOW, 0), Metric(SUCCESS), 0.85,
                cmas, corr, settings)
    market = draw_market(sample, cmas, corr, settings)
    grid = np.linspace(0.6 * MM, 1.7 * MM, 45)
    probs = []
    for v in grid:
        strat = deepcopy(sample.strategies[0])
        strat.cashflows[0].amount = v
        probs.append(simulate_strategy(strat, sample.horizon, sample.inflation,
                                       sample.initial_value, cmas, market).success_probability)
    fig, ax = plt.subplots(figsize=(8, 3.8))
    ax.plot(grid, np.array(probs) * 100, color=NAVY, linewidth=2, label="Probabilidad de éxito")
    tried = [(v, p) for v, p in res.curve if 0.6 * MM <= v <= 1.7 * MM]
    ax.scatter([v for v, _ in tried], [p * 100 for _, p in tried], color=CYAN, s=22, zorder=5,
               label=f"Valores que probó el solver ({res.evaluations} en total)")
    ax.axhline(85, color=INK_SOFT, linestyle="--", linewidth=1)
    ax.axvline(res.value, color=INK_SOFT, linestyle=":", linewidth=1)
    ax.annotate(f"Retiro máximo con ≥85%:\n{format_money(res.value)}",
                xy=(res.value, 85), xytext=(res.value + 0.12 * MM, 93), fontsize=8.5, color=INK,
                arrowprops=dict(arrowstyle="-", color=LEADER))
    ax.set_xlabel("Retiro anual del primer año")
    ax.set_ylabel("Probabilidad de éxito (%)")
    money_axis(ax, "x")
    ax.legend(loc="lower left")
    clean_axes(ax)
    _save(fig, "09_solver.png")
    print(f"    solver: {format_money(res.value)} → {res.achieved:.2%} "
          f"en {res.evaluations} pruebas; actual {format_money(res.current_value)} → "
          f"{res.current_probability:.2%}")


def worked_example():
    """El camino de tres años de MODELO.md §7, calculado por el motor real."""
    cmas = CMASet([AssetClass("U.S. Cash", 0.03, 0.0), AssetClass("Portafolio", 0.06, 0.0)])
    names = ["Portafolio", "U.S. Cash"]
    gross = np.array([[[1.10, 1.03], [0.70, 1.03], [1.15, 1.03]]])  # 1 camino, 3 años
    market = Market(names=names, gross_returns=gross, cash_growth=gross[:, :, 1],
                    corr=np.eye(2))
    strat = Strategy(
        Allocation("Ejemplo", {"Portafolio": 1.0}),
        cashflows=[
            CashFlow("Aporte", FlowKind.INFLOW, 500_000, 1, 1),
            CashFlow("Gasto", FlowKind.OUTFLOW, 400_000, 1, 3, inflation_indexed=True),
        ],
        loan=LoanTerms(principal=4 * MM, start_year=1, term_years=5, rate=0.06,
                       max_ltv=0.35, target_ltv=0.30),
    )
    r = simulate_strategy(strat, 3, 0.03, 10 * MM, cmas, market)
    print("  ejemplo resuelto (año: activos / deuda / patrimonio / venta forzada acumulada):")
    for y in range(3):
        print(f"    {y + 1}: {format_money(r.assets[0, y])} / {format_money(r.debt[0, y])} / "
              f"{format_money(r.wealth[0, y])}")
    print(f"    llamadas a margen: {int(r.margin_calls[0])}, venta forzada "
          f"{format_money(r.forced_sales[0])}")


def conversion_example(cmas):
    a = cmas.by_name("U.S. Large Cap")
    print(f"  conversión U.S. Large Cap: compuesto {a.compound_return:.4%}, volatilidad "
          f"{a.volatility:.4%} → mu_log {a.mu_log:.6f}, sigma_log {a.sigma_log:.6f}, "
          f"aritmético {a.arithmetic_return:.4%}")


def cvar_example():
    rng = np.random.default_rng(3)
    values = np.round(rng.lognormal(np.log(30), 0.5, 20) - 8, 1)
    ordered = np.sort(values)
    print("  CVaR sobre 20 caminos (millones), ordenados:", ", ".join(f"{v:g}" for v in ordered))
    print(f"    p5 ≈ {np.percentile(values, 5):.2f}; peor 5% = 1 camino → CVaR {ordered[0]:g}; "
          f"peor 10% = 2 caminos → {ordered[:2].mean():.2f}")


def main():
    apply_matplotlib_style()
    cmas, corr = seed_cmas(), CorrelationMatrix.load()
    sample = build_sample_case()
    result = simulate(sample, cmas, corr, SimulationSettings())
    print("Figuras:")
    fig_normal_vs_lognormal()
    fig_volatility_drag()
    fig_correlation()
    fig_fan(result)
    fig_box_reading(result)
    fig_amortization()
    fig_margin_call(cmas, corr)
    fig_fixed_vs_percentage(cmas, corr)
    fig_solver(cmas, corr, sample)
    print("Ejemplos:")
    conversion_example(cmas)
    worked_example()
    cvar_example()


if __name__ == "__main__":
    main()
