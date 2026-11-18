"""Optimización del portafolio sobre los activos que elige el analista.

Tres alternativas, todas con los **mismos supuestos** que usa la proyección
(LTCMA y activos propios, con la matriz de correlación de la app) y en la misma
unidad: retornos y volatilidades **anuales**, en decimales, en la moneda base
(USD). Los activos en COP se llevan antes a USD con la devaluación del caso
(`CMASet.in_usd`), exactamente como hace el motor Monte Carlo.

* **Maximizar retorno**: el mayor retorno esperado del portafolio.
* **Minimizar volatilidad**: la menor volatilidad del portafolio.
* **Maximizar eficiencia**: el mayor cociente retorno esperado / volatilidad.
  Es el cociente simple que pidió el negocio, **no** un Sharpe: no resta tasa
  libre de riesgo. (La app sí muestra un Sharpe en Supuestos, con la caja como
  tasa libre; aquí no se usa a propósito.)

«Retorno esperado» es el **aritmético** del portafolio, `Σ wᵢ·mᵢ`, el mismo con
el que `engine.summary` calcula los supuestos resumen: es lineal en los pesos,
que es lo que hace bien planteado el problema. El compuesto se informa al lado,
derivado con la misma relación lognormal que usa Supuestos.

Restricciones (siempre)
-----------------------
* Los pesos suman exactamente 100% y no hay pesos negativos: sin apalancamiento
  ni cortos.
* Solo entran los activos seleccionados; el resto queda en cero.
* Límites mínimo y máximo por activo, opcionales (por defecto 0% y 100%).

Métodos
-------
* Retorno: es un problema lineal; la solución exacta se arma llenando cada
  activo hasta su máximo en orden de retorno, después de asignar los mínimos.
* Volatilidad: la varianza es convexa; se minimiza exactamente con un método
  de conjunto activo para programación cuadrática con límites por activo y
  suma 1 (`solve_box_qp`).
* Eficiencia: el portafolio de mayor retorno/volatilidad está en la frontera
  eficiente (min varianza − λ·retorno, el mismo QP); se recorre λ por sección
  áurea, porque a lo largo de la frontera el cociente es unimodal.

No hace falta scipy, que no está entre las dependencias del instalador.

Casos sin solución útil
-----------------------
Se informan con un mensaje y **sin pesos**, nunca con pesos engañosos: menos de
un activo seleccionado, límites que no pueden sumar 100%, supuestos faltantes,
una volatilidad mínima de cero (el cociente no está definido) o ningún
portafolio con retorno positivo (el cociente no ordena nada útil).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..model.allocation import Allocation
from ..model.assets import CMASet
from ..model.correlation import CorrelationMatrix, covariance
from ..model.currency import BASE_CURRENCY, describe_rate
from ..model.scenario import Scenario
from .summary import summarize

MAX_RETURN = "max_return"
MIN_VOLATILITY = "min_volatility"
MAX_EFFICIENCY = "max_efficiency"
OBJECTIVES = {
    MAX_RETURN: "Maximizar retorno",
    MIN_VOLATILITY: "Minimizar volatilidad",
    MAX_EFFICIENCY: "Maximizar eficiencia",
}

# Por debajo de esto una volatilidad se trata como cero (0,0001% anual).
ZERO_VOL = 1e-6
WEIGHT_TOL = 1e-9


class OptimizationError(ValueError):
    """Faltan datos o el problema no tiene solución válida."""


@dataclass
class PortfolioStats:
    """Retorno, volatilidad y cociente de un juego de pesos, en la moneda base."""

    weights: dict[str, float]
    expected_return: float        # aritmético anual
    compound_return: float        # compuesto anual (informativo)
    volatility: float             # anual
    ratio: float                  # retorno esperado / volatilidad; nan si vol = 0

    @property
    def ratio_defined(self) -> bool:
        return bool(np.isfinite(self.ratio))


@dataclass
class OptimizationOutcome:
    """Resultado de una alternativa: pesos y cifras, o el motivo de no tenerlos."""

    objective: str
    stats: PortfolioStats | None = None
    message: str = ""
    iterations: int = 0

    @property
    def label(self) -> str:
        return OBJECTIVES[self.objective]

    @property
    def ok(self) -> bool:
        return self.stats is not None


@dataclass
class OptimizationReport:
    """Las tres alternativas, el portafolio actual y el contexto con que se hicieron."""

    strategy_name: str
    assets: list[str]
    bounds: dict[str, tuple[float, float]]
    outcomes: dict[str, OptimizationOutcome]
    current: PortfolioStats | None
    base_currency: str = BASE_CURRENCY
    fx_description: str = ""
    cop_assets: list[str] = field(default_factory=list)

    @property
    def assumptions(self) -> list[str]:
        notas = [
            "Supuestos de mercado de la librería de la app (LTCMA de J.P. Morgan y "
            "activos propios) y su matriz de correlación; ninguna fuente externa.",
            "Retorno esperado = retorno aritmético anual del portafolio; "
            "volatilidad anual; ambos en decimales y en la moneda base "
            f"({self.base_currency}).",
            "Eficiencia = retorno esperado / volatilidad, sin tasa libre de riesgo "
            "(no es un Sharpe).",
            "Pesos entre los límites de cada activo, sin pesos negativos ni "
            "apalancamiento, sumando 100%. Activos no seleccionados en 0%.",
            "Optimización de un solo período con supuestos de largo plazo: no "
            "considera los flujos, el crédito, las metas ni el horizonte del caso. "
            "Su efecto sobre la probabilidad de éxito se ve al aplicarla y simular.",
        ]
        if self.cop_assets:
            notas.append(
                "Activos en COP llevados a USD con la devaluación esperada del caso "
                f"({', '.join(self.cop_assets)}). {self.fx_description}. El riesgo "
                "cambiario NO está incluido: la tasa sigue un camino fijo."
            )
        else:
            notas.append(
                "Todos los activos seleccionados están en USD: no se aplica conversión "
                "ni hay riesgo cambiario que modelar."
            )
        return notas


# --------------------------------------------------------------------------
# Álgebra del conjunto factible
# --------------------------------------------------------------------------


def project_capped_simplex(v: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Proyección euclídea sobre {lo ≤ w ≤ hi, Σw = 1}.

    La solución es `clip(v − τ, lo, hi)` para el `τ` que hace sumar 1; la suma
    es monótona en `τ`, así que se encuentra por bisección.
    """
    lo_t = float(np.min(v - hi)) - 1.0
    hi_t = float(np.max(v - lo)) + 1.0
    for _ in range(200):
        tau = 0.5 * (lo_t + hi_t)
        total = np.clip(v - tau, lo, hi).sum()
        if total > 1.0:
            lo_t = tau
        else:
            hi_t = tau
        if hi_t - lo_t < 1e-15:
            break
    return np.clip(v - 0.5 * (lo_t + hi_t), lo, hi)


def _max_return_weights(mu: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Solución exacta del problema lineal: mínimos, y el resto por orden de retorno."""
    w = lo.copy()
    remaining = 1.0 - w.sum()
    for i in np.argsort(-mu, kind="stable"):
        add = min(hi[i] - w[i], remaining)
        w[i] += add
        remaining -= add
        if remaining <= 1e-15:
            break
    return w


def solve_box_qp(q: np.ndarray, c: np.ndarray, lo: np.ndarray, hi: np.ndarray,
                 max_iter: int = 2_000) -> tuple[np.ndarray, int]:
    """min ½x'Qx + c'x  s.a.  Σx = 1,  lo ≤ x ≤ hi   (Q semidefinida positiva).

    Conjunto activo primal: los activos «fijos» están en uno de sus límites y
    el resto se resuelve con el sistema KKT de la igualdad. Si un paso se sale
    de un límite, ese activo se fija; si en el óptimo del subproblema algún
    multiplicador tiene el signo equivocado, ese activo se libera. Termina en un
    número finito de pasos con la solución exacta (salvo redondeo), y con 60
    activos tarda milisegundos.
    """
    n = len(lo)
    x = project_capped_simplex(np.full(n, 1.0 / n), lo, hi)
    at_lo = np.isclose(x, lo, atol=1e-14)
    at_hi = np.isclose(x, hi, atol=1e-14) & ~at_lo
    fixed = at_lo | at_hi
    if fixed.all():
        # Todos en un límite: se libera el de mejor gradiente para tener una
        # dirección; si no hay grados de libertad, x ya es la única solución.
        fixed[np.argmin(q @ x + c)] = False
    for k in range(1, max_iter + 1):
        free = np.flatnonzero(~fixed)
        g = q @ x + c
        nu = 0.0
        if free.size:
            m = free.size
            kkt = np.zeros((m + 1, m + 1))
            kkt[:m, :m] = q[np.ix_(free, free)]
            kkt[:m, m] = 1.0
            kkt[m, :m] = 1.0
            rhs = np.concatenate([-(c[free] + q[np.ix_(free, np.flatnonzero(fixed))]
                                    @ x[fixed]), [1.0 - x[fixed].sum()]])
            sol = np.linalg.lstsq(kkt, rhs, rcond=None)[0]
            target, nu = sol[:m], sol[m]
            p = target - x[free]
        else:
            p = np.zeros(0)
        if p.size and np.max(np.abs(p)) > 1e-13:
            # Paso hacia el óptimo del subproblema, cortado en el primer límite.
            alpha, block, block_hi = 1.0, -1, False
            for j, i in enumerate(free):
                if p[j] < 0 and x[i] + p[j] < lo[i]:
                    a = (lo[i] - x[i]) / p[j]
                    if a < alpha:
                        alpha, block, block_hi = a, i, False
                elif p[j] > 0 and x[i] + p[j] > hi[i]:
                    a = (hi[i] - x[i]) / p[j]
                    if a < alpha:
                        alpha, block, block_hi = a, i, True
            x[free] += alpha * p
            if block >= 0:
                x[block] = hi[block] if block_hi else lo[block]
                fixed[block] = True
                at_hi[block], at_lo[block] = block_hi, not block_hi
            continue
        # Óptimo del subproblema: multiplicadores de los límites activos.
        g = q @ x + c
        if not free.size:
            nu = -float(np.min(g[at_lo])) if at_lo.any() else -float(np.max(g[at_hi]))
        mult = g + nu
        bad_lo = np.where(fixed & at_lo & (mult < -1e-12), mult, 0.0)
        bad_hi = np.where(fixed & at_hi & (mult > 1e-12), -mult, 0.0)
        worst = np.minimum(bad_lo, bad_hi)
        if worst.min() >= 0:
            return x, k
        i = int(np.argmin(worst))
        fixed[i] = at_lo[i] = at_hi[i] = False
    return x, max_iter


def _ridge(cov: np.ndarray) -> np.ndarray:
    """Una diagonal mínima para que el KKT no sea singular con activos sin
    volatilidad o perfectamente correlacionados; mueve la varianza en ~1e-12."""
    scale = float(np.mean(np.diag(cov))) or 1.0
    return 2.0 * cov + np.eye(len(cov)) * scale * 1e-10


def _min_variance_weights(cov, lo, hi):
    return solve_box_qp(_ridge(cov), np.zeros(len(lo)), lo, hi)


def _frontier_weights(mu, cov, lo, hi, lam):
    """Portafolio de la frontera: min varianza − λ·retorno."""
    return solve_box_qp(_ridge(cov), -lam * mu, lo, hi)[0]


def _max_ratio_weights(mu, cov, lo, hi, candidates) -> tuple[np.ndarray, int]:
    """Máximo μ'w/σ(w) recorriendo la frontera eficiente.

    El portafolio de máxima eficiencia está en la frontera de media-varianza, y
    a lo largo de ella el cociente es unimodal (la tangente desde el origen la
    toca una sola vez). Se busca por sección áurea sobre log λ, y se compara con
    los extremos (`candidates`: mínima varianza y máximo retorno).
    """
    def ratio(w):
        v = float(np.sqrt(max(w @ cov @ w, 0.0)))
        return float(mu @ w) / v if v > ZERO_VOL else -np.inf

    golden = (np.sqrt(5.0) - 1.0) / 2.0
    a, b = np.log(1e-8), np.log(1e4)
    c1, c2 = b - golden * (b - a), a + golden * (b - a)
    w1, w2 = (_frontier_weights(mu, cov, lo, hi, np.exp(s)) for s in (c1, c2))
    f1, f2 = ratio(w1), ratio(w2)
    evaluations = 2
    while b - a > 1e-9:
        if f1 >= f2:
            b, c2, w2, f2 = c2, c1, w1, f1
            c1 = b - golden * (b - a)
            w1 = _frontier_weights(mu, cov, lo, hi, np.exp(c1)); f1 = ratio(w1)
        else:
            a, c1, w1, f1 = c1, c2, w2, f2
            c2 = a + golden * (b - a)
            w2 = _frontier_weights(mu, cov, lo, hi, np.exp(c2)); f2 = ratio(w2)
        evaluations += 1
    best = max([w1, w2, *candidates], key=ratio)
    return best, evaluations


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def portfolio_stats(weights: dict[str, float], cmas_usd: CMASet,
                    correlations: CorrelationMatrix) -> PortfolioStats:
    """Cifras de un portafolio con las mismas fórmulas que Supuestos (`summarize`)."""
    clean = {k: float(v) for k, v in weights.items() if v > WEIGHT_TOL}
    names = list(clean)
    summary = summarize(Allocation("p", clean), cmas_usd, correlations.subset(names))
    ratio = (summary.arithmetic_return / summary.volatility
             if summary.volatility > ZERO_VOL else float("nan"))
    total = sum(clean.values())
    return PortfolioStats(
        weights={k: v / total for k, v in clean.items()},
        expected_return=summary.arithmetic_return,
        compound_return=summary.compound_return,
        volatility=summary.volatility,
        ratio=ratio,
    )


def _clean(w: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Quita el ruido numérico (pesos de 1e-12) sin salirse de los límites."""
    w = np.where((w < WEIGHT_TOL) & (lo <= 0), 0.0, w)
    return project_capped_simplex(w, lo, hi)


def check_bounds(names: list[str], bounds: dict[str, tuple[float, float]] | None
                 ) -> tuple[np.ndarray, np.ndarray]:
    bounds = bounds or {}
    lo = np.array([float(bounds.get(n, (0.0, 1.0))[0]) for n in names])
    hi = np.array([float(bounds.get(n, (0.0, 1.0))[1]) for n in names])
    problems = []
    for n, a, b in zip(names, lo, hi):
        if not (np.isfinite(a) and np.isfinite(b)):
            problems.append(f"{n}: límites no numéricos")
        elif a < 0 or b > 1:
            problems.append(f"{n}: los límites deben estar entre 0% y 100%")
        elif a > b + 1e-12:
            problems.append(f"{n}: el mínimo ({a:.1%}) supera al máximo ({b:.1%})")
    if problems:
        raise OptimizationError("Límites inválidos. " + "; ".join(problems) + ".")
    if lo.sum() > 1.0 + 1e-9:
        raise OptimizationError(
            f"Los mínimos suman {lo.sum():.1%}: con más de 100% no hay portafolio "
            "posible. Baja algún mínimo."
        )
    if hi.sum() < 1.0 - 1e-9:
        raise OptimizationError(
            f"Los máximos suman {hi.sum():.1%}: no alcanzan para el 100%. Sube algún "
            "máximo o selecciona más activos."
        )
    return lo, hi


def optimize(
    scenario: Scenario,
    strategy_name: str,
    assets: list[str],
    cmas: CMASet,
    correlations: CorrelationMatrix,
    bounds: dict[str, tuple[float, float]] | None = None,
    objectives: tuple[str, ...] = (MAX_RETURN, MIN_VOLATILITY, MAX_EFFICIENCY),
) -> OptimizationReport:
    """Las alternativas pedidas para los `assets` seleccionados. No toca `scenario`.

    Levanta `OptimizationError` si faltan datos para plantear el problema; si el
    problema está bien planteado pero una alternativa no tiene solución útil,
    esa alternativa vuelve sin pesos y con el motivo en `message`.
    """
    names = list(dict.fromkeys(assets))
    if not names:
        raise OptimizationError("Selecciona al menos un activo para optimizar.")
    strategy = next((s for s in scenario.strategies if s.name == strategy_name), None)
    if strategy is None:
        raise OptimizationError(f"No hay una estrategia llamada «{strategy_name}».")

    missing = [n for n in names if n not in cmas.names]
    if missing:
        raise OptimizationError(
            "Faltan los supuestos (retorno y volatilidad) de: " + ", ".join(missing) + "."
        )
    not_in_corr = [n for n in names if n not in correlations.names]
    if not_in_corr:
        raise OptimizationError(
            "La matriz de correlación no cubre: " + ", ".join(not_in_corr) + "."
        )

    cop_assets = [n for n in names if cmas.by_name(n).currency == "COP"]
    if cop_assets and scenario.peso is None:
        raise OptimizationError(
            "Hay activos en COP (" + ", ".join(cop_assets) + ") y el caso no tiene tasa "
            "USD/COP: sin ella no se pueden llevar a la moneda base. Escríbela en "
            "Escenario › Pesos colombianos."
        )
    cmas_usd = cmas.in_usd(scenario.peso.devaluation if scenario.peso else None)

    lo, hi = check_bounds(names, bounds)
    mu = np.array([cmas_usd.by_name(n).arithmetic_return for n in names])
    sigmas = np.array([cmas_usd.by_name(n).volatility for n in names])
    if not (np.all(np.isfinite(mu)) and np.all(np.isfinite(sigmas))):
        raise OptimizationError("Hay supuestos de retorno o volatilidad no numéricos.")
    cov = covariance(sigmas, correlations.subset(names))

    def stats(w: np.ndarray) -> PortfolioStats:
        return portfolio_stats(dict(zip(names, _clean(w, lo, hi))), cmas_usd, correlations)

    outcomes: dict[str, OptimizationOutcome] = {}
    if MAX_RETURN in objectives:
        outcomes[MAX_RETURN] = OptimizationOutcome(
            MAX_RETURN, stats(_max_return_weights(mu, lo, hi)), iterations=1
        )

    min_var_w, it = _min_variance_weights(cov, lo, hi)
    min_vol = float(np.sqrt(max(min_var_w @ cov @ min_var_w, 0.0)))
    if MIN_VOLATILITY in objectives:
        outcomes[MIN_VOLATILITY] = OptimizationOutcome(MIN_VOLATILITY, stats(min_var_w),
                                                       iterations=it)

    if MAX_EFFICIENCY in objectives:
        outcomes[MAX_EFFICIENCY] = _efficiency(mu, cov, lo, hi, min_var_w, min_vol, stats)

    current = None
    try:
        current = portfolio_stats(
            dict(strategy.weights), cmas_usd, correlations
        ) if strategy.asset_names else None
    except (KeyError, ValueError):
        current = None

    return OptimizationReport(
        strategy_name=strategy_name,
        assets=names,
        bounds={n: (float(a), float(b)) for n, a, b in zip(names, lo, hi)},
        outcomes=outcomes,
        current=current,
        fx_description=describe_rate(scenario.peso),
        cop_assets=cop_assets,
    )


def _efficiency(mu, cov, lo, hi, min_var_w, min_vol, stats) -> OptimizationOutcome:
    if min_vol <= ZERO_VOL:
        return OptimizationOutcome(
            MAX_EFFICIENCY,
            message="Con estos activos y límites existe un portafolio de volatilidad "
            "cero, así que el cociente retorno/volatilidad no está definido (sería "
            "infinito). Quita los activos sin volatilidad o fíjales un máximo.",
        )
    max_ret_w = _max_return_weights(mu, lo, hi)
    if float(mu @ max_ret_w) <= 0:
        return OptimizationOutcome(
            MAX_EFFICIENCY,
            message="Ningún portafolio posible con estos activos tiene retorno "
            "esperado positivo: maximizar retorno/volatilidad no tendría sentido.",
        )
    # Arranque con cociente positivo: el de mínima varianza si lo es, si no el
    # de máximo retorno.
    w, iterations = _max_ratio_weights(mu, cov, lo, hi, [min_var_w, max_ret_w])
    return OptimizationOutcome(MAX_EFFICIENCY, stats(w), iterations=iterations)
