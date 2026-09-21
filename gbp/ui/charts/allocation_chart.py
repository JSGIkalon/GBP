"""Asignación de activos de cada estrategia, en dos lecturas.

Forma: dos paneles apilados, y son dos preguntas distintas.

* Arriba, **barra apilada por clase de activo**. Es la lectura de comité: cuánto
  hay en renta variable, renta fija, alternativos y caja. Cuatro segmentos como
  mucho, así que cada uno puede tomar un paso entero de la rampa azul y las
  clases se separan por color sin esfuerzo.
* Abajo, **barras agrupadas por sub-clase**, ordenadas de mayor a menor. Es el
  detalle que hace falta para reproducir el caso. Aquí el color ya no codifica
  la clase sino la **estrategia**, y la sub-clase la lleva la etiqueta directa.

Por qué no un solo panel
------------------------
Lo natural sería una sola barra apilada con las sub-clases dentro, distinguidas
por intensidad del azul de su clase. Se probó y no funciona: con siete
sub-clases los pasos de intensidad de una clase chocan con los de la vecina —el
segundo tono de renta variable queda igual al primero de renta fija— y el color
deja de decir a qué clase pertenece cada tramo, que era su único trabajo. La
paleta de marca tiene cuatro pasos y no se inventan tonos, así que la salida es
no pedirle al color dos trabajos a la vez.

Con muchas sub-clases el panel de abajo se queda con las más grandes y agrupa la
cola en una fila, porque veinte filas de 1% no se leen y el detalle completo ya
está en el anexo de tablas del informe.
"""

from __future__ import annotations

import numpy as np

from ...model.groups import GROUP_ORDER, OTHER, group_of, group_weights
from ..theme import (
    INK,
    INK_SOFT,
    LEADER,
    NEUTRAL,
    WHITE,
    clean_axes,
    series_color,
    series_text_color,
)

# Relleno y color de texto de cada clase de activo. El orden de `GROUP_ORDER` es
# el de la rampa, así que renta variable toma navy y la caja el azul medio.
CLASS_FILL = {group: series_color(i) for i, group in enumerate(GROUP_ORDER)}
CLASS_TEXT = {group: series_text_color(i) for i, group in enumerate(GROUP_ORDER)}
# Lo que no se pudo clasificar va en gris: se ve que está sin mapear.
CLASS_FILL[OTHER] = NEUTRAL
CLASS_TEXT[OTHER] = INK

# Filas del panel de detalle antes de agrupar la cola. Por encima de esto las
# barras quedan más finas que su propia etiqueta.
MAX_SUBCLASS_ROWS = 14

# Peso mínimo para que la cifra quepa dentro del segmento apilado.
MIN_SHARE_FOR_LABEL = 0.055


def draw_allocation_chart(canvas, scenario, resolver=None, title_x: float = 0.0):
    """Dibuja los dos paneles para las estrategias del escenario.

    `title_x` corre el titular en fracción del ancho del eje. Existe porque en
    el informe este gráfico usa un margen izquierdo mucho más ancho que los
    demás —los nombres de sub-clase son largos— y sin corrección su titular
    quedaba sangrado media página respecto al de las otras láminas. En pantalla
    el valor por defecto deja el titular donde siempre.
    """
    strategies = [s for s in scenario.strategies if s.asset_names]
    if not strategies:
        canvas.show_message(
            "Define los pesos de al menos una estrategia para ver su asignación."
        )
        return

    grouped = [group_weights(s.weights, resolver) for s in strategies]
    if not any(grouped):
        canvas.show_message(
            "Las estrategias no tienen pesos cargados todavía."
        )
        return

    top, bottom = canvas.panels((1.0, 2.2))

    classes = _classes_present(grouped)
    marks = _draw_classes(top, strategies, grouped, classes, title_x)
    rows = _subclass_rows(strategies, resolver)
    marks += _draw_subclasses(bottom, strategies, rows, title_x)

    canvas.set_hover_probe(_probe(marks))
    canvas.finish()


# ----------------------------------------------------------------- clases
def _classes_present(grouped: list[dict[str, float]]) -> list[str]:
    """Clases con peso en alguna estrategia, en orden de lectura."""
    presentes = {g for pesos in grouped for g in pesos}
    ordenadas = [g for g in GROUP_ORDER if g in presentes]
    if OTHER in presentes:
        ordenadas.append(OTHER)
    return ordenadas


def _draw_classes(ax, strategies, grouped, classes, title_x: float = 0.0) -> list[tuple]:
    marks = []
    for row, (strategy, pesos) in enumerate(zip(strategies, grouped)):
        left = 0.0
        y = len(strategies) - 1 - row
        for group in classes:
            share = pesos.get(group, 0.0)
            if not share:
                continue
            # El borde blanco separa segmentos vecinos sin dibujar una línea:
            # es el fondo de la página asomando entre dos rellenos.
            ax.barh(y, share, left=left, height=0.46, color=CLASS_FILL[group],
                    edgecolor=WHITE, linewidth=1.2, zorder=2)
            if share >= MIN_SHARE_FOR_LABEL:
                ax.text(left + share / 2, y, f"{share:.0%}", ha="center", va="center",
                        fontsize=9, fontweight="semibold", color=CLASS_TEXT[group],
                        zorder=3)
            marks.append((ax, left, left + share, y, 0.46,
                          f"{strategy.name}\n{group} {share:.1%}"))
            left += share

    ax.set_yticks(range(len(strategies)))
    ax.set_yticklabels([s.name for s in reversed(strategies)], fontsize=9.5, color=INK)
    ax.set_xlim(0, 1)
    ax.set_xticks([])
    ax.set_ylim(-0.6, len(strategies) - 0.4)
    # Sin marco ni rejilla: los segmentos ya suman el 100% del ancho, así que un
    # eje de porcentaje no añadiría lectura y sí ruido.
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.grid(False)
    ax.tick_params(length=0)

    from matplotlib.patches import Patch

    ax.legend(
        handles=[Patch(facecolor=CLASS_FILL[g], label=g) for g in classes],
        loc="lower left",
        bbox_to_anchor=(title_x, 1.02),
        ncol=len(classes),
        borderaxespad=0,
        frameon=False,
        fontsize=9,
        columnspacing=1.6,
        handlelength=1.2,
    )
    ax.set_title(
        "Cada estrategia reparte el patrimonio entre las cuatro clases de activo",
        loc="left",
        color=INK,
        pad=26,
        x=title_x,
    )
    return marks


# -------------------------------------------------------------- sub-clases
def _subclass_rows(strategies, resolver) -> list[tuple[str, list[float]]]:
    """`(sub-clase, peso en cada estrategia)`, de mayor a menor peso medio."""
    normalizados = []
    for strategy in strategies:
        total = sum(strategy.weights.values())
        normalizados.append(
            {n: w / total for n, w in strategy.weights.items() if w} if total > 0 else {}
        )

    nombres = {n for pesos in normalizados for n in pesos}
    filas = [
        (n, [pesos.get(n, 0.0) for pesos in normalizados])
        for n in nombres
    ]
    filas.sort(key=lambda fila: -sum(fila[1]))

    if len(filas) <= MAX_SUBCLASS_ROWS:
        return filas

    cabeza, cola = filas[:MAX_SUBCLASS_ROWS - 1], filas[MAX_SUBCLASS_ROWS - 1:]
    resto = [sum(valores) for valores in zip(*[f[1] for f in cola])]
    return cabeza + [(f"Otras {len(cola)} sub-clases", resto)]


def _draw_subclasses(ax, strategies, rows, title_x: float = 0.0) -> list[tuple]:
    marks = []
    ys = np.arange(len(rows))
    n = len(strategies)
    height = 0.72 / n

    peak = max((max(valores) for _, valores in rows), default=0.0) or 1.0

    for i, strategy in enumerate(strategies):
        color = series_color(i)
        valores = [fila[1][i] for fila in rows]
        # El eje está invertido, así que un `y` mayor cae más abajo: para que la
        # primera estrategia quede arriba —como en el panel de clases y en la
        # leyenda— su desplazamiento tiene que ser negativo.
        pos = ys + (i - (n - 1) / 2) * height
        ax.barh(pos, valores, height=height, color=color, label=strategy.name, zorder=2)
        for (nombre, _), y, value in zip(rows, pos, valores):
            if value:
                ax.text(value + peak * 0.012, y, f"{value:.1%}", va="center",
                        fontsize=7.5, color=INK_SOFT, zorder=3)
            marks.append((ax, 0.0, value, y, height,
                          f"{strategy.name}\n{nombre} {value:.1%}"))

    ax.set_yticks(ys)
    ax.set_yticklabels([nombre for nombre, _ in rows], fontsize=8.5, color=INK)
    ax.invert_yaxis()
    ax.set_xlim(0, peak * 1.16)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    clean_axes(ax)
    # `clean_axes` deja la rejilla horizontal, que aquí no dice nada: las
    # categorías son nominales y la magnitud se lee sobre el eje X.
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=NEUTRAL, linewidth=0.8)
    ax.spines["bottom"].set_color(LEADER)
    ax.set_axisbelow(True)
    if n >= 2:
        ax.legend(loc="lower right", frameon=False, fontsize=8.5)
    ax.set_title("Detalle por sub-clase", loc="left", color=INK, fontsize=10, pad=8,
                 x=title_x)
    return marks


# ------------------------------------------------------------------ hover
def _probe(marks):
    """Detalle al pasar el mouse, sobre cualquiera de los dos paneles."""

    def probe(x_data, y_data, ax):
        if x_data is None:
            return None
        for owner, x0, x1, y, height, text in marks:
            if owner is not ax:
                continue
            if min(x0, x1) <= x_data <= max(x0, x1) and abs(y_data - y) <= height / 2:
                return text
        return None

    return probe


def allocation_table_rows(scenario, resolver=None) -> list[dict]:
    """Los mismos pesos del gráfico, para la tabla del anexo."""
    rows = []
    for strategy in scenario.strategies:
        total = sum(strategy.weights.values())
        if total <= 0:
            continue
        clasificar = resolver.group_of if resolver is not None else group_of
        for name, weight in strategy.weights.items():
            if not weight:
                continue
            grupo = clasificar(name)
            rows.append(
                {
                    "Estrategia": strategy.name,
                    "Clase de activo": grupo,
                    "Sub-clase": name,
                    "Peso": f"{weight / total:.1%}",
                }
            )
    return rows
