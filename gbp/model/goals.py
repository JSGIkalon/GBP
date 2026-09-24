"""Metas del cliente y su probabilidad de cumplirse.

Una meta es un patrimonio neto mínimo en un año: «tener 10.000.000 en el año
15», o un legado —«dejar 5.000.000 al final»—, que es la misma meta con el año
en el final del horizonte.

Las metas **no cambian la simulación**: se evalúan sobre los caminos que ya
salieron de ella. Por eso agregar o quitar una meta no mueve ni una cifra del
resto del caso, y no hace falta volver a correr para verla.

Cuándo se cumple
----------------
En un camino, la meta se cumple si el patrimonio neto de ese año es **al menos**
el monto, y el camino **no se agotó antes**. La segunda condición importa: un
patrimonio que se agotó en el año 8 y volvió a crecer por aportes posteriores no
cumplió la meta del año 15 en ningún sentido que le importe al cliente, porque
en el medio se quedó sin plata.

El monto puede estar en moneda de hoy (`real=True`, lo normal: «lo que hoy
compran 10.000.000») o en valores nominales.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class GoalPriority(str, Enum):
    """Solo una etiqueta para ordenar la lectura; no pesa en ningún cálculo."""

    ESSENTIAL = "esencial"
    IMPORTANT = "importante"
    ASPIRATIONAL = "deseable"


@dataclass
class Goal:
    """Patrimonio neto mínimo en un año del horizonte.

    `year=None` significa el último año del horizonte, sea cual sea: una meta de
    legado sigue siéndolo aunque después se alargue el horizonte.
    """

    name: str
    amount: float
    year: int | None = None
    real: bool = True
    priority: GoalPriority = GoalPriority.IMPORTANT

    def __post_init__(self) -> None:
        if isinstance(self.priority, str):
            self.priority = GoalPriority(self.priority)
        if self.amount < 0:
            raise ValueError(f"{self.name}: el monto de la meta no puede ser negativo.")
        if self.year is not None and self.year < 1:
            raise ValueError(f"{self.name}: el año de la meta debe ser 1 o mayor.")

    def resolved_year(self, horizon: int) -> int:
        """Año en que se mide: el propio, o el final del horizonte."""
        return horizon if self.year is None else self.year

    def fits(self, horizon: int) -> bool:
        return self.resolved_year(horizon) <= horizon

    def describe(self, horizon: int) -> str:
        cuando = "al final" if self.year is None else f"en el año {self.year}"
        return f"{self.name} ({cuando})"


def goal_probability(strategy_result, goal: Goal) -> float:
    """Fracción de caminos en que la meta se cumple.

    Devuelve `nan` si el año de la meta cae fuera del horizonte simulado: no
    es que la probabilidad sea cero, es que la corrida no llegó hasta ahí.
    """
    horizon = strategy_result.horizon
    if not goal.fits(horizon):
        return float("nan")
    year = goal.resolved_year(horizon)
    wealth = strategy_result.wealth[:, :year]
    at_year = wealth[:, year - 1]
    if goal.real and strategy_result.inflation_factors.size:
        at_year = at_year / strategy_result.inflation_factors[year - 1]
    # Sin agotarse **antes** del año de la meta: el propio año lo decide el
    # monto, que para una meta positiva ya exige patrimonio positivo.
    alive_before = (wealth[:, : year - 1] > 0).all(axis=1) if year > 1 else True
    return float(np.mean((at_year >= goal.amount) & alive_before))
