"""Estrategia: una asignación con sus propios flujos, crédito y capital.

Una estrategia es un **caso completo**, no solo una mezcla de activos: lleva sus
aportes y retiros, su crédito y, si se quiere, su propio capital inicial. Así se
pueden comparar dos planes de verdad distintos en la misma corrida —por ejemplo
uno apalancado contra uno sin deuda, o uno con retiros tempranos contra otro que
los aplaza— y no solo dos mezclas de activos.

La `Allocation` que contiene sigue siendo solo pesos: es lo que consumen el
cálculo de supuestos resumen y la vista de asignación, que no saben nada de
flujos.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .allocation import Allocation
from .cashflows import CashFlow
from .leverage import LoanTerms


@dataclass
class Strategy:
    """Un caso completo a simular.

    Attributes
    ----------
    allocation:
        Pesos por clase de activo. Su nombre identifica a la estrategia.
    cashflows:
        Aportes y retiros propios de esta estrategia.
    loan:
        Crédito propio de esta estrategia, o `None` si no usa apalancamiento.
    initial_value:
        Capital inicial propio. `None` —el caso normal— hereda el del escenario,
        que es lo que mantiene honesta la comparación: mismo punto de partida,
        distinta estrategia.
    """

    allocation: Allocation
    cashflows: list[CashFlow] = field(default_factory=list)
    loan: LoanTerms | None = None
    initial_value: float | None = None

    def __post_init__(self) -> None:
        if self.initial_value is not None and self.initial_value < 0:
            raise ValueError(f"{self.name}: el capital inicial no puede ser negativo.")

    @property
    def name(self) -> str:
        return self.allocation.name

    @name.setter
    def name(self, value: str) -> None:
        self.allocation.name = value

    @property
    def weights(self) -> dict[str, float]:
        return self.allocation.weights

    @property
    def asset_names(self) -> list[str]:
        return self.allocation.asset_names

    @property
    def has_own_initial(self) -> bool:
        return self.initial_value is not None

    @property
    def has_loan(self) -> bool:
        return self.loan is not None and self.loan.active

    def resolved_initial(self, scenario_initial: float) -> float:
        """Capital con el que arranca: el propio si lo tiene, si no el del escenario."""
        return self.initial_value if self.initial_value is not None else scenario_initial

    def copy(self, new_name: str) -> "Strategy":
        """Duplicado independiente, con otro nombre.

        Los flujos y el crédito se copian por valor: editar el duplicado no debe
        tocar el original.
        """
        from copy import deepcopy

        return Strategy(
            allocation=Allocation(new_name, dict(self.allocation.weights)),
            cashflows=deepcopy(self.cashflows),
            loan=deepcopy(self.loan),
            initial_value=self.initial_value,
        )
