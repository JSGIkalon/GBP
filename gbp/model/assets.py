"""Clases de activo y su conjunto de supuestos de mercado (CMAs).

Las CMAs se ingresan a mano y se guardan en la librería global de la app
(ver `gbp.io.library`), no dentro del caso del cliente.

Convención de retornos
----------------------
J.P. Morgan publica en sus LTCMA el **retorno compuesto** (geométrico) y la
volatilidad. El motor Monte Carlo trabaja en espacio logarítmico, así que la
conversión es directa:

    mu_log = ln(1 + retorno_compuesto)

y el retorno aritmético esperado se deriva de ahí:

    retorno_aritmetico = exp(mu_log + sigma_log^2 / 2) - 1

donde `sigma_log` se aproxima a partir de la volatilidad aritmética reportada.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Procedencia de una clase de activo. La distinción no es cosmética: las del
# LTCMA son idénticas en todas las máquinas porque viajan como recurso embebido,
# mientras que las propias las declara el analista y por eso tienen que viajar
# dentro del caso (ver `gbp.io.caseio`).
ORIGIN_LTCMA = "ltcma"
ORIGIN_CUSTOM = "custom"


@dataclass
class AssetClass:
    """Supuestos de largo plazo para una clase de activo.

    Todos los porcentajes se expresan en forma decimal (0.069 = 6.9%).

    Una clase **propia** —patrimonio que el LTCMA no cubre, como renta fija
    colombiana— declara además a qué clase de activo pertenece. Esa declaración
    es la que permite derivarle correlaciones, porque no las tiene publicadas:
    ver `gbp.model.custom_assets`.
    """

    name: str
    compound_return: float
    volatility: float
    yield_: float = 0.0
    origin: str = ORIGIN_LTCMA
    asset_class: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("La clase de activo necesita un nombre.")
        self.name = self.name.strip()
        if self.volatility < 0:
            raise ValueError(f"{self.name}: la volatilidad no puede ser negativa.")
        if self.compound_return <= -1:
            raise ValueError(f"{self.name}: el retorno compuesto debe ser mayor a -100%.")

        if self.origin not in (ORIGIN_LTCMA, ORIGIN_CUSTOM):
            raise ValueError(
                f"{self.name}: origen desconocido '{self.origin}'; "
                f"debe ser '{ORIGIN_LTCMA}' o '{ORIGIN_CUSTOM}'."
            )

        if self.origin == ORIGIN_CUSTOM:
            # Se importa aquí y no arriba para que `groups` no tenga que
            # importarse siempre: `assets` es la base de casi todo el modelo.
            from .groups import GROUP_ORDER, OTHER

            if self.asset_class == OTHER:
                raise ValueError(
                    f"{self.name}: '{OTHER}' no sirve como clase declarada. Es el "
                    "cajón de lo que no se pudo clasificar, así que no tiene "
                    "miembros del LTCMA de los que derivar correlaciones."
                )
            if self.asset_class not in GROUP_ORDER:
                raise ValueError(
                    f"{self.name}: un activo propio debe declarar su clase de activo, "
                    f"una de {GROUP_ORDER}; llegó {self.asset_class!r}."
                )
        else:
            # La clase de una clase del LTCMA se deduce de su nombre; guardarla
            # abriría la puerta a que las dos fuentes se contradigan.
            self.asset_class = None

    @property
    def is_custom(self) -> bool:
        return self.origin == ORIGIN_CUSTOM

    @property
    def sigma_log(self) -> float:
        """Volatilidad en espacio logarítmico.

        Para una lognormal, la volatilidad aritmética reportada se relaciona con
        la media aritmética `m = E[1 + R]`, no con el retorno compuesto:

            sigma^2 = m^2 * (exp(sigma_log^2) - 1)     con  m = (1 + comp) * exp(sigma_log^2 / 2)

        Como `m` depende a su vez de `sigma_log`, se resuelve por punto fijo.
        Converge en pocas iteraciones y deja la conversión reversible: aplicar
        `arithmetic_return` y volver al compuesto devuelve el valor original,
        que es lo que permite comparar los supuestos resumen con los publicados.
        """
        if self.volatility == 0:
            return 0.0
        gross = 1.0 + self.compound_return
        sigma_sq = math.log1p((self.volatility / gross) ** 2)
        for _ in range(64):
            mean = gross * math.exp(sigma_sq / 2.0)
            updated = math.log1p((self.volatility / mean) ** 2)
            if abs(updated - sigma_sq) < 1e-15:
                sigma_sq = updated
                break
            sigma_sq = updated
        return math.sqrt(sigma_sq)

    @property
    def mu_log(self) -> float:
        """Media en espacio logarítmico: el retorno compuesto esperado."""
        return math.log1p(self.compound_return)

    @property
    def arithmetic_return(self) -> float:
        """Retorno aritmético esperado implícito en los supuestos lognormales."""
        return math.exp(self.mu_log + 0.5 * self.sigma_log**2) - 1.0

    @property
    def appreciation(self) -> float:
        """Apreciación de capital = retorno compuesto menos el yield."""
        return self.compound_return - self.yield_


@dataclass
class CMASet:
    """Colección ordenada de clases de activo.

    El orden importa: define el orden de filas y columnas de la matriz de
    correlación y de los vectores de pesos.
    """

    assets: list[AssetClass] = field(default_factory=list)

    def __post_init__(self) -> None:
        names = [a.name for a in self.assets]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"Clases de activo duplicadas: {sorted(duplicates)}")

    def __len__(self) -> int:
        return len(self.assets)

    def __iter__(self):
        return iter(self.assets)

    def __getitem__(self, key: int | str) -> AssetClass:
        if isinstance(key, int):
            return self.assets[key]
        return self.by_name(key)

    @property
    def names(self) -> list[str]:
        return [a.name for a in self.assets]

    def by_name(self, name: str) -> AssetClass:
        for asset in self.assets:
            if asset.name == name:
                return asset
        raise KeyError(f"No existe la clase de activo '{name}'.")

    def index_of(self, name: str) -> int:
        try:
            return self.names.index(name)
        except ValueError:
            raise KeyError(f"No existe la clase de activo '{name}'.") from None

    def add(self, asset: AssetClass) -> None:
        if asset.name in self.names:
            raise ValueError(f"La clase de activo '{asset.name}' ya existe.")
        self.assets.append(asset)

    def remove(self, name: str) -> None:
        self.assets.pop(self.index_of(name))

    def subset(self, names: list[str]) -> "CMASet":
        """Devuelve un CMASet con las clases indicadas, en ese orden."""
        return CMASet([self.by_name(n) for n in names])

    @property
    def custom(self) -> list[AssetClass]:
        """Las clases declaradas por el analista, en orden."""
        return [a for a in self.assets if a.is_custom]

    @property
    def ltcma(self) -> list[AssetClass]:
        """Las clases que vienen del LTCMA."""
        return [a for a in self.assets if not a.is_custom]
