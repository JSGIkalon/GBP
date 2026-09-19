"""Resultados de la simulación: percentiles, probabilidad de éxito, CVaR."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Percentiles que muestra la app. El script de control contra el PDF de J.P.
# Morgan pide 5 y 95 explícitamente, para no perder esa comparación.
PERCENTILES = (10, 25, 50, 75, 90)


@dataclass
class SummaryAssumptions:
    """Estadísticas resumen de una estrategia (tabla de supuestos de JPM)."""

    arithmetic_return: float
    volatility: float
    compound_return: float
    yield_: float
    sharpe_ratio: float


@dataclass
class StrategyResult:
    """Resultado de una estrategia sobre todos los caminos simulados.

    `wealth` tiene forma `(n_paths, horizon)` y guarda el **patrimonio neto**
    (activos menos deuda) al cierre de cada año.
    """

    name: str
    wealth: np.ndarray
    assets: np.ndarray
    debt: np.ndarray
    summary: SummaryAssumptions
    margin_calls: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=int))
    forced_sales: np.ndarray = field(default_factory=lambda: np.zeros(0))
    inflation_factors: np.ndarray = field(default_factory=lambda: np.zeros(0))

    @property
    def n_paths(self) -> int:
        return self.wealth.shape[0]

    @property
    def horizon(self) -> int:
        return self.wealth.shape[1]

    def values(self, real: bool = False) -> np.ndarray:
        """Patrimonio neto en términos nominales o en poder adquisitivo de hoy."""
        if not real or self.inflation_factors.size == 0:
            return self.wealth
        return self.wealth / self.inflation_factors

    def percentiles(
        self,
        years: list[int] | None = None,
        real: bool = False,
        percentiles: tuple[float, ...] | list[float] | None = None,
    ) -> dict:
        """Percentiles del patrimonio neto para los años indicados.

        Devuelve `{percentil: array alineado a years}`. Por defecto calcula los
        de `PERCENTILES`; `percentiles` permite pedir otros, que es lo que usa el
        script de control para comparar contra los p5 y p95 publicados por
        J.P. Morgan.
        """
        years = years or list(range(1, self.horizon + 1))
        idx = [y - 1 for y in years]
        data = self.values(real)[:, idx]
        wanted = percentiles if percentiles is not None else PERCENTILES
        return {p: np.percentile(data, p, axis=0) for p in wanted}

    def mean(self, years: list[int] | None = None, real: bool = False) -> np.ndarray:
        years = years or list(range(1, self.horizon + 1))
        return self.values(real)[:, [y - 1 for y in years]].mean(axis=0)

    def std(self, years: list[int] | None = None, real: bool = False) -> np.ndarray:
        """Desviación estándar del patrimonio en cada año indicado."""
        years = years or list(range(1, self.horizon + 1))
        return self.values(real)[:, [y - 1 for y in years]].std(axis=0)

    def cvar(self, year: int, level: float = 0.05, real: bool = False) -> float:
        """Valor esperado en el peor `level` de los caminos (CVaR)."""
        data = np.sort(self.values(real)[:, year - 1])
        cut = max(1, int(round(level * len(data))))
        return float(data[:cut].mean())

    @property
    def success_probability(self) -> float:
        """Fracción de caminos en que el patrimonio neto nunca se agota.

        Un camino "falla" si en algún año el patrimonio neto llega a cero o
        menos, es decir si los retiros y la deuda consumen el portafolio.
        """
        return float((self.wealth > 0).all(axis=1).mean())

    @property
    def margin_call_probability(self) -> float:
        if self.margin_calls.size == 0:
            return 0.0
        return float((self.margin_calls > 0).mean())

    def terminal_values(self, real: bool = False) -> np.ndarray:
        return self.values(real)[:, -1]


@dataclass
class SimulationResult:
    """Resultado completo de una corrida: una entrada por estrategia."""

    strategies: list[StrategyResult]
    horizon: int
    n_paths: int
    seed: int | None = None
    scenario_name: str = ""

    def __iter__(self):
        return iter(self.strategies)

    def __len__(self) -> int:
        return len(self.strategies)

    def by_name(self, name: str) -> StrategyResult:
        for strategy in self.strategies:
            if strategy.name == name:
                return strategy
        raise KeyError(f"No hay resultados para la estrategia '{name}'.")

    @property
    def names(self) -> list[str]:
        return [s.name for s in self.strategies]
