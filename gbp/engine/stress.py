"""Stress tests por shocks instantáneos definidos a mano.

Un escenario de estrés es un conjunto de caídas (o alzas) porcentuales por clase
de activo. El impacto sobre una estrategia es la suma ponderada de los shocks,
igual que la lámina de crisis históricas del ejemplo de J.P. Morgan.

Los shocks precargados son órdenes de magnitud razonables para cada crisis, no
retornos de índices reales: el cálculo desde series históricas queda para cuando
se incorporen los datos de mercado. Son totalmente editables.

Las clases de activo no mencionadas en un escenario reciben el shock del grupo
al que pertenecen (`default_by_group`), y si tampoco hay grupo, cero.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..model.allocation import Allocation

# Agrupación gruesa de las clases del LTCMA, para aplicar shocks por defecto.
# El orden importa: gana la primera coincidencia, así que los grupos más
# específicos van primero. "Private Equity" contiene la palabra "Equity", de
# modo que debe resolverse como activo privado antes de llegar al grupo de
# renta variable.
GROUP_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("privados", ("Private Equity", "Venture Capital")),
    ("hedge", ("Hedge Funds",)),
    ("caja", ("Cash",)),
    ("gobierno", ("Treasuries", "Government Bonds", "TIPS")),
    ("credito", ("High Yield", "Leveraged Loans", "Emerging Markets Sovereign",
                 "Emerging Markets Local", "Emerging Markets Corporate",
                 "Direct Lending", "Convertible")),
    ("real", ("Real Estate", "Infrastructure", "Transport", "Timberland",
              "Commodities", "Gold", "Mortgage Loans", "REITs")),
    ("bonos", ("Aggregate", "Securitized", "Muni", "Corporate Bonds", "Government/Credit")),
    ("equity", ("Equity", "Large Cap", "Mid Cap", "Small Cap")),
]


def group_of(asset_name: str) -> str:
    """Grupo al que pertenece una clase de activo, por palabras clave."""
    for group, keywords in GROUP_KEYWORDS:
        if any(k.lower() in asset_name.lower() for k in keywords):
            return group
    return "otros"


@dataclass
class StressScenario:
    """Un escenario de estrés: shocks en forma decimal (-0.30 = caída de 30%).

    El `resolver` es opcional y solo hace falta cuando hay activos propios. Va
    como **campo y no como parámetro** de `impact()` a propósito: así ni
    `impact`, ni `breakdown`, ni `run_stress_tests`, ni el gráfico de estrés
    cambian de firma. Quien construye los escenarios los resuelve una vez con
    `with_resolver()` y el resto del código no se entera.
    """

    name: str
    description: str = ""
    shocks: dict[str, float] = field(default_factory=dict)
    default_by_group: dict[str, float] = field(default_factory=dict)
    resolver: object | None = None

    def with_resolver(self, resolver) -> "StressScenario":
        """Copia con el resolvedor puesto; los precargados nacen sin él."""
        return StressScenario(
            name=self.name,
            description=self.description,
            shocks=dict(self.shocks),
            default_by_group=dict(self.default_by_group),
            resolver=resolver,
        )

    def shock_for(self, asset_name: str) -> float:
        """Shock de una clase de activo.

        Orden: un shock puesto a mano por nombre gana siempre; si el activo es
        propio, se promedia el shock de las clases del LTCMA de su clase —el
        mismo principio que rige sus correlaciones—; si no, se deduce del
        nombre por palabras clave.

        Nótese que el promedio atraviesa los dos cortes de clases de activo que
        conviven en el proyecto: la clase declarada usa los cuatro grupos de
        `model/groups.py` y el shock usa los ocho de aquí. Es deliberado. La
        alternativa —una tabla que traduzca de cuatro a ocho— sería una tercera
        taxonomía y una convención inventada.
        """
        if asset_name in self.shocks:
            return self.shocks[asset_name]

        if self.resolver is not None:
            miembros = self.resolver.members_of(asset_name)
            if miembros:
                return sum(self.shock_for(m) for m in miembros) / len(miembros)

        return self.default_by_group.get(group_of(asset_name), 0.0)

    def impact(self, allocation: Allocation) -> float:
        """Caída porcentual de la estrategia ante el escenario."""
        names = allocation.asset_names
        if not names:
            return 0.0
        weights = allocation.weight_vector(names)
        total = weights.sum()
        if total <= 0:
            return 0.0
        weights = weights / total
        return float(sum(w * self.shock_for(n) for w, n in zip(weights, names)))

    def breakdown(self, allocation: Allocation) -> list[tuple[str, float, float, float]]:
        """Aporte de cada clase: (nombre, peso, shock, contribución)."""
        names = allocation.asset_names
        weights = allocation.weight_vector(names)
        total = weights.sum() or 1.0
        rows = []
        for name, weight in zip(names, weights / total):
            shock = self.shock_for(name)
            rows.append((name, float(weight), shock, float(weight * shock)))
        return rows


def default_scenarios() -> list[StressScenario]:
    """Escenarios precargados, editables desde la app."""
    return [
        StressScenario(
            name="Covid-19 (feb–mar 2020)",
            description=(
                "Caída abrupta y global tras la declaración de emergencia sanitaria. "
                "Liquidez y gobierno actúan como refugio; el crédito sufre por falta de liquidez."
            ),
            default_by_group={
                "caja": 0.0,
                "gobierno": 0.06,
                "bonos": 0.01,
                "credito": -0.13,
                "equity": -0.32,
                "real": -0.18,
                "privados": -0.24,
                "hedge": -0.10,
                "otros": -0.15,
            },
        ),
        StressScenario(
            name="Crisis financiera global (jul 2007–mar 2009)",
            description=(
                "Corrección prolongada originada en el crédito hipotecario. "
                "Los activos reales y privados caen con rezago pero con fuerza."
            ),
            default_by_group={
                "caja": 0.0,
                "gobierno": 0.12,
                "bonos": 0.03,
                "credito": -0.28,
                "equity": -0.51,
                "real": -0.38,
                "privados": -0.45,
                "hedge": -0.19,
                "otros": -0.30,
            },
        ),
        StressScenario(
            name="Burbuja puntocom (mar 2000–oct 2002)",
            description=(
                "Corrección concentrada en renta variable, sobre todo tecnología y "
                "capital de riesgo. La renta fija se comporta bien."
            ),
            default_by_group={
                "caja": 0.0,
                "gobierno": 0.20,
                "bonos": 0.15,
                "credito": -0.05,
                "equity": -0.45,
                "real": 0.02,
                "privados": -0.40,
                "hedge": -0.06,
                "otros": -0.20,
            },
        ),
        StressScenario(
            name="Shock de tasas (2022)",
            description=(
                "Alza sincronizada de tasas: renta fija y renta variable caen a la vez "
                "y la diversificación tradicional no protege."
            ),
            default_by_group={
                "caja": 0.01,
                "gobierno": -0.15,
                "bonos": -0.14,
                "credito": -0.12,
                "equity": -0.20,
                "real": -0.06,
                "privados": -0.12,
                "hedge": -0.05,
                "otros": -0.10,
            },
        ),
    ]


def run_stress_tests(
    allocations: list[Allocation],
    scenarios: list[StressScenario],
    initial_value: float = 1.0,
) -> dict[str, dict[str, float]]:
    """Impacto de cada escenario sobre cada estrategia.

    Devuelve `{escenario: {estrategia: caída porcentual}}`. Multiplicar por
    `initial_value` da la pérdida en moneda.
    """
    return {
        scenario.name: {
            allocation.name: scenario.impact(allocation) * initial_value
            for allocation in allocations
        }
        for scenario in scenarios
    }
