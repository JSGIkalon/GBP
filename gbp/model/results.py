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
    # Estadísticas ya calculadas. Un resultado no cambia después de la corrida,
    # así que la caché no puede quedar vieja; y con un millón de caminos cada
    # mediana o percentil sobre la matriz completa es lo caro de redibujar.
    _cache: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def n_paths(self) -> int:
        return self.wealth.shape[0]

    @property
    def horizon(self) -> int:
        return self.wealth.shape[1]

    def _cached(self, key, compute):
        if key not in self._cache:
            self._cache[key] = compute()
        return self._cache[key]

    def values(self, real: bool = False) -> np.ndarray:
        """Patrimonio neto en términos nominales o en poder adquisitivo de hoy."""
        if not real or self.inflation_factors.size == 0:
            return self.wealth
        # Sin caché a propósito: sería una segunda copia de la corrida entera en
        # memoria. Lo que se calcula sobre ella sí se cachea, y los cálculos
        # internos cortan antes de deflactar (`_columns`).
        return self.wealth / self.inflation_factors

    def _columns(self, years: list[int], real: bool) -> np.ndarray:
        """Solo los años pedidos, deflactados después de cortar.

        Dividir la matriz completa para quedarse con cuatro columnas era copiar
        la corrida entera en cada llamada. El resultado es idéntico: cada celda
        se divide por el mismo factor.
        """
        idx = [y - 1 for y in years]
        data = self.wealth[:, idx]
        if real and self.inflation_factors.size:
            data = data / self.inflation_factors[idx]
        return data

    def distribution_stats(self, years: list[int], real: bool = False) -> dict:
        """Percentiles, media y desviación de los años pedidos, calculados una vez.

        Es lo que consumen el box plot, su tabla y el informe: antes cada uno
        recalculaba los mismos cinco percentiles por su lado.
        """
        def compute():
            data = self._columns(years, real)
            p10, p25, p50, p75, p90 = np.percentile(data, [10, 25, 50, 75, 90], axis=0)
            return {
                10: p10, 25: p25, 50: p50, 75: p75, 90: p90,
                "mean": data.mean(axis=0), "std": data.std(axis=0),
            }
        return self._cached(("stats", tuple(years), real), compute)

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
        if years is None:
            years = list(range(1, self.horizon + 1))
        wanted = percentiles if percentiles is not None else PERCENTILES
        data = self._columns(years, real)
        return {p: np.percentile(data, p, axis=0) for p in wanted}

    def mean(self, years: list[int] | None = None, real: bool = False) -> np.ndarray:
        if years is None:
            years = list(range(1, self.horizon + 1))
        return self._columns(years, real).mean(axis=0)

    def std(self, years: list[int] | None = None, real: bool = False) -> np.ndarray:
        """Desviación estándar del patrimonio en cada año indicado."""
        if years is None:
            years = list(range(1, self.horizon + 1))
        return self._columns(years, real).std(axis=0)

    def cvar(self, year: int, level: float = 0.05, real: bool = False) -> float:
        """Valor esperado en el peor `level` de los caminos (CVaR).

        Basta separar la cola con `partition` en vez de ordenar el millón de
        caminos. La cola se ordena después —es chica— para que la suma se haga
        en el mismo orden de siempre y la cifra no cambie ni en el último bit.
        """
        data = self._columns([year], real)[:, 0]
        cut = max(1, int(round(level * len(data))))
        tail = np.sort(np.partition(data, cut - 1)[:cut])
        return float(tail.mean())

    @property
    def success_probability(self) -> float:
        """Fracción de caminos en que el patrimonio neto nunca se agota.

        Un camino "falla" si en algún año el patrimonio neto llega a cero o
        menos, es decir si los retiros y la deuda consumen el portafolio.
        """
        return self._cached(
            "success", lambda: float((self.wealth > 0).all(axis=1).mean())
        )

    @property
    def debt_peak(self) -> float:
        """Máximo saldo de deuda de toda la corrida; cero si no hubo crédito."""
        return self._cached(
            "debt_peak", lambda: float(self.debt.max()) if self.debt.size else 0.0
        )

    @property
    def has_debt(self) -> bool:
        return self.debt_peak > 0

    @property
    def margin_call_probability(self) -> float:
        if self.margin_calls.size == 0:
            return 0.0
        return float((self.margin_calls > 0).mean())

    def terminal_values(self, real: bool = False) -> np.ndarray:
        return self._columns([self.horizon], real)[:, 0]

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
        last = self._columns([self.horizon], real)[:, 0]
        if self.horizon >= 2:
            previous = self._columns([self.horizon - 1], real)[:, 0]
        else:
            # Con un solo año, el punto de partida es el capital del año 0, que
            # ya está en moneda de hoy: no se deflacta.
            previous = np.full(self.n_paths, self.initial_value)
        alive = previous > 0
        if not alive.any():
            return float("nan")
        return float(np.median(last[alive] / previous[alive] - 1.0))

    def flow_history(self, real: bool = False) -> dict[str, np.ndarray]:
        """Aportes y retiros medianos por año, alineados a `1..horizon`.

        La mediana y no el promedio porque un flujo porcentual tiene cola: el
        promedio lo sube un puñado de caminos muy ricos y dejaría de parecerse
        al retiro que se ve en un año corriente.
        """
        def compute():
            horizon = self.horizon
            if self.contributions.size == 0:
                aportes = np.zeros(horizon)
                retiros = np.zeros(horizon)
            else:
                # Sin flujos porcentuales se guardan como una sola fila —son
                # iguales en todos los caminos— y su mediana es esa fila.
                aportes = np.median(self.contributions, axis=0)
                retiros = np.median(self.withdrawals, axis=0)
            if real and self.inflation_factors.size:
                aportes = aportes / self.inflation_factors
                retiros = retiros / self.inflation_factors
            return {"aportes": aportes, "retiros": retiros, "neto": aportes - retiros}
        return self._cached(("flows", real), compute)

    def flow_value_series(self) -> dict[str, np.ndarray]:
        """Flujos netos y valor de portafolio mediano, año por año.

        Junta lo que hace falta para la tabla de "flujos y valor de portafolio"
        que se muestra tanto en la app como en el informe: el flujo neto
        nominal, su acumulado, y el patrimonio neto mediano en las dos
        unidades. Vive aquí y no en la UI ni en el informe porque los dos la
        necesitan igual.
        """
        def compute():
            neto = self.flow_history()["neto"]
            all_years = list(range(1, self.horizon + 1))
            return {
                "neto": neto,
                "acumulado": np.cumsum(neto),
                "valor_nominal": np.median(self.wealth, axis=0),
                "valor_real": np.median(self._columns(all_years, True), axis=0),
            }
        return self._cached("flow_values", compute)


@dataclass
class SimulationResult:
    """Resultado completo de una corrida: una entrada por estrategia."""

    strategies: list[StrategyResult]
    horizon: int
    n_paths: int
    seed: int | None = None
    scenario_name: str = ""
    # Vacío en la corrida original, que está en la moneda de los supuestos
    # (USD). `in_currency` lo marca, y así cada gráfico y tabla puede decir en
    # qué moneda está sin que nadie se lo pase aparte.
    currency: str = ""
    fx_rate: float = 1.0

    def in_currency(self, rate: float, currency: str = "COP") -> "SimulationResult":
        """La misma corrida con todos los montos multiplicados por una tasa fija.

        Es una **vista**: no se vuelve a simular nada. Con una tasa fija, toda
        cifra en dinero se multiplica por el mismo número, así que
        probabilidades, porcentajes y Sharpe no cambian —no dependen de la
        escala— y los percentiles convertidos son los percentiles de lo
        convertido. Se devuelven copias nuevas, con cachés vacías, para que
        nada de la vista en USD se cuele en la de COP ni al revés.
        """
        def convert(s: StrategyResult) -> StrategyResult:
            wealth = s.wealth * rate
            # Sin crédito el motor comparte un solo arreglo para activos y
            # patrimonio; la vista lo sigue compartiendo en vez de duplicarlo.
            assets = wealth if np.shares_memory(s.wealth, s.assets) else s.assets * rate
            return StrategyResult(
                name=s.name,
                wealth=wealth,
                assets=assets,
                debt=s.debt * rate,
                summary=s.summary,
                margin_calls=s.margin_calls,
                forced_sales=s.forced_sales * rate,
                inflation_factors=s.inflation_factors,
                contributions=s.contributions * rate,
                withdrawals=s.withdrawals * rate,
                initial_value=s.initial_value * rate,
            )

        return SimulationResult(
            strategies=[convert(s) for s in self.strategies],
            horizon=self.horizon,
            n_paths=self.n_paths,
            seed=self.seed,
            scenario_name=self.scenario_name,
            currency=currency,
            fx_rate=rate,
        )

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
