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

Moneda
------
Una meta puede escribirse en USD o en COP. El patrimonio se simula en USD, así
que una meta en pesos se convierte a un umbral en dólares con la tasa
determinística del caso (`PesoAssumptions`):

* nominal: ``monto / S_t``;
* de hoy:  ``monto · (1 + π_COP)^t / S_t`` en USD nominales. Con la inflación
  colombiana de paridad esto es lo mismo que una meta de hoy de
  ``monto / spot`` dólares.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


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
    currency: str = field(default="USD", kw_only=True)

    def __post_init__(self) -> None:
        if self.currency not in ("USD", "COP"):
            raise ValueError(f"{self.name}: moneda desconocida {self.currency!r}.")
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


def _cop_threshold(goal: Goal, year: int, peso, usd_factor: float | None):
    """Umbral de la meta en COP llevado a USD: (monto, ¿es real en USD?)."""
    if peso is None:
        raise ValueError(
            f"{goal.name}: la meta está en COP y el caso no tiene tasa USD/COP."
        )
    if not goal.real:
        return goal.amount / peso.rate(year), False
    if peso.inflation is None:
        # Paridad: la inflación COP es la USD con la devaluación, así que la
        # meta de hoy en pesos es una meta de hoy en dólares a la tasa inicial.
        return goal.amount / peso.spot, True
    nominal = goal.amount * (1.0 + peso.inflation) ** year / peso.rate(year)
    return nominal, False


def goal_amount_usd(goal: Goal, horizon: int, peso=None) -> tuple[float, bool]:
    """El monto de la meta en USD y si es de hoy (real) o nominal.

    Una meta en USD vuelve tal cual. Sirve para mostrarla junto al patrimonio.
    """
    if goal.currency != "COP":
        return goal.amount, goal.real
    return _cop_threshold(goal, goal.resolved_year(horizon), peso, None)


def goal_probability(strategy_result, goal: Goal, peso=None) -> float:
    """Fracción de caminos en que la meta se cumple.

    Devuelve `nan` si el año de la meta cae fuera del horizonte simulado: no
    es que la probabilidad sea cero, es que la corrida no llegó hasta ahí.
    """
    cache = getattr(strategy_result, "_cache", None)
    key = ("goal", goal.amount, goal.year, goal.real, goal.currency,
           None if peso is None else (peso.spot, peso.devaluation, peso.inflation))
    if cache is not None and key in cache:
        return cache[key]
    p = _goal_probability(strategy_result, goal, peso)
    if cache is not None:
        cache[key] = p
    return p


def _goal_probability(strategy_result, goal: Goal, peso=None) -> float:
    horizon = strategy_result.horizon
    if not goal.fits(horizon):
        return float("nan")
    year = goal.resolved_year(horizon)
    wealth = strategy_result.wealth[:, :year]
    at_year = wealth[:, year - 1]
    amount, real = goal.amount, goal.real
    if goal.currency == "COP":
        amount, real = _cop_threshold(goal, year, peso, None)
    if real and strategy_result.inflation_factors.size:
        at_year = at_year / strategy_result.inflation_factors[year - 1]
    # Sin agotarse **antes** del año de la meta: el propio año lo decide el
    # monto, que para una meta positiva ya exige patrimonio positivo.
    alive_before = (wealth[:, : year - 1] > 0).all(axis=1) if year > 1 else True
    return float(np.mean((at_year >= amount) & alive_before))
