"""Agregación de las clases del LTCMA en las cuatro clases de activo clásicas.

El LTCMA publica 59 **sub-clases**. Para leer un portafolio en comité no sirven
59 filas: sirve saber cuánto hay en renta variable, renta fija, alternativos y
caja. Este módulo hace ese único trabajo, y solo de lectura: los pesos se siguen
cargando por sub-clase, que es el nivel al que existen retorno, volatilidad y
correlación. Agregar es una vista, nunca un input.

Es deliberadamente distinto de `gbp/engine/stress.py`, que agrupa en ocho
bloques para aplicar shocks. Aquel corte responde "qué se mueve junto en una
crisis"; este responde "cómo se lee la asignación". Mezclarlos obligaría a que
un solo corte sirviera para dos preguntas distintas, y no sirve para ninguna.

Dos decisiones de frontera que conviene conocer, porque son convención y no
verdad:

* **Direct Lending y Commercial Mortgage Loans van a Alternativos**, no a renta
  fija. Son crédito privado e ilíquido: se parecen más a un fondo cerrado que a
  un bono que se vende el martes.
* **Los REITs van a Alternativos**, junto al real estate privado. Cotizan como
  acciones, así que hay argumento para contarlos en renta variable; se agrupan
  con el ladrillo porque la pregunta que responde esta vista es a qué está
  expuesto el patrimonio, no en qué mercado se negocia.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

EQUITY = "Renta variable"
FIXED_INCOME = "Renta fija"
ALTERNATIVES = "Alternativos"
CASH = "Caja"
OTHER = "Otros"

# Orden de presentación: de más a menos riesgo, con caja al final. `OTHER` no
# entra: solo aparece si una clase no se pudo clasificar, y entonces se añade
# al final para que se vea que hay algo sin mapear.
GROUP_ORDER = [EQUITY, FIXED_INCOME, ALTERNATIVES, CASH]

# Gana la primera coincidencia, así que el orden **importa**: los alternativos
# van antes que renta variable porque "Private Equity" contiene "Equity", y
# antes que renta fija porque "Commercial Mortgage Loans" contiene "Loans".
GROUP_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    (CASH, ("Cash",)),
    (
        ALTERNATIVES,
        (
            "Private Equity", "Venture Capital", "Hedge Funds", "Direct Lending",
            "Real Estate", "REITs", "Mortgage Loans", "Infrastructure",
            "Transport", "Timberland", "Commodities", "Gold",
        ),
    ),
    (
        EQUITY,
        ("Equity", "Large Cap", "Mid Cap", "Small Cap", "Factor"),
    ),
    (
        FIXED_INCOME,
        (
            "Treasuries", "TIPS", "Bonds", "Securitized", "Government/Credit",
            "Leveraged Loans", "Muni", "Debt", "Convertible",
        ),
    ),
]


def group_of(asset_name: str) -> str:
    """Clase de activo a la que pertenece una sub-clase del LTCMA.

    Deduce por palabras clave del nombre, que están en inglés porque así vienen
    del LTCMA. Un activo propio llamado "Renta Fija Colombiana" caería aquí en
    `OTHER`: para esos hay que pasar por un `ClassResolver`, que conoce la clase
    que el analista declaró.
    """
    lowered = asset_name.lower()
    for group, keywords in GROUP_KEYWORDS:
        if any(keyword.lower() in lowered for keyword in keywords):
            return group
    return OTHER


def ltcma_members(names: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """Clases del LTCMA que pertenecen a cada clase de activo.

    Recibe una secuencia de nombres en vez de una `CorrelationMatrix` para que
    este módulo no dependa de ningún otro del modelo: así se puede importar
    desde cualquier sitio sin arrastrar ciclos.
    """
    members: dict[str, list[str]] = {g: [] for g in GROUP_ORDER}
    for name in names:
        group = group_of(name)
        if group in members:
            members[group].append(name)
    return {g: tuple(ns) for g, ns in members.items() if ns}


@dataclass(frozen=True)
class ClassResolver:
    """Sabe la clase de cualquier activo, incluidos los propios.

    Existe para que `group_of` y los shocks de estrés puedan conocer la clase
    **declarada** de un activo propio sin recurrir a estado global mutable:
    el resolvedor se construye una vez desde la librería y se pasa a quien lo
    necesite.

    Un `ClassResolver()` vacío se comporta exactamente igual que `group_of`, que
    es lo que mantiene intacto todo el código que no sabe de activos propios.
    """

    declared: Mapping[str, str] = field(default_factory=dict)
    members: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def from_library(cls, cmas, ltcma_names: Sequence[str]) -> "ClassResolver":
        """Resolvedor para una librería de CMAs y el universo del LTCMA."""
        return cls(
            declared={a.name: a.asset_class for a in cmas if a.is_custom},
            members=ltcma_members(ltcma_names),
        )

    def is_custom(self, asset_name: str) -> bool:
        return asset_name in self.declared

    def group_of(self, asset_name: str) -> str:
        """La clase declarada si es un activo propio; si no, la deducida."""
        declared = self.declared.get(asset_name)
        return declared if declared is not None else group_of(asset_name)

    def members_of(self, asset_name: str) -> tuple[str, ...]:
        """Clases del LTCMA de las que un activo propio deriva sus supuestos.

        Vacío para una clase del LTCMA: esa no deriva nada, los tiene publicados.
        """
        declared = self.declared.get(asset_name)
        if declared is None:
            return ()
        return tuple(self.members.get(declared, ()))


def group_weights(
    weights: dict[str, float], resolver: ClassResolver | None = None
) -> dict[str, float]:
    """Pesos agregados por clase de activo, normalizados y en orden de lectura.

    Se normaliza sobre el total cargado: si los pesos aún no suman 100% la vista
    agrupada sigue siendo legible, y el aviso de que no suman ya lo da el
    semáforo de la tabla de pesos. Un grupo con peso cero no aparece.
    """
    total = sum(weights.values())
    if total <= 0:
        return {}

    clasificar = resolver.group_of if resolver is not None else group_of

    buckets: dict[str, float] = {}
    for name, weight in weights.items():
        if weight:
            grupo = clasificar(name)
            buckets[grupo] = buckets.get(grupo, 0.0) + weight / total

    ordered = {g: buckets[g] for g in GROUP_ORDER if g in buckets}
    if OTHER in buckets:  # al final, para que se note lo que no se pudo mapear
        ordered[OTHER] = buckets[OTHER]
    return ordered


def group_summary(
    weights: dict[str, float], resolver: ClassResolver | None = None
) -> str:
    """Una línea con la composición agrupada, para textos e informes."""
    grouped = group_weights(weights, resolver)
    if not grouped:
        return "sin pesos definidos"
    return " · ".join(f"{g} {w:.1%}" for g, w in grouped.items())
