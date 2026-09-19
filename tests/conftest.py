"""Fixtures compartidas por los tests del motor."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gbp.model.assets import AssetClass, CMASet  # noqa: E402
from gbp.model.correlation import CorrelationMatrix  # noqa: E402


@pytest.fixture
def simple_cmas() -> CMASet:
    """Dos activos y caja, con números redondos para verificar a mano."""
    return CMASet(
        [
            AssetClass("U.S. Cash", compound_return=0.03, volatility=0.007, yield_=0.03),
            AssetClass("Bonos", compound_return=0.04, volatility=0.05, yield_=0.038),
            AssetClass("Acciones", compound_return=0.07, volatility=0.16, yield_=0.02),
        ]
    )


@pytest.fixture
def simple_corr() -> CorrelationMatrix:
    matrix = np.array(
        [
            [1.0, 0.1, 0.0],
            [0.1, 1.0, 0.2],
            [0.0, 0.2, 1.0],
        ]
    )
    return CorrelationMatrix(names=["U.S. Cash", "Bonos", "Acciones"], matrix=matrix)


@pytest.fixture
def deterministic_cmas() -> CMASet:
    """Un único activo sin volatilidad: la simulación se vuelve determinística."""
    return CMASet(
        [
            AssetClass("U.S. Cash", compound_return=0.03, volatility=0.0),
            AssetClass("Fijo", compound_return=0.05, volatility=0.0),
        ]
    )


@pytest.fixture
def deterministic_corr() -> CorrelationMatrix:
    return CorrelationMatrix(
        names=["U.S. Cash", "Fijo"], matrix=np.array([[1.0, 0.0], [0.0, 1.0]])
    )
