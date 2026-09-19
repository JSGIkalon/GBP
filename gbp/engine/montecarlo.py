"""Simulación Monte Carlo del patrimonio.

Modelo
------
Los retornos de cada clase de activo se modelan como **lognormales
correlacionadas**, con paso anual. Trabajar en espacio logarítmico garantiza que
ningún activo pierda más del 100% en un año y reproduce el arrastre de la
volatilidad sobre el retorno compuesto.

Todas las estrategias comparadas se simulan con **los mismos números aleatorios**
(se sortean una sola vez sobre la unión de clases de activo del escenario), de
modo que las diferencias entre estrategias reflejen la estrategia y no el ruido
del muestreo.

Cada estrategia lleva sus propios flujos, su propio crédito y, si se le fijó, su
propio capital inicial: se pueden comparar planes completos, no solo mezclas de
activos. El horizonte y la inflación sí son comunes a toda la corrida.

Orden de operaciones dentro de cada año
---------------------------------------
1. Desembolso del crédito, si corresponde a ese año.
2. Aportes.
3. Retorno de mercado, con rebalanceo anual a los pesos objetivo.
4. Intereses y amortización del crédito.
5. Retiros, indexados a la inflación.
6. Control de LTV y liquidación forzada si aplica.

Si los retiros agotan el portafolio, el saldo queda negativo y a partir de ahí
devenga a la tasa de caja en vez de al retorno del portafolio: un patrimonio
agotado es un descubierto, no una posición invertida que siga capitalizando.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from ..model.assets import CMASet
from ..model.cashflows import CashFlow, FlowKind
from ..model.correlation import CorrelationMatrix, cholesky_factor, covariance
from ..model.leverage import LoanSimulator, RateMode
from ..model.results import SimulationResult, StrategyResult
from ..model.scenario import Scenario, SimulationSettings
from ..model.strategy import Strategy
from .summary import CASH_ASSET, summarize

ProgressCallback = Callable[[int, int, str], None]


def _flow_schedules(
    flows: list[CashFlow], horizon: int, inflation: float
) -> tuple[np.ndarray, np.ndarray]:
    """Aportes y retiros por año, ambos como magnitudes positivas."""
    inflows = np.zeros(horizon)
    outflows = np.zeros(horizon)
    for flow in flows:
        schedule = flow.schedule(horizon, inflation)
        if flow.kind is FlowKind.INFLOW:
            inflows += schedule
        else:
            outflows += -schedule
    return inflows, outflows


def _simulate_asset_returns(
    names: list[str],
    cmas: CMASet,
    corr: np.ndarray,
    n_paths: int,
    horizon: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Retornos brutos (1 + r) por camino, año y clase de activo."""
    assets = [cmas.by_name(n) for n in names]
    mu_log = np.array([a.mu_log for a in assets])
    sigma_log = np.array([a.sigma_log for a in assets])

    cov_log = covariance(sigma_log, corr)
    factor = cholesky_factor(cov_log)

    shocks = rng.standard_normal((n_paths, horizon, len(names)))
    log_returns = mu_log + shocks @ factor.T
    return np.exp(log_returns)


def _cash_growth(
    names: list[str], gross_returns: np.ndarray, cmas: CMASet, cash_asset: str
) -> np.ndarray | float:
    """Factor de crecimiento de la caja, simulado si la clase está en el escenario."""
    if cash_asset in names:
        return gross_returns[:, :, names.index(cash_asset)]
    try:
        return 1.0 + cmas.by_name(cash_asset).compound_return
    except KeyError:
        return 1.0


def _simulate_strategy(
    strategy: Strategy,
    horizon: int,
    inflation: float,
    scenario_initial: float,
    cmas: CMASet,
    names: list[str],
    gross_returns: np.ndarray,
    cash_growth: np.ndarray | float,
    corr_full: np.ndarray,
    cash_asset: str,
    on_year: Callable[[], None] | None = None,
) -> StrategyResult:
    allocation = strategy.allocation
    n_paths = gross_returns.shape[0]
    weights = allocation.weight_vector(names)
    weights = weights / weights.sum()

    portfolio_growth = gross_returns @ weights  # (n_paths, horizon)
    cash_rate = np.asarray(cash_growth) - 1.0

    inflows, outflows = _flow_schedules(strategy.cashflows, horizon, inflation)

    loan = strategy.loan
    reference_cash = 0.0
    try:
        reference_cash = cmas.by_name(cash_asset).compound_return
    except KeyError:
        pass
    ledger = (
        LoanSimulator(loan, n_paths, horizon, reference_cash)
        if loan is not None and loan.active
        else None
    )

    assets = np.full(n_paths, float(strategy.resolved_initial(scenario_initial)))
    assets_history = np.zeros((n_paths, horizon))
    debt_history = np.zeros((n_paths, horizon))

    for year in range(1, horizon + 1):
        y = year - 1

        if ledger is not None:
            assets += ledger.drawdown(year)

        assets += inflows[y]

        growth = np.where(assets > 0, portfolio_growth[:, y], _year_cash(cash_rate, y) + 1.0)
        assets = assets * growth

        if ledger is not None:
            rates = _loan_rates(loan, cash_rate, y, n_paths)
            assets -= ledger.accrue_and_amortize(year, rates)

        assets -= outflows[y]

        if ledger is not None:
            # La liquidación forzada **sale del portafolio**: se venden activos y
            # con lo obtenido se paga deuda, así que bajan los dos lados por
            # igual y el patrimonio neto no cambia en ese instante. Descartar lo
            # que devuelve `margin_call` dejaba la deuda pagada pero los activos
            # intactos: el patrimonio neto subía al recibir una llamada a margen
            # —imposible— y los años siguientes capitalizaban sobre un
            # portafolio que ya se había vendido.
            assets -= ledger.margin_call(np.maximum(assets, 0.0))
            ledger.record(year)
            debt_history[:, y] = ledger.balance

        assets_history[:, y] = assets

        if on_year is not None:
            on_year()

    corr_subset = corr_full[np.ix_(
        [names.index(n) for n in allocation.asset_names],
        [names.index(n) for n in allocation.asset_names],
    )]
    summary = summarize(allocation, cmas, corr_subset, cash_asset)

    inflation_factors = (1.0 + inflation) ** np.arange(1, horizon + 1)

    return StrategyResult(
        name=allocation.name,
        wealth=assets_history - debt_history,
        assets=assets_history,
        debt=debt_history,
        summary=summary,
        margin_calls=ledger.margin_calls if ledger else np.zeros(n_paths, dtype=int),
        forced_sales=ledger.forced_sales if ledger else np.zeros(n_paths),
        inflation_factors=inflation_factors,
    )


def _year_cash(cash_rate: np.ndarray | float, year_index: int) -> np.ndarray | float:
    """Tasa de caja del año, sea una constante o una matriz por camino."""
    if np.ndim(cash_rate) == 2:
        return cash_rate[:, year_index]
    return cash_rate


def _loan_rates(loan, cash_rate: np.ndarray | float, year_index: int, n_paths: int) -> np.ndarray:
    """Tasa del crédito para el año, por camino."""
    if loan.rate_mode is RateMode.FIXED:
        return np.full(n_paths, loan.rate)
    return np.broadcast_to(
        np.asarray(_year_cash(cash_rate, year_index)) + loan.spread, (n_paths,)
    ).copy()


def simulate(
    scenario: Scenario,
    cmas: CMASet,
    correlations: CorrelationMatrix,
    settings: SimulationSettings | None = None,
    cash_asset: str = CASH_ASSET,
    progress: ProgressCallback | None = None,
) -> SimulationResult:
    """Corre la simulación para todas las estrategias del escenario."""
    settings = settings or SimulationSettings()
    scenario.validate(cmas)

    names = scenario.asset_names
    # La caja entra al sorteo aunque ninguna estrategia la use, porque de ella
    # dependen la tasa del crédito y el devengo de un patrimonio agotado.
    if cash_asset not in names and cash_asset in cmas.names and cash_asset in correlations.names:
        names = names + [cash_asset]

    corr_full = correlations.subset(names)
    rng = np.random.default_rng(settings.seed)

    # El progreso se cuenta en pasos de **año simulado**, no de estrategia: con
    # una sola estrategia la barra saltaba de 0 a 100 sin pasar por el medio.
    # El sorteo de retornos es un paso aparte porque es la parte cara cuando el
    # número de caminos es grande.
    steps_per_strategy = scenario.horizon
    total = 1 + len(scenario.strategies) * steps_per_strategy
    done = 0

    if progress:
        progress(done, total, f"Sorteando {settings.n_paths:,} caminos de mercado…")

    gross_returns = _simulate_asset_returns(
        names, cmas, corr_full, settings.n_paths, scenario.horizon, rng
    )
    cash_growth = _cash_growth(names, gross_returns, cmas, cash_asset)
    done = 1

    results = []
    for i, strategy in enumerate(scenario.strategies, start=1):
        label = f"Simulando '{strategy.name}' ({i} de {len(scenario.strategies)})"
        if progress:
            progress(done, total, label)

        def tick(_label=label):
            nonlocal done
            done += 1
            if progress:
                progress(done, total, _label)

        results.append(
            _simulate_strategy(
                strategy,
                scenario.horizon,
                scenario.inflation,
                scenario.initial_value,
                cmas,
                names,
                gross_returns,
                cash_growth,
                corr_full,
                cash_asset,
                on_year=tick if progress else None,
            )
        )

    if progress:
        progress(total, total, "Listo")

    return SimulationResult(
        strategies=results,
        horizon=scenario.horizon,
        n_paths=settings.n_paths,
        seed=settings.seed,
        scenario_name=scenario.name,
    )
