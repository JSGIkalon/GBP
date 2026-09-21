"""Activos propios: patrimonio que el LTCMA no cubre.

El LTCMA publica 59 clases de activo en USD. Un cliente colombiano tiene TES,
CDT y finca raíz en Bogotá, y nada de eso está ahí. Retorno y volatilidad se
pueden escribir a mano; el problema son las **correlaciones**, porque el motor
sortea retornos correlacionados con un factor de Cholesky sobre la matriz
completa y por tanto todo activo necesita su fila y su columna.

El principio
------------
    Un activo propio se comporta como **el promedio de su clase de activo**,
    más su propio riesgo idiosincrático, con el retorno y la volatilidad que
    el analista fija.

De ese único enunciado salen las dos cosas que el activo necesita y que nadie
escribe: sus correlaciones (aquí) y su grupo en la vista agrupada
(`gbp.model.groups`).

Por qué la matriz extendida es válida
-------------------------------------
Sea `p` el portafolio equiponderado de las clases del LTCMA de esa clase, en
retornos estandarizados. El activo propio se construye como

    z = λ·p + sqrt(1 - λ²·var(p))·ε      con ε independiente de todo lo demás

que tiene varianza 1 y `corr(z, X) = λ·cov(p, X) = λ · promedio de corr(g, X)`.
Como la matriz extendida es la correlación de un vector aleatorio **construido
explícitamente**, es semidefinida positiva por construcción. No hace falta
repararla, y de hecho no se debe: pasarla por `nearest_psd` destruiría las
correlaciones derivadas exactas para arreglar un problema que no existe.

El caso degenerado, que es real y no hipotético
-----------------------------------------------
`var(p) ≤ 1` siempre, con igualdad solo si todas las correlaciones dentro de la
clase valen 1 — y eso ocurre cuando **la clase tiene un solo miembro**. La clase
"Caja" del LTCMA tiene exactamente uno (`U.S. Cash`), así que con λ = 1 una
"caja colombiana" saldría con correlación 1.00 contra `U.S. Cash`: un clon sin
riesgo propio, y la matriz exactamente singular.

De ahí `CORRELATION_CAP`: se limita cuánto de la varianza del activo puede
explicar su clase, mediante `λ = min(1, sqrt(cap / var(p)))`. Para las clases
pobladas λ = 1 y no cambia nada; solo actúa donde haría falta. Es honesto
además de conveniente: un CDT en pesos **no es** un T-bill.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .assets import CMASet
from .correlation import CorrelationMatrix
from .groups import ClassResolver, ltcma_members

# Cuánta de la varianza de un activo propio puede explicar su clase. El resto es
# riesgo idiosincrático —país, emisor, moneda— que por definición la clase no
# captura. 0.95 deja la matriz definida positiva incluso para una clase de un
# solo miembro, sin tocar las clases pobladas.
CORRELATION_CAP = 0.95


def custom_pairs(cmas: CMASet) -> list[tuple[str, str]]:
    """Los activos propios de la librería como `(nombre, clase declarada)`."""
    return [(a.name, a.asset_class) for a in cmas.custom]


def resolver_for(cmas: CMASet, base: CorrelationMatrix) -> ClassResolver:
    """Resolvedor de clases para una librería sobre el universo del LTCMA."""
    return ClassResolver.from_library(cmas, base.names)


def class_loading(
    base: CorrelationMatrix, asset_class: str, cap: float = CORRELATION_CAP
) -> tuple[np.ndarray, float]:
    """Fila de correlaciones de un activo propio contra la base, y su λ.

    La fila ya viene escalada por λ. Devolver λ aparte sirve para el bloque
    entre activos propios y para poder explicarlo en la interfaz.
    """
    members = ltcma_members(base.names).get(asset_class, ())
    if not members:
        raise ValueError(
            f"La clase '{asset_class}' no tiene ninguna clase del LTCMA de la que "
            "derivar correlaciones."
        )

    idx = [base.names.index(n) for n in members]
    # El promedio del bloque incluye los términos g == h, que valen 1. Es lo que
    # hace que el resultado sea exactamente var(p) y, con ello, que la
    # construcción sea realizable. Excluir la diagonal rompe la garantía de PSD
    # en silencio, así que hay un test dedicado a esto.
    var_p = float(base.matrix[np.ix_(idx, idx)].mean())
    lam = 1.0 if var_p <= cap else float(np.sqrt(cap / var_p))

    row = base.matrix[idx, :].mean(axis=0) * lam
    return row, lam


def extend_correlations(
    base: CorrelationMatrix,
    custom: Sequence[tuple[str, str]],
    cap: float = CORRELATION_CAP,
) -> CorrelationMatrix:
    """Matriz con los activos propios añadidos al final, en el orden dado.

    PSD por construcción: es la correlación de un vector aleatorio realizable.
    No pasa por `nearest_psd` a propósito.
    """
    if not custom:
        return base  # es frozen, devolverla tal cual es seguro

    nombres = [n for n, _ in custom]
    repetidos = {n for n in nombres if nombres.count(n) > 1}
    if repetidos:
        raise ValueError(f"Activos propios duplicados: {sorted(repetidos)}")
    ya_estaban = [n for n in nombres if n in base.names]
    if ya_estaban:
        raise ValueError(
            "Estos activos propios chocan con clases del LTCMA: "
            + ", ".join(ya_estaban)
        )

    n = len(base.names)
    k = len(custom)
    extended = np.eye(n + k)
    extended[:n, :n] = base.matrix

    filas: list[np.ndarray] = []
    lambdas: list[float] = []
    for _, asset_class in custom:
        row, lam = class_loading(base, asset_class, cap)
        filas.append(row)
        lambdas.append(lam)

    for i, row in enumerate(filas):
        extended[n + i, :n] = row
        extended[:n, n + i] = row

    # Entre dos activos propios: λ_i · λ_j · promedio cruzado de sus clases.
    # Si comparten clase eso da λ² · var(p), que es exactamente cov(p, p) del
    # mismo portafolio — es decir, dos activos propios de la misma clase se
    # parecen mucho, pero nunca son el mismo activo.
    indices = {
        c: [base.names.index(x) for x in ltcma_members(base.names).get(c, ())]
        for _, c in custom
    }
    for i, (_, ci) in enumerate(custom):
        for j, (_, cj) in enumerate(custom):
            if i == j:
                continue
            cruzado = float(base.matrix[np.ix_(indices[ci], indices[cj])].mean())
            extended[n + i, n + j] = lambdas[i] * lambdas[j] * cruzado

    np.fill_diagonal(extended, 1.0)

    return CorrelationMatrix(
        names=list(base.names) + nombres,
        matrix=extended,
        source=base.source,
        provisional=base.provisional,
        psd_adjustment=base.psd_adjustment,
    )


def derived_preview(
    base: CorrelationMatrix,
    asset_class: str,
    against: Sequence[str] = (),
    cap: float = CORRELATION_CAP,
) -> str:
    """Frase que explica en la interfaz lo que la app va a derivar.

    Sin esto, elegir una clase es una caja negra: el analista no tiene forma de
    saber con qué está simulando en realidad.
    """
    row, lam = class_loading(base, asset_class, cap)
    members = ltcma_members(base.names).get(asset_class, ())
    var_p = lam**2 * float(
        base.matrix[
            np.ix_(
                [base.names.index(n) for n in members],
                [base.names.index(n) for n in members],
            )
        ].mean()
    )

    partes = [
        f"Se comportará como el promedio de {asset_class} "
        f"({len(members)} clases del LTCMA)."
    ]
    muestras = [n for n in against if n in base.names]
    if muestras:
        detalle = " · ".join(
            f"{n} {row[base.names.index(n)]:.2f}" for n in muestras
        )
        partes.append(f"Correlación derivada: {detalle}.")
    partes.append(
        f"Riesgo propio no explicado por la clase: {1 - var_p:.0%}. "
        f"Dos activos propios de esta clase quedan correlacionados al {var_p:.2f}."
    )
    return " ".join(partes)
