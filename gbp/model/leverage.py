"""Apalancamiento: crédito con amortización, capitalización y margin call.

El crédito se simula camino a camino porque dos cosas dependen del escenario:
la tasa, cuando se define como spread sobre la tasa de caja, y las llamadas a
margen, que dependen del valor del portafolio en ese camino.

Convención de amortización
--------------------------
El cronograma de amortización se expresa como fracciones del **principal
original** y se calcula una sola vez, con una tasa de referencia determinística
(la tasa fija, o la tasa de caja esperada más el spread). Eso mantiene la cuota
estable aunque la tasa realizada varíe entre caminos, que es como funciona un
crédito en la práctica. Cualquier saldo remanente al vencimiento —el caso típico
cuando los intereses se capitalizan— se paga íntegro en el último año.

Moneda
------
Un crédito puede estar en USD o en COP. El saldo se lleva **en la moneda del
crédito** y se convierte al cruzar al portafolio, que vive en USD, con la tasa
determinística del caso (`PesoAssumptions`): desembolso, intereses y cuotas del
año `t` a la tasa del inicio del año, ``S_(t−1)`` (igual que los flujos), y el
saldo —para el LTV y el patrimonio neto— a la de cierre, ``S_t``. Así, con
devaluación, la deuda en pesos pesa cada vez menos en dólares.

La tasa fija se lee en pesos. En modo spread, la base es la caja USD llevada a
pesos por paridad, ``(1 + caja)(1 + devaluación) − 1``, más el spread.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class RateMode(str, Enum):
    FIXED = "fija"
    SPREAD_OVER_CASH = "spread sobre caja"


class InterestMode(str, Enum):
    PAID = "pagado"
    CAPITALIZED = "capitalizado"


class Amortization(str, Enum):
    BULLET = "bullet"
    LINEAR = "lineal"
    FRENCH = "cuota fija"


@dataclass
class LoanTerms:
    """Condiciones de un crédito.

    Attributes
    ----------
    principal:
        Monto desembolsado, que ingresa al portafolio en el año `start_year`.
    start_year:
        Año en que se desembolsa (1 = primer año proyectado).
    term_years:
        Plazo en años desde el desembolso. Al final del plazo el saldo queda en cero.
    rate / spread:
        `rate` es la tasa fija anual; `spread` es el diferencial sobre la tasa de
        caja cuando `rate_mode` es SPREAD_OVER_CASH.
    max_ltv:
        Loan-to-value máximo. Si el saldo supera esa fracción del valor del
        portafolio, se liquidan activos para volver a `target_ltv`. `None`
        desactiva el control.
    target_ltv:
        LTV al que se regresa tras una llamada a margen. Por defecto, `max_ltv`.
    """

    name: str = "Crédito"
    principal: float = 0.0
    start_year: int = 1
    term_years: int = 10
    rate_mode: RateMode = RateMode.FIXED
    rate: float = 0.05
    spread: float = 0.015
    interest_mode: InterestMode = InterestMode.PAID
    amortization: Amortization = Amortization.BULLET
    max_ltv: float | None = None
    target_ltv: float | None = None
    currency: str = "USD"

    def __post_init__(self) -> None:
        if self.currency not in ("USD", "COP"):
            raise ValueError(f"{self.name}: moneda desconocida {self.currency!r}.")
        for field_name, enum_cls in (
            ("rate_mode", RateMode),
            ("interest_mode", InterestMode),
            ("amortization", Amortization),
        ):
            value = getattr(self, field_name)
            if isinstance(value, str):
                setattr(self, field_name, enum_cls(value))
        if self.principal < 0:
            raise ValueError(f"{self.name}: el monto del crédito no puede ser negativo.")
        if self.term_years < 1:
            raise ValueError(f"{self.name}: el plazo debe ser de al menos un año.")
        if self.start_year < 1:
            raise ValueError(f"{self.name}: el año de desembolso debe ser 1 o mayor.")
        if self.max_ltv is not None and not 0 < self.max_ltv < 1:
            raise ValueError(f"{self.name}: el LTV máximo debe estar entre 0 y 1.")
        if self.target_ltv is not None:
            if not 0 < self.target_ltv < 1:
                raise ValueError(f"{self.name}: el LTV objetivo debe estar entre 0 y 1.")
            if self.max_ltv is not None and self.target_ltv > self.max_ltv:
                raise ValueError(
                    f"{self.name}: el LTV objetivo no puede superar el LTV máximo."
                )

    @property
    def active(self) -> bool:
        return self.principal > 0

    @property
    def maturity_year(self) -> int:
        """Último año en que el crédito tiene saldo."""
        return self.start_year + self.term_years - 1

    @property
    def effective_target_ltv(self) -> float | None:
        if self.max_ltv is None:
            return None
        return self.target_ltv if self.target_ltv is not None else self.max_ltv

    def reference_rate(self, cash_return: float) -> float:
        """Tasa determinística usada para construir el cronograma de amortización."""
        if self.rate_mode is RateMode.FIXED:
            return self.rate
        return cash_return + self.spread

    def amortization_fractions(self, cash_return: float = 0.0) -> np.ndarray:
        """Fracciones del principal original que se amortizan cada año del plazo."""
        n = self.term_years
        if self.amortization is Amortization.BULLET:
            fractions = np.zeros(n)
            fractions[-1] = 1.0
            return fractions
        if self.amortization is Amortization.LINEAR:
            return np.full(n, 1.0 / n)

        # Cuota fija (francesa): la cuota constante se reparte entre interés y
        # principal, y la porción de principal crece geométricamente a la tasa.
        rate = self.reference_rate(cash_return)
        if abs(rate) < 1e-12:
            return np.full(n, 1.0 / n)
        annuity = rate / (1.0 - (1.0 + rate) ** -n)
        balance = 1.0
        fractions = np.zeros(n)
        for i in range(n):
            interest = balance * rate
            principal = annuity - interest
            principal = min(principal, balance)
            fractions[i] = principal
            balance -= principal
        fractions[-1] += balance  # residuo por redondeo
        return fractions


class LoanSimulator:
    """Aplica las reglas del crédito año a año sobre un conjunto de caminos.

    Solo lleva el estado del año en curso (`balance`) y los acumulados que se
    reportan. El histórico del saldo lo guarda el motor, que es quien lo usa.
    """

    def __init__(self, terms: LoanTerms, n_paths: int, horizon: int, cash_return: float = 0.0,
                 peso=None):
        self.terms = terms
        self.horizon = horizon
        if terms.currency == "COP":
            if peso is None:
                raise ValueError(
                    f"{terms.name}: el crédito está en COP y el caso no tiene tasa USD/COP."
                )
            cash_return = local_cash_rate(cash_return, peso)
        self.peso = peso if terms.currency == "COP" else None
        self.fractions = terms.amortization_fractions(cash_return)
        self.balance = np.zeros(n_paths, dtype=float)
        self.margin_calls = np.zeros(n_paths, dtype=int)
        self.forced_sales = np.zeros(n_paths, dtype=float)

    def fx_open(self, year: int) -> float:
        """Unidades de la moneda del crédito por USD al inicio del año (1 en USD)."""
        return 1.0 if self.peso is None else self.peso.rate(year - 1)

    def fx_close(self, year: int) -> float:
        """Unidades de la moneda del crédito por USD al cierre del año."""
        return 1.0 if self.peso is None else self.peso.rate(year)

    def balance_usd(self, year: int) -> np.ndarray:
        """Saldo por camino en USD, a la tasa de cierre del año."""
        fx = self.fx_close(year)
        return self.balance if fx == 1.0 else self.balance / fx

    def drawdown(self, year: int) -> float:
        """Monto en USD que ingresa al portafolio este año por desembolso."""
        if year == self.terms.start_year:
            self.balance += self.terms.principal
            fx = self.fx_open(year)
            return self.terms.principal if fx == 1.0 else self.terms.principal / fx
        return 0.0

    def accrue_and_amortize(self, year: int, path_rates: np.ndarray) -> np.ndarray:
        """Devengo y amortización del año.

        Devuelve el monto que **sale del portafolio** por camino: intereses si se
        pagan, más la amortización de principal. Si los intereses se capitalizan,
        se suman al saldo en vez de salir del portafolio.
        """
        n = len(self.balance)
        outflow = np.zeros(n, dtype=float)
        if not self.terms.active:
            return outflow

        offset = year - self.terms.start_year
        if offset < 0 or offset >= self.terms.term_years:
            return outflow

        interest = self.balance * path_rates
        if self.terms.interest_mode is InterestMode.CAPITALIZED:
            self.balance += interest
        else:
            outflow += interest

        # En el vencimiento se cancela todo el saldo, incluidos los intereses
        # capitalizados que quedaron acumulados por encima del principal original.
        if offset == self.terms.term_years - 1:
            principal = self.balance.copy()
        else:
            scheduled = self.terms.principal * self.fractions[offset]
            principal = np.minimum(self.balance, scheduled)
        self.balance -= principal
        outflow += principal
        fx = self.fx_open(year)
        return outflow if fx == 1.0 else outflow / fx

    def margin_call(self, assets: np.ndarray, year: int | None = None) -> np.ndarray:
        """Liquidación forzada si se supera el LTV máximo.

        Vender activos para pagar deuda reduce ambos lados por igual, así que el
        monto `d` que devuelve el LTV al objetivo `t` sale de
        `(D - d) / (A - d) = t`, es decir `d = (D - t·A) / (1 - t)`.

        Devuelve el monto liquidado por camino **en USD**, que ya fue restado
        del saldo. `assets` está en USD; para un crédito en COP el saldo se
        compara a la tasa de cierre de `year`.
        """
        fx = 1.0 if year is None else self.fx_close(year)
        if fx != 1.0:
            # Se trabaja en USD y lo vendido se descuenta del saldo en pesos.
            local = self.balance
            self.balance = local / fx
            try:
                sale = self._margin_call_usd(assets)
            finally:
                self.balance = self.balance * fx
            return sale
        return self._margin_call_usd(assets)

    def _margin_call_usd(self, assets: np.ndarray) -> np.ndarray:
        target = self.terms.effective_target_ltv
        if target is None or not self.terms.active:
            return np.zeros(len(self.balance), dtype=float)

        with np.errstate(divide="ignore", invalid="ignore"):
            ltv = np.where(assets > 0, self.balance / assets, np.inf)
        breach = (self.balance > 0) & (ltv > self.terms.max_ltv)
        if not breach.any():
            return np.zeros(len(self.balance), dtype=float)

        sale = np.zeros(len(self.balance), dtype=float)
        needed = (self.balance - target * assets) / (1.0 - target)
        # Nunca se puede vender más de lo que hay, ni más de lo que se debe.
        sale[breach] = np.clip(needed[breach], 0.0, None)
        sale = np.minimum(sale, np.minimum(assets, self.balance))
        self.balance -= sale
        self.forced_sales += sale
        # Se cuenta una llamada solo si hubo venta. Un camino ya agotado tiene
        # LTV infinito y "rompe" el límite todos los años, pero no tiene nada
        # que vender: contarlo inflaba las llamadas promedio con años en que no
        # pasó nada.
        self.margin_calls += (sale > 0).astype(int)
        return sale


def local_cash_rate(usd_cash: np.ndarray | float, peso) -> np.ndarray | float:
    """La caja USD llevada a pesos por paridad: (1 + caja)(1 + devaluación) − 1."""
    return (1.0 + usd_cash) * (1.0 + peso.devaluation) - 1.0
