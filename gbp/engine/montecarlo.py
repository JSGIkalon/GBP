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
5. Retiros: primero los porcentuales, luego los de monto fijo indexados a la
   inflación.
6. Control de LTV y liquidación forzada si aplica.

Si los retiros agotan el portafolio, el saldo queda negativo y a partir de ahí
devenga a la tasa de caja en vez de al retorno del portafolio: un patrimonio
agotado es un descubierto, no una posición invertida que siga capitalizando.

Flujos porcentuales
-------------------
Un flujo expresado como porcentaje se calcula sobre el **patrimonio neto** del
año —activos menos deuda— ya crecido y ya servido el crédito. Neto y no bruto
porque con apalancamiento el activo bruto no es del inversionista: retirar 4%
de 10MM de activos contra 5MM de deuda sería retirar el 8% de lo que realmente
tiene. Sin crédito los dos coinciden, que es el caso normal.

La base se fija **antes** de aplicar cualquier retiro del año, así que varios
flujos porcentuales del mismo año no dependen del orden en que se listen. Un
patrimonio ya negativo no genera retiro: no se puede sacar un porcentaje de una
deuda.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from ..model.assets import CMASet
from ..model.cashflows import CashFlow, FlowKind, combined_rate_schedule
from ..model.correlation import CorrelationMatrix, cholesky_factor, covariance
from ..model.leverage import LoanSimulator, RateMode
from ..model.results import SimulationResult, StrategyResult
from ..model.scenario import Scenario, SimulationSettings
from ..model.strategy import Strategy
from .summary import CASH_ASSET, risk_free_rate, summarize

ProgressCallback = Callable[[int, int, str], None]


def _split_by_kind(
    flows: list[CashFlow], schedule_of: Callable[[CashFlow], np.ndarray], horizon: int
) -> tuple[np.ndarray, np.ndarray]:
    """Entradas y salidas por año, ambas como magnitudes positivas.

    Sirve para los dos calendarios —montos fijos y fracciones del patrimonio—,
    que se separan igual y solo difieren en cómo se calcula cada flujo. Las dos
    mitades hacen falta por separado aunque el patrimonio solo vea el neto: un
    año con un aporte del 3% y un retiro del 4% no es lo mismo, en el anexo,
    que un año con un retiro del 1%.
    """
    inflows = np.zeros(horizon)
    outflows = np.zeros(horizon)
    for flow in flows:
        schedule = schedule_of(flow)
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
    """Retornos brutos (1 + r) por camino, año y clase de activo.

    Se calcula sobre un solo arreglo: el producto por el factor de Cholesky ya
    crea uno nuevo, y a ese mismo se le suma la media y se le aplica la
    exponencial. Con 1.000.000 de caminos cada copia intermedia son gigas, y la
    versión anterior tenía cuatro vivas a la vez. El resultado es idéntico bit
    a bit: son las mismas operaciones, sin copias entre ellas.
    """
    assets = [cmas.by_name(n) for n in names]
    mu_log = np.array([a.mu_log for a in assets])
    sigma_log = np.array([a.sigma_log for a in assets])

    cov_log = covariance(sigma_log, corr)
    factor = cholesky_factor(cov_log)

    shocks = rng.standard_normal((n_paths, horizon, len(names)))
    returns = shocks @ factor.T
    del shocks
    returns += mu_log
    np.exp(returns, out=returns)
    return returns


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


@dataclass
class Market:
    """Los caminos de mercado de una corrida, sorteados una sola vez.

    Es lo que comparten todas las estrategias —y todas las pruebas del solver—:
    que el mercado sea el mismo es lo que hace que las diferencias vengan de la
    estrategia y no del azar.
    """

    names: list[str]
    gross_returns: np.ndarray  # (n_paths, horizon, n_assets)
    cash_growth: np.ndarray | float
    corr: np.ndarray
    cash_asset: str = CASH_ASSET


def _market_names(scenario: Scenario, cmas: CMASet, correlations: CorrelationMatrix,
                  cash_asset: str) -> list[str]:
    names = scenario.asset_names
    # La caja entra al sorteo aunque ninguna estrategia la use, porque de ella
    # dependen la tasa del crédito y el devengo de un patrimonio agotado.
    if cash_asset not in names and cash_asset in cmas.names and cash_asset in correlations.names:
        names = names + [cash_asset]

    # `subset` levantaría un KeyError, que es correcto como red de programador
    # pero ilegible para quien abrió un caso de otra máquina. Aquí se convierte
    # en un error de dominio que dice qué hacer.
    missing = [n for n in names if n not in correlations.names]
    if missing:
        raise ValueError(
            "La matriz de correlación no cubre estas clases de activo: "
            + ", ".join(missing)
            + ". Si el caso viene de otro computador, vuelve a abrirlo y acepta "
            "añadir sus activos propios a tu librería."
        )
    return names


def draw_market(
    scenario: Scenario,
    cmas: CMASet,
    correlations: CorrelationMatrix,
    settings: SimulationSettings,
    cash_asset: str = CASH_ASSET,
) -> Market:
    """Sortea los caminos de mercado del escenario, validado de antemano."""
    names = _market_names(scenario, cmas, correlations, cash_asset)
    corr_full = correlations.subset(names)
    rng = np.random.default_rng(settings.seed)
    gross_returns = _simulate_asset_returns(
        names, cmas, corr_full, settings.n_paths, scenario.horizon, rng
    )
    return Market(
        names=names,
        gross_returns=gross_returns,
        cash_growth=_cash_growth(names, gross_returns, cmas, cash_asset),
        corr=corr_full,
        cash_asset=cash_asset,
    )


def simulate_strategy(
    strategy: Strategy,
    horizon: int,
    inflation: float,
    scenario_initial: float,
    cmas: CMASet,
    market: Market,
    on_year: Callable[[], None] | None = None,
) -> StrategyResult:
    """Proyecta una estrategia sobre caminos de mercado ya sorteados.

    Pública porque el solver la llama muchas veces sobre el mismo `market`,
    cambiando solo una cifra de la estrategia.

    Disposición de memoria
    ----------------------
    Dentro del bucle todo va **año por fila** —`(horizon, n_paths)`—, porque el
    bucle recorre años y cada año toca todos los caminos: así cada lectura y
    cada escritura es un bloque contiguo en memoria y no un salto de un camino
    al siguiente. Medido: unas 3,6 veces más rápido que por columnas, con las
    mismas cifras bit a bit. Al final se entrega la vista traspuesta, que es la
    forma `(n_paths, horizon)` que espera el resto de la app.
    """
    allocation = strategy.allocation
    names = market.names
    n_paths = market.gross_returns.shape[0]
    weights = allocation.weight_vector(names)
    weights = weights / weights.sum()

    portfolio_growth = np.ascontiguousarray((market.gross_returns @ weights).T)
    cash_rate = np.asarray(market.cash_growth) - 1.0
    if cash_rate.ndim == 2:
        cash_rate = np.ascontiguousarray(cash_rate.T)

    inflows, outflows = _split_by_kind(
        strategy.cashflows, lambda f: f.schedule(horizon, inflation), horizon
    )
    flow_rates = combined_rate_schedule(strategy.cashflows, horizon)
    # Las dos mitades del flujo porcentual por separado, solo para el registro:
    # sobre una base que se fija antes de aplicar nada, aplicarlas juntas o por
    # separado da el mismo patrimonio, pero el anexo necesita saber cuánto
    # entró y cuánto salió, no solo el neto.
    rate_in, rate_out = _split_by_kind(
        strategy.cashflows, lambda f: f.rate_schedule(horizon), horizon
    )
    # Sin flujos porcentuales los aportes y retiros son los mismos en todos los
    # caminos: basta una fila, y no una matriz de caminos repetidos.
    per_path_flows = bool(rate_in.any() or rate_out.any())
    flow_rows = n_paths if per_path_flows else 1

    loan = strategy.loan
    ledger = (
        LoanSimulator(loan, n_paths, horizon, risk_free_rate(cmas, market.cash_asset))
        if loan is not None and loan.active
        else None
    )

    initial_value = float(strategy.resolved_initial(scenario_initial))
    assets = np.full(n_paths, initial_value)
    assets_history = np.zeros((horizon, n_paths))
    debt_history = np.zeros((horizon, n_paths)) if ledger is not None else None
    contributions = np.zeros((horizon, flow_rows))
    withdrawals = np.zeros((horizon, flow_rows))

    for year in range(1, horizon + 1):
        y = year - 1

        if ledger is not None:
            assets += ledger.drawdown(year)

        assets += inflows[y]
        contributions[y] = inflows[y]

        growth = np.where(assets > 0, portfolio_growth[y], _year_cash(cash_rate, y) + 1.0)
        assets = assets * growth

        if ledger is not None:
            rates = _loan_rates(loan, cash_rate, y, n_paths)
            assets -= ledger.accrue_and_amortize(year, rates)

        if flow_rates[y] or rate_in[y] or rate_out[y]:
            net_wealth = assets - ledger.balance if ledger is not None else assets
            base = np.maximum(net_wealth, 0.0)
            assets += base * flow_rates[y]
            contributions[y] += base * rate_in[y]
            withdrawals[y] += base * rate_out[y]

        assets -= outflows[y]
        withdrawals[y] += outflows[y]

        if ledger is not None:
            # La liquidación forzada **sale del portafolio**: se venden activos y
            # con lo obtenido se paga deuda, así que bajan los dos lados por
            # igual y el patrimonio neto no cambia en ese instante. Descartar lo
            # que devuelve `margin_call` dejaba la deuda pagada pero los activos
            # intactos: el patrimonio neto subía al recibir una llamada a margen
            # —imposible— y los años siguientes capitalizaban sobre un
            # portafolio que ya se había vendido.
            assets -= ledger.margin_call(np.maximum(assets, 0.0))
            debt_history[y] = ledger.balance

        assets_history[y] = assets

        if on_year is not None:
            on_year()

    idx = [names.index(n) for n in allocation.asset_names]
    summary = summarize(allocation, cmas, market.corr[np.ix_(idx, idx)], market.cash_asset)

    inflation_factors = (1.0 + inflation) ** np.arange(1, horizon + 1)

    # Sin crédito la deuda es cero en todas partes y el patrimonio neto es el
    # activo tal cual: se comparte el arreglo en vez de guardar una resta por
    # cero y una matriz de ceros del tamaño de la corrida.
    if debt_history is None:
        debt = np.zeros((1, horizon))
        wealth = assets_history.T
    else:
        debt = debt_history.T
        wealth = (assets_history - debt_history).T

    return StrategyResult(
        name=allocation.name,
        wealth=wealth,
        assets=assets_history.T,
        debt=debt,
        summary=summary,
        margin_calls=ledger.margin_calls if ledger else np.zeros(n_paths, dtype=int),
        forced_sales=ledger.forced_sales if ledger else np.zeros(n_paths),
        inflation_factors=inflation_factors,
        contributions=contributions.T,
        withdrawals=withdrawals.T,
        initial_value=initial_value,
    )


def _year_cash(cash_rate: np.ndarray | float, year_index: int) -> np.ndarray | float:
    """Tasa de caja del año, sea una constante o una matriz año por camino."""
    if np.ndim(cash_rate) == 2:
        return cash_rate[year_index]
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
    _market_names(scenario, cmas, correlations, cash_asset)  # falla antes de sortear

    # El progreso se cuenta en pasos de **año simulado**, no de estrategia: con
    # una sola estrategia la barra saltaba de 0 a 100 sin pasar por el medio.
    # El sorteo de retornos es un paso aparte porque es la parte cara cuando el
    # número de caminos es grande.
    steps_per_strategy = scenario.horizon
    total = 1 + len(scenario.strategies) * steps_per_strategy
    done = 0

    if progress:
        caminos = f"{settings.n_paths:,}".replace(",", ".")
        progress(done, total, f"Sorteando {caminos} caminos de mercado…")

    market = draw_market(scenario, cmas, correlations, settings, cash_asset)
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
            simulate_strategy(
                strategy,
                scenario.horizon,
                scenario.inflation,
                scenario.initial_value,
                cmas,
                market,
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
