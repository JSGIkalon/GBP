"""Solver: la cifra del plan que logra una probabilidad objetivo.

La corrida normal responde «con este retiro, ¿qué probabilidad hay de que la
plata alcance?». El solver responde la pregunta inversa: «¿cuánto puedo retirar
para que la probabilidad sea al menos 85%?», o cuánto hay que aportar, o con
cuánto capital hay que empezar.

Método
------
1. Se sortean los caminos de mercado **una sola vez**, con la misma semilla y el
   mismo número de caminos que la corrida normal.
2. Sobre ese mismo mercado se proyecta la estrategia con distintos valores de la
   cifra elegida. Como el mercado no cambia entre prueba y prueba, lo único que
   mueve la probabilidad es la cifra: más retiro nunca sube la probabilidad, más
   aporte o más capital nunca la baja. Esa monotonía es la que permite buscar
   por **bisección** en vez de probar a ciegas.
3. Primero se acota: se duplica la cifra hasta cruzar el objetivo. Después se
   parte el intervalo por la mitad hasta que mida menos de 0,1% del valor.
4. Se devuelve el valor **del lado seguro**: el retiro máximo que todavía cumple
   el objetivo, o el aporte o capital mínimo que ya lo cumple, redondeado en la
   dirección que no lo rompe.

El caso **no se modifica**: cada prueba se hace sobre una copia de la estrategia.
Aplicar el resultado es una decisión aparte, desde la interfaz.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field

from ..model.assets import CMASet
from ..model.cashflows import FlowKind
from ..model.correlation import CorrelationMatrix
from ..model.goals import goal_probability
from ..model.scenario import Scenario, SimulationSettings
from .montecarlo import draw_market, simulate_strategy, usd_cmas

# Topes de la búsqueda. Un monto que no cruza el objetivo ni en billones no lo
# va a cruzar nunca; un porcentaje no puede pasar del 100% del patrimonio.
AMOUNT_CAP = 1e15
PERCENT_CAP = 1.0
MAX_ITERATIONS = 40
RELATIVE_TOLERANCE = 0.001

CAPITAL = "capital"
FLOW = "flow"
SUCCESS = "success"
GOAL = "goal"


@dataclass(frozen=True)
class Variable:
    """La cifra que el solver ajusta: el monto de un flujo o el capital inicial."""

    kind: str  # FLOW o CAPITAL
    flow_index: int | None = None


@dataclass(frozen=True)
class Metric:
    """La probabilidad que se quiere alcanzar: la de éxito o la de una meta."""

    kind: str  # SUCCESS o GOAL
    goal_index: int | None = None


@dataclass
class SolveResult:
    strategy_name: str
    variable_label: str
    metric_label: str
    target: float
    # `True`: se busca el valor más alto que cumple (un retiro). `False`: el más
    # bajo que cumple (un aporte, el capital).
    maximize: bool
    is_percentage: bool
    current_value: float
    current_probability: float
    value: float | None = None
    achieved: float | None = None
    message: str = ""
    evaluations: int = 0
    n_paths: int = 0
    # Los puntos probados, (valor, probabilidad), ordenados por valor. Sirven
    # para dibujar la curva y para auditar la búsqueda.
    curve: list[tuple[float, float]] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.value is not None


def describe_variable(strategy, variable: Variable) -> tuple[str, bool, bool]:
    """Rótulo de la variable, si es porcentual y si se maximiza."""
    if variable.kind == CAPITAL:
        return "Capital inicial", False, False
    flow = strategy.cashflows[variable.flow_index]
    tipo = "Retiro" if flow.kind is FlowKind.OUTFLOW else "Aporte"
    unidad = "% del patrimonio" if flow.is_percentage else "monto anual"
    return f"{tipo} · {flow.name} ({unidad})", flow.is_percentage, flow.kind is FlowKind.OUTFLOW


def describe_metric(scenario: Scenario, metric: Metric) -> str:
    if metric.kind == SUCCESS:
        return "Probabilidad de éxito"
    goal = scenario.goals[metric.goal_index]
    return f"Meta · {goal.describe(scenario.horizon)}"


def _get(strategy, scenario: Scenario, variable: Variable) -> float:
    if variable.kind == CAPITAL:
        return float(strategy.resolved_initial(scenario.initial_value))
    return float(strategy.cashflows[variable.flow_index].amount)


def _set(strategy, variable: Variable, value: float) -> None:
    if variable.kind == CAPITAL:
        strategy.initial_value = value
    else:
        strategy.cashflows[variable.flow_index].amount = value


def solve(
    scenario: Scenario,
    strategy_name: str,
    variable: Variable,
    metric: Metric,
    target: float,
    cmas: CMASet,
    correlations: CorrelationMatrix,
    settings: SimulationSettings,
    progress: Callable[[int, str], None] | None = None,
) -> SolveResult:
    """Busca la cifra que lleva la probabilidad al objetivo. No toca `scenario`."""
    if not 0 < target < 1:
        raise ValueError("La probabilidad objetivo debe estar entre 0% y 100%.")
    scenario.validate(cmas)
    strategy = next((s for s in scenario.strategies if s.name == strategy_name), None)
    if strategy is None:
        raise ValueError(f"No hay una estrategia llamada «{strategy_name}».")
    if variable.kind == FLOW and not (
        variable.flow_index is not None and 0 <= variable.flow_index < len(strategy.cashflows)
    ):
        raise ValueError("El flujo elegido no existe en la estrategia.")
    if metric.kind == GOAL and not (
        metric.goal_index is not None and 0 <= metric.goal_index < len(scenario.goals)
    ):
        raise ValueError("La meta elegida no existe en el caso.")

    label, is_pct, maximize = describe_variable(strategy, variable)
    goal = scenario.goals[metric.goal_index] if metric.kind == GOAL else None
    if goal is not None and not goal.fits(scenario.horizon):
        raise ValueError("La meta cae después del final del horizonte.")

    if progress:
        progress(0, "Sorteando los caminos de mercado…")
    cmas = usd_cmas(scenario, cmas)
    market = draw_market(scenario, cmas, correlations, settings)
    cache: dict[float, float] = {}

    def probability(value: float) -> float:
        if value in cache:
            return cache[value]
        trial = deepcopy(strategy)
        _set(trial, variable, value)
        result = simulate_strategy(
            trial, scenario.horizon, scenario.inflation, scenario.initial_value, cmas, market,
            peso=scenario.peso,
        )
        p = result.success_probability if goal is None else goal_probability(result, goal)
        cache[value] = p
        if progress:
            progress(len(cache), f"Probando {len(cache)}…")
        return p

    current = _get(strategy, scenario, variable)
    out = SolveResult(
        strategy_name=strategy.name,
        variable_label=label,
        metric_label=describe_metric(scenario, metric),
        target=target,
        maximize=maximize,
        is_percentage=is_pct,
        current_value=current,
        current_probability=probability(current),
        n_paths=settings.n_paths,
    )

    cap = PERCENT_CAP if is_pct else AMOUNT_CAP
    meets = lambda v: probability(v) >= target  # noqa: E731

    if maximize:
        # Más retiro, menos probabilidad. Se busca el borde: el último valor que
        # todavía cumple.
        if not meets(0.0):
            out.message = (
                "El objetivo no se alcanza ni sin este retiro: la probabilidad con "
                f"retiro cero es {probability(0.0):.1%}."
            )
            return _finish(out, cache)
        low, high = 0.0, max(current, 0.01 if is_pct else 1.0)
        while meets(high):
            low = high
            if high >= cap:
                out.value, out.achieved = cap, probability(cap)
                out.message = "Cualquier valor hasta el tope cumple el objetivo."
                return _finish(out, cache)
            high = min(high * 2, cap)
    else:
        # Más aporte o capital, más probabilidad. Se busca el primer valor que
        # ya cumple.
        if meets(0.0):
            out.value, out.achieved = 0.0, probability(0.0)
            out.message = "El objetivo ya se cumple sin esta cifra."
            return _finish(out, cache)
        low, high = 0.0, max(current, 0.01 if is_pct else 1.0)
        while not meets(high):
            low = high
            if high >= cap:
                out.message = (
                    "El objetivo no se alcanza ni con el máximo que admite la búsqueda: "
                    f"la probabilidad llega a {probability(cap):.1%}."
                )
                return _finish(out, cache)
            high = min(high * 2, cap)

    for _ in range(MAX_ITERATIONS):
        if high - low <= RELATIVE_TOLERANCE * max(abs(high), 1e-9):
            break
        mid = (low + high) / 2
        if meets(mid) == maximize:
            low = mid
        else:
            high = mid

    value = _round_safe(low if maximize else high, is_pct, maximize)
    # El redondeo va hacia el lado seguro, pero se confirma: si por la forma
    # escalonada de la probabilidad el valor redondeado no cumpliera, se usa el
    # borde sin redondear, que sí cumple por construcción.
    if not meets(value):
        value = low if maximize else high
    out.value, out.achieved = value, probability(value)
    return _finish(out, cache)


def _round_safe(value: float, is_pct: bool, maximize: bool) -> float:
    """Redondea hacia el lado que no rompe el objetivo."""
    step = 1e-4 if is_pct else 1.0  # 0,01 punto porcentual, o una unidad
    scaled = value / step
    scaled = math.floor(scaled + 1e-9) if maximize else math.ceil(scaled - 1e-9)
    return max(scaled * step, 0.0)


def _finish(out: SolveResult, cache: dict[float, float]) -> SolveResult:
    out.evaluations = len(cache)
    out.curve = sorted(cache.items())
    return out
