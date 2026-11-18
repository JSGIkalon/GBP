"""Monedas del caso: la moneda base y la conversión a ella.

La moneda base es **USD** y no se configura: es la moneda en que J.P. Morgan
publica el LTCMA —retornos, volatilidades y correlaciones— y por tanto la única
en que los supuestos de mercado tienen sentido sin transformarlos. Todo lo que
entra al motor se lleva a USD antes de simular, optimizar o comparar:

* el capital inicial del caso (y el propio de una estrategia), si se escribió
  en COP, con la tasa inicial;
* los activos propios en COP, con la devaluación esperada
  (`AssetClass.in_usd`);
* los flujos en COP, con la tasa de cada año (`CashFlow.schedule`).

La única tasa que existe es la USD/COP del caso (`PesoAssumptions`): un camino
determinístico `S_t = spot · (1 + d)^t`. **No modela riesgo cambiario**: el
peso no tiene volatilidad ni correlación con los mercados.

Este módulo concentra la conversión y sus validaciones para que un caso con una
tasa faltante o inválida falle con un mensaje claro en vez de producir cifras
engañosas, y para que dos monedas iguales no pasen por ninguna multiplicación.
"""

from __future__ import annotations

import math

BASE_CURRENCY = "USD"
SUPPORTED_CURRENCIES = ("USD", "COP")


class CurrencyError(ValueError):
    """Moneda desconocida, o tasa de cambio faltante o inválida."""


def check_currency(currency: str) -> str:
    if currency not in SUPPORTED_CURRENCIES:
        raise CurrencyError(
            f"Moneda desconocida {currency!r}: las monedas disponibles son "
            + ", ".join(SUPPORTED_CURRENCIES) + "."
        )
    return currency


def check_rate(rate) -> float:
    """Una tasa de cambio usable: un número finito y positivo."""
    try:
        value = float(rate)
    except (TypeError, ValueError):
        raise CurrencyError(f"La tasa de cambio {rate!r} no es un número.") from None
    if not math.isfinite(value) or value <= 0:
        raise CurrencyError(
            f"La tasa de cambio debe ser un número positivo; llegó {rate!r}."
        )
    return value


def factor_to_base(currency: str, peso) -> float:
    """Por cuánto se multiplica un monto de hoy en `currency` para llevarlo a USD.

    Monedas iguales devuelven exactamente 1.0, sin pasar por la tasa. Un monto
    en COP sin tasa USD/COP —o con una tasa inválida— es un error, nunca un
    cero o un uno silencioso.
    """
    check_currency(currency)
    if currency == BASE_CURRENCY:
        return 1.0
    if peso is None:
        raise CurrencyError(
            "Hay montos en COP pero el caso no tiene tasa USD/COP. Escríbela en la "
            "sección «Pesos colombianos» de Escenario."
        )
    return 1.0 / check_rate(peso.spot)


def to_base(amount: float, currency: str, peso) -> float:
    """El monto de hoy llevado a la moneda base (USD)."""
    factor = factor_to_base(currency, peso)
    return float(amount) if factor == 1.0 else float(amount) * factor


def from_base(amount: float, currency: str, peso) -> float:
    """Inverso de `to_base`: un monto de hoy en USD expresado en `currency`."""
    factor = factor_to_base(currency, peso)
    return float(amount) if factor == 1.0 else float(amount) / factor


def describe_rate(peso) -> str:
    """Tasa inicial y devaluación, sin depender del formato de la interfaz."""
    if peso is None:
        return "Sin tasa USD/COP: todo el caso está en USD."
    spot = f"{peso.spot:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return (
        f"USD/COP {spot} hoy, devaluación esperada {peso.devaluation:.2%} anual "
        "(camino fijo, sin riesgo cambiario)"
    )
