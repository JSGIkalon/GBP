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
    # Flujos **realizados** año por año, en magnitudes positivas y forma
    # `(n_paths, horizon)`. Los de monto fijo son iguales en todos los caminos;
    # los porcentuales no, porque dependen del patrimonio de cada camino, y por
    # eso se guardan por camino y no como un vector.
    contributions: np.ndarray = field(default_factory=lambda: np.zeros(0))
    withdrawals: np.ndarray = field(default_factory=lambda: np.zeros(0))
    initial_value: float = 0.0

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

    def last_year_change(self, real: bool = False) -> float:
        """Variación mediana del patrimonio neto en el **último año proyectado**.

        No es la rentabilidad del portafolio: es el cambio del patrimonio, que
        incluye aportes, retiros y servicio de la deuda. Un portafolio que rinde
        5% mientras se le retira el 6% cae, y esa es justamente la cifra que hace
        falta para saber si el plan todavía se sostiene al final del horizonte.

        Se mide sobre los caminos en que el patrimonio del año anterior era
        positivo: de un patrimonio agotado no hay variación porcentual que
        signifique nada.
        """
        values = self.values(real)
        if self.horizon >= 2:
            previous = values[:, -2]
        else:
            factor = self.inflation_factors[0] if (real and self.inflation_factors.size) else 1.0
            previous = np.full(self.n_paths, self.initial_value / factor)
        alive = previous > 0
        if not alive.any():
            return float("nan")
        return float(np.median(values[alive, -1] / previous[alive] - 1.0))

    def flow_history(self, real: bool = False) -> dict[str, np.ndarray]:
        """Aportes y retiros medianos por año, alineados a `1..horizon`.

        La mediana y no el promedio porque un flujo porcentual tiene cola: el
        promedio lo sube un puñado de caminos muy ricos y dejaría de parecerse
        al retiro que se ve en un año corriente.
        """
        horizon = self.horizon
        if self.contributions.size == 0:
            aportes = np.zeros(horizon)
            retiros = np.zeros(horizon)
        else:
            aportes = np.median(self.contributions, axis=0)
            retiros = np.median(self.withdrawals, axis=0)
        if real and self.inflation_factors.size:
            aportes = aportes / self.inflation_factors
            retiros = retiros / self.inflation_factors
        return {"aportes": aportes, "retiros": retiros, "neto": aportes - retiros}

    def flow_value_series(self) -> dict[str, np.ndarray]:
        """Flujos netos y valor de portafolio mediano, año por año.

        Junta lo que hace falta para la tabla de "flujos y valor de portafolio"
        que se muestra tanto en la app como en el informe: el flujo neto
        nominal, su acumulado, y el patrimonio neto mediano en las dos
        unidades. Vive aquí y no en la UI ni en el informe porque los dos la
        necesitan igual.
        """
        neto = self.flow_history()["neto"]
        return {
            "neto": neto,
            "acumulado": np.cumsum(neto),
            "valor_nominal": np.median(self.values(False), axis=0),
            "valor_real": np.median(self.values(True), axis=0),
        }


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
