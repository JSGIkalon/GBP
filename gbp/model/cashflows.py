"""Flujos de entrada (aportes) y salida (gastos, retiros) del portafolio.

Convención de años: el año 1 es el primer año proyectado. Un flujo activo
entre `start_year` y `end_year` inclusive ocurre una vez por año.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class FlowKind(str, Enum):
    INFLOW = "aporte"
    OUTFLOW = "retiro"


@dataclass
class CashFlow:
    """Un flujo recurrente o puntual.

    `amount` siempre es positivo; el signo lo determina `kind`.

    El crecimiento anual del flujo puede venir de dos fuentes, que se acumulan:

    * `inflation_indexed`: el flujo sigue la inflación del escenario (típico de
      gastos de estilo de vida, como el "USD 1.1MM por año" del ejemplo de JPM).
    * `growth`: crecimiento real adicional, por encima de la inflación.
    """

    name: str
    kind: FlowKind
    amount: float
    start_year: int
    end_year: int
    inflation_indexed: bool = True
    growth: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.kind, str):
            self.kind = FlowKind(self.kind)
        if self.amount < 0:
            raise ValueError(
                f"{self.name}: el monto debe ser positivo; el signo lo define el tipo de flujo."
            )
        if self.start_year < 1:
            raise ValueError(f"{self.name}: el año inicial debe ser 1 o mayor.")
        if self.end_year < self.start_year:
            raise ValueError(
                f"{self.name}: el año final ({self.end_year}) es anterior al inicial "
                f"({self.start_year})."
            )

    @property
    def sign(self) -> int:
        return 1 if self.kind is FlowKind.INFLOW else -1

    def schedule(self, horizon: int, inflation: float) -> np.ndarray:
        """Vector de longitud `horizon` con el flujo firmado de cada año.

        El índice 0 corresponde al año 1. El monto se ingresa en **moneda de
        hoy** (año 0) y se indexa desde el primer año proyectado, es decir con
        factor `(1 + tasa)^year`. Esa es la convención de J.P. Morgan: para el
        caso de la lámina 9 —1.1MM al año durante 29 años con inflación de
        2.5%— reproduce exactamente el total de 47.2MM que reporta el PDF.
        """
        flows = np.zeros(horizon, dtype=float)
        rate = (1.0 + (inflation if self.inflation_indexed else 0.0)) * (1.0 + self.growth) - 1.0
        last = min(self.end_year, horizon)
        for year in range(self.start_year, last + 1):
            flows[year - 1] += self.sign * self.amount * (1.0 + rate) ** year
        return flows


def combined_schedule(
    flows: list[CashFlow], horizon: int, inflation: float
) -> np.ndarray:
    """Suma de todos los flujos por año (positivo = entrada neta)."""
    total = np.zeros(horizon, dtype=float)
    for flow in flows:
        total += flow.schedule(horizon, inflation)
    return total
