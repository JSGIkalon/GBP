"""Escenario del cliente: capital, horizonte, inflación y estrategias.

El escenario guarda lo que es común a toda la comparación —capital inicial,
horizonte e inflación— y una lista de estrategias. Los flujos y el crédito
**no viven aquí**: son de cada estrategia (ver `gbp.model.strategy`), para poder
comparar planes completos y no solo mezclas de activos.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .assets import CMASet
from .strategy import Strategy


@dataclass
class SimulationSettings:
    """Configuración general de la app (no del caso del cliente)."""

    n_paths: int = 10_000
    seed: int | None = 42
    show_real_values: bool = False
    milestone_years: list[int] = field(default_factory=lambda: [5, 10, 15, 20])

    def __post_init__(self) -> None:
        if self.n_paths < 100:
            raise ValueError("Se necesitan al menos 100 simulaciones.")
        if self.n_paths > 1_000_000:
            raise ValueError("El máximo razonable es 1.000.000 de simulaciones.")

    def milestones_within(self, horizon: int) -> list[int]:
        """Años hito que caben en el horizonte, sin repetidos y ordenados.

        Se respeta exactamente lo configurado: no se añade el horizonte por
        cuenta propia. Menos ventanas de tiempo dejan el gráfico legible, y si
        se quiere el año final basta con agregarlo en Configuración.
        """
        return sorted({y for y in self.milestone_years if 1 <= y <= horizon})


@dataclass
class Scenario:
    """Todo lo que define el caso de un cliente.

    Las estrategias se simulan en paralelo con los mismos sorteos de mercado,
    para que las diferencias entre ellas vengan de la estrategia y no del azar.
    """

    name: str = "Caso sin título"
    initial_value: float = 0.0
    horizon: int = 30
    inflation: float = 0.025
    strategies: list[Strategy] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.horizon < 1:
            raise ValueError("El horizonte debe ser de al menos un año.")
        if self.initial_value < 0:
            raise ValueError("El capital inicial no puede ser negativo.")

    def validate(self, cmas: CMASet) -> None:
        """Verifica que el caso se pueda simular con la librería de CMAs dada."""
        if not self.strategies:
            raise ValueError("Define al menos una estrategia para simular.")

        names = [s.name for s in self.strategies]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"Hay estrategias con el mismo nombre: {sorted(duplicates)}")

        for strategy in self.strategies:
            strategy.allocation.validate()

            unknown = strategy.allocation.unknown_assets(cmas)
            if unknown:
                raise ValueError(
                    f"La estrategia '{strategy.name}' usa clases de activo que no están "
                    f"en la librería de CMAs: {', '.join(unknown)}"
                )

            initial = strategy.resolved_initial(self.initial_value)
            if initial <= 0 and not any(f.sign > 0 for f in strategy.cashflows):
                raise ValueError(
                    f"La estrategia '{strategy.name}' no tiene capital inicial ni aportes: "
                    "no hay nada que proyectar."
                )

            if strategy.has_loan and strategy.loan.start_year > self.horizon:
                raise ValueError(
                    f"El crédito de '{strategy.name}' se desembolsa en el año "
                    f"{strategy.loan.start_year}, después del final del horizonte "
                    f"({self.horizon} años)."
                )

    @property
    def asset_names(self) -> list[str]:
        """Unión de las clases usadas por todas las estrategias, en orden estable."""
        names: list[str] = []
        for strategy in self.strategies:
            for name in strategy.asset_names:
                if name not in names:
                    names.append(name)
        return names
