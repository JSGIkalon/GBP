"""Flujos de entrada (aportes) y salida (gastos, retiros) del portafolio.

Convención de años: el año 1 es el primer año proyectado. Un flujo activo
entre `start_year` y `end_year` inclusive ocurre una vez por año.

Un flujo se expresa de una de dos formas, que es lo que distingue `FlowBasis`:

* **Monto fijo** (`FlowBasis.AMOUNT`): una cifra en moneda de hoy, indexada a la
  inflación del escenario. Se conoce año por año antes de simular, así que el
  motor la precalcula en un vector.
* **Porcentaje del patrimonio** (`FlowBasis.PORTFOLIO_PCT`): una fracción del
  patrimonio vigente de ese año, al estilo de la regla del 4% de un endowment.
  **No se puede precalcular**: depende del valor que tenga el portafolio en cada
  camino y cada año, así que se aplica dentro del bucle de simulación.

La diferencia no es cosmética. Un retiro porcentual se autorregula —si el
mercado cae, el retiro cae con él— y por eso nunca agota el portafolio, a costa
de que el gasto sea volátil. Un monto fijo mantiene el gasto estable y traslada
todo el riesgo al patrimonio, que sí se puede agotar.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class FlowKind(str, Enum):
    INFLOW = "aporte"
    OUTFLOW = "retiro"


class FlowBasis(str, Enum):
    AMOUNT = "monto"
    PORTFOLIO_PCT = "% patrimonio"


@dataclass
class CashFlow:
    """Un flujo recurrente o puntual.

    `amount` siempre es positivo; el signo lo determina `kind`. Su unidad la
    determina `basis`: una cifra en moneda de hoy si es `AMOUNT`, o una fracción
    del patrimonio (0.04 = 4%) si es `PORTFOLIO_PCT`.

    Para un flujo de monto fijo, el crecimiento anual puede venir de dos fuentes
    que se acumulan:

    * `inflation_indexed`: el flujo sigue la inflación del escenario (típico de
      gastos de estilo de vida, como el "USD 1.1MM por año" del ejemplo de JPM).
    * `growth`: crecimiento real adicional, por encima de la inflación.

    Un flujo porcentual ignora ambos: la fracción se aplica sobre un patrimonio
    que ya creció, así que indexarla además a la inflación la contaría dos veces.
    `__post_init__` lo normaliza en vez de confiar en que la UI no los envíe.
    """

    name: str
    kind: FlowKind
    amount: float
    start_year: int
    end_year: int
    inflation_indexed: bool = True
    growth: float = 0.0
    basis: FlowBasis = FlowBasis.AMOUNT

    def __post_init__(self) -> None:
        if isinstance(self.kind, str):
            self.kind = FlowKind(self.kind)
        if isinstance(self.basis, str):
            self.basis = FlowBasis(self.basis)
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
        if self.is_percentage:
            if self.amount > 1.0:
                raise ValueError(
                    f"{self.name}: un flujo porcentual se expresa como fracción "
                    f"(0.04 = 4%); {self.amount} sería {self.amount:.0%} del patrimonio."
                )
            self.inflation_indexed = False
            self.growth = 0.0

    @property
    def sign(self) -> int:
        return 1 if self.kind is FlowKind.INFLOW else -1

    @property
    def is_percentage(self) -> bool:
        return self.basis is FlowBasis.PORTFOLIO_PCT

    def schedule(self, horizon: int, inflation: float) -> np.ndarray:
        """Vector de longitud `horizon` con el flujo firmado de cada año.

        El índice 0 corresponde al año 1. El monto ingresado es **el del año 1**
        y se indexa desde el año 2, con factor `(1 + tasa)^(year - 1)`: un
        retiro de 1.000 con inflación de 5% vale 1.000 el año 1 y 1.050 el año
        2. Un flujo que empieza más tarde también se expresa en pesos del año 1,
        así que el año 5 ya llega con cuatro años de indexación.

        J.P. Morgan indexa desde el año 1 (`(1 + tasa)^year`), y con esa
        convención el caso de la lámina 9 reproducía su total de 47.2MM. Se
        cambió a pedido de Ikalon, que ingresa el retiro del primer año tal
        cual; con la nueva convención ese total da 46.0MM.

        Un flujo porcentual devuelve ceros: su monto no existe hasta que hay un
        patrimonio sobre el cual calcularlo. Se obtiene con `rate_schedule`.
        """
        flows = np.zeros(horizon, dtype=float)
        if self.is_percentage:
            return flows
        rate = (1.0 + (inflation if self.inflation_indexed else 0.0)) * (1.0 + self.growth) - 1.0
        last = min(self.end_year, horizon)
        for year in range(self.start_year, last + 1):
            flows[year - 1] += self.sign * self.amount * (1.0 + rate) ** (year - 1)
        return flows

    def rate_schedule(self, horizon: int) -> np.ndarray:
        """Vector de longitud `horizon` con la fracción firmada de cada año.

        Ceros para un flujo de monto fijo, que se obtiene con `schedule`. Las dos
        vistas son excluyentes: ningún flujo aporta a ambas, así que sumarlas por
        separado cubre la lista entera sin contar nada dos veces.
        """
        rates = np.zeros(horizon, dtype=float)
        if not self.is_percentage:
            return rates
        last = min(self.end_year, horizon)
        for year in range(self.start_year, last + 1):
            rates[year - 1] += self.sign * self.amount
        return rates


def combined_schedule(
    flows: list[CashFlow], horizon: int, inflation: float
) -> np.ndarray:
    """Suma de los flujos de monto fijo por año (positivo = entrada neta).

    Los flujos porcentuales no entran: no tienen monto conocido fuera de la
    simulación. Quien muestre totales debe reportarlos aparte, no sumarlos como
    si fueran cero.
    """
    total = np.zeros(horizon, dtype=float)
    for flow in flows:
        total += flow.schedule(horizon, inflation)
    return total


def combined_rate_schedule(flows: list[CashFlow], horizon: int) -> np.ndarray:
    """Suma de las fracciones porcentuales por año (positivo = entrada neta)."""
    total = np.zeros(horizon, dtype=float)
    for flow in flows:
        total += flow.rate_schedule(horizon)
    return total
