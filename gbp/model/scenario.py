"""Escenario del cliente: capital, horizonte, inflación y estrategias.

El escenario guarda lo que es común a toda la comparación —capital inicial,
horizonte e inflación— y una lista de estrategias. Los flujos y el crédito
**no viven aquí**: son de cada estrategia (ver `gbp.model.strategy`), para poder
comparar planes completos y no solo mezclas de activos.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .assets import CMASet
from .goals import Goal
from .strategy import Strategy


@dataclass
class SimulationSettings:
    """Configuración general de la app (no del caso del cliente).

    La unidad de los resultados —nominal o moneda de hoy— **no se configura**:
    las dos se muestran siempre, cada una en su pestaña y cada una en su lámina
    del informe. Eran la misma proyección contada de dos maneras y las dos hacen
    falta, así que elegir una escondía la otra.
    """

    n_paths: int = 10_000
    seed: int | None = 42
    milestone_years: list[int] = field(default_factory=lambda: [5, 10, 15, 20])
    # Preferencias de lectura: ver en COP (con los supuestos del peso del caso)
    # y la escala de las cifras. Ninguna entra a la simulación.
    show_cop: bool = False
    # Escala en que se leen los resultados: "normal", "miles", "millones" o
    # "miles_de_millones". Solo cambia cómo se muestran las cifras.
    display_scale: str = "normal"

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

        La excepción es un horizonte más corto que todos los hitos (un caso a 3
        años con hitos 5, 10, 15, 20): sin ningún hito el gráfico quedaba vacío
        y el informe salía con tablas sin filas. Ahí se muestra el año final.
        """
        years = sorted({y for y in self.milestone_years if 1 <= y <= horizon})
        return years or [horizon]


@dataclass
class PesoAssumptions:
    """Supuestos del peso colombiano, para activos y flujos en COP.

    El portafolio se proyecta en USD. Un activo o un flujo en pesos se lleva a
    dólares con una tasa que se devalúa a ritmo fijo:

        S_t = spot · (1 + devaluación)^t        (COP por USD al cierre del año t)

    Es una trayectoria **determinística**: ajusta retornos y montos por la
    devaluación esperada, pero no agrega riesgo cambiario. Viaja con el caso
    porque cambia cifras de la simulación, igual que la inflación.
    """

    spot: float
    devaluation: float = 0.0
    # Indexa los flujos en COP. Si falta, se usa la paridad: inflación USD
    # compuesta con la devaluación, que deja un flujo en pesos indexado igual
    # de caro en dólares que uno en dólares indexado.
    inflation: float | None = None

    def __post_init__(self) -> None:
        if self.spot <= 0:
            raise ValueError("La tasa USD/COP debe ser positiva.")
        if self.devaluation <= -1:
            raise ValueError("La devaluación anual debe ser mayor a -100%.")

    def rate(self, year: int) -> float:
        """COP por USD al cierre del año `year` (año 0 = hoy)."""
        return self.spot * (1.0 + self.devaluation) ** year

    def cop_inflation(self, usd_inflation: float) -> float:
        if self.inflation is not None:
            return self.inflation
        return (1.0 + usd_inflation) * (1.0 + self.devaluation) - 1.0


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
    # Opcionales: un caso sin metas se comporta exactamente como antes de que
    # existieran. No entran a la simulación.
    goals: list[Goal] = field(default_factory=list)
    # Opcional: solo hace falta si el caso tiene activos o flujos en pesos, o
    # para ver los resultados en COP.
    peso: PesoAssumptions | None = None

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
            if initial <= 0:
                # Sin capital solo cuentan los aportes de monto fijo: un aporte
                # porcentual sobre un patrimonio de cero es cero para siempre.
                # Y tienen que empezar el año 1, porque un año con patrimonio en
                # cero cuenta como agotado y el caso saldría con 0% de éxito sin
                # que nada lo explique.
                aportes = [
                    f for f in strategy.cashflows if f.sign > 0 and not f.is_percentage
                ]
                if not aportes:
                    raise ValueError(
                        f"La estrategia '{strategy.name}' no tiene capital inicial ni "
                        "aportes de monto fijo: no hay nada que proyectar. Un aporte "
                        "porcentual sobre un patrimonio de cero no aporta nada."
                    )
                if min(f.start_year for f in aportes) > 1:
                    raise ValueError(
                        f"La estrategia '{strategy.name}' no tiene capital inicial y su "
                        f"primer aporte llega en el año {min(f.start_year for f in aportes)}. "
                        "Los años previos quedarían con patrimonio cero, que cuenta como "
                        "agotado. Dale un capital inicial o haz que un aporte empiece "
                        "el año 1."
                    )

            if strategy.has_loan and strategy.loan.start_year > self.horizon:
                raise ValueError(
                    f"El crédito de '{strategy.name}' se desembolsa en el año "
                    f"{strategy.loan.start_year}, después del final del horizonte "
                    f"({self.horizon} años)."
                )

        if self.peso is None:
            en_pesos = self.cop_items(cmas)
            if en_pesos:
                raise ValueError(
                    "El caso tiene cifras en pesos —" + ", ".join(en_pesos) + "— pero no "
                    "tiene tasa USD/COP. Escríbela en la sección «Pesos colombianos» de "
                    "Escenario."
                )

    def cop_items(self, cmas: CMASet) -> list[str]:
        """Activos y flujos del caso que están en pesos, por nombre."""
        items: list[str] = []
        for name in self.asset_names:
            try:
                if cmas.by_name(name).currency == "COP":
                    items.append(name)
            except KeyError:
                continue
        for strategy in self.strategies:
            items += [f.name for f in strategy.cashflows if f.currency == "COP"]
        return items

    @property
    def asset_names(self) -> list[str]:
        """Unión de las clases usadas por todas las estrategias, en orden estable."""
        names: list[str] = []
        for strategy in self.strategies:
            for name in strategy.asset_names:
                if name not in names:
                    names.append(name)
        return names
