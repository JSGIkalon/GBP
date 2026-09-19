"""Asignaciones estratégicas de activos (estrategias comparables)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .assets import CMASet

WEIGHT_TOLERANCE = 1e-6


@dataclass
class Allocation:
    """Una estrategia: pesos por clase de activo que suman 1.

    Ejemplo: "Portafolio actual", "Balanceado con 30% PI", "Growth con 20% PI".
    Las clases con peso cero pueden omitirse.
    """

    name: str
    weights: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("La estrategia necesita un nombre.")
        self.name = self.name.strip()
        negatives = {k: v for k, v in self.weights.items() if v < 0}
        if negatives:
            raise ValueError(f"{self.name}: pesos negativos en {sorted(negatives)}.")

    @property
    def total(self) -> float:
        return sum(self.weights.values())

    @property
    def asset_names(self) -> list[str]:
        """Clases con peso distinto de cero, en el orden en que fueron definidas."""
        return [name for name, w in self.weights.items() if w != 0.0]

    def validate(self) -> None:
        if abs(self.total - 1.0) > WEIGHT_TOLERANCE:
            raise ValueError(
                f"{self.name}: los pesos suman {self.total:.4%}, deberían sumar 100%."
            )

    def normalized(self) -> "Allocation":
        """Copia con los pesos reescalados para que sumen exactamente 1."""
        total = self.total
        if total <= 0:
            raise ValueError(f"{self.name}: los pesos suman cero, no se puede normalizar.")
        return Allocation(self.name, {k: v / total for k, v in self.weights.items()})

    def weight_vector(self, names: list[str]) -> np.ndarray:
        """Vector de pesos alineado al orden de `names` (cero si no aparece)."""
        return np.array([self.weights.get(n, 0.0) for n in names], dtype=float)

    def unknown_assets(self, cmas: CMASet) -> list[str]:
        """Clases usadas en la estrategia que no existen en la librería de CMAs."""
        known = set(cmas.names)
        return [n for n in self.asset_names if n not in known]
