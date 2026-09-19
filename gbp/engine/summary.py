"""Supuestos resumen de una estrategia (la tabla de la lámina 7 del ejemplo de JPM).

Son estadísticas ponderadas por los pesos de la estrategia: retorno de largo
plazo (aritmético), volatilidad, retorno compuesto, yield y Sharpe. No son una
predicción, solo explican los supuestos con que se construyen las proyecciones.
"""

from __future__ import annotations

import numpy as np

from ..model.allocation import Allocation
from ..model.assets import CMASet
from ..model.correlation import covariance
from ..model.results import SummaryAssumptions

# Nombre de la clase de activo que se usa como tasa libre de riesgo en el Sharpe.
CASH_ASSET = "U.S. Cash"


def risk_free_rate(cmas: CMASet, cash_asset: str = CASH_ASSET) -> float:
    """Tasa libre de riesgo: el retorno compuesto de la clase de caja.

    Si la librería de CMAs no tiene esa clase, se devuelve cero y el Sharpe
    queda calculado sobre el retorno total.
    """
    try:
        return cmas.by_name(cash_asset).compound_return
    except KeyError:
        return 0.0


def summarize(
    allocation: Allocation,
    cmas: CMASet,
    corr: np.ndarray,
    cash_asset: str = CASH_ASSET,
) -> SummaryAssumptions:
    """Estadísticas resumen de una estrategia.

    `corr` debe ser la submatriz de correlación alineada a
    `allocation.asset_names`.
    """
    names = allocation.asset_names
    if not names:
        raise ValueError(f"La estrategia '{allocation.name}' no tiene pesos asignados.")

    assets = [cmas.by_name(n) for n in names]
    weights = allocation.weight_vector(names)
    weights = weights / weights.sum()

    arithmetic = np.array([a.arithmetic_return for a in assets])
    sigmas = np.array([a.volatility for a in assets])
    yields = np.array([a.yield_ for a in assets])

    portfolio_return = float(weights @ arithmetic)
    variance = float(weights @ covariance(sigmas, corr) @ weights)
    volatility = float(np.sqrt(max(variance, 0.0)))
    portfolio_yield = float(weights @ yields)

    # Retorno compuesto del portafolio: se descuenta el arrastre de la volatilidad
    # sobre el retorno aritmético, que es la relación lognormal estándar.
    gross = 1.0 + portfolio_return
    sigma_log_sq = np.log1p((volatility / gross) ** 2) if gross > 0 else 0.0
    compound = float(np.exp(np.log(gross) - 0.5 * sigma_log_sq) - 1.0) if gross > 0 else -1.0

    rf = risk_free_rate(cmas, cash_asset)
    sharpe = (portfolio_return - rf) / volatility if volatility > 0 else float("nan")

    return SummaryAssumptions(
        arithmetic_return=portfolio_return,
        volatility=volatility,
        compound_return=compound,
        yield_=portfolio_yield,
        sharpe_ratio=float(sharpe),
    )
