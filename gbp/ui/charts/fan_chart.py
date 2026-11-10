"""La distribución del patrimonio como serie continua: abanico y medianas.

Son la misma proyección que el gráfico de cajas, leída de otra manera. Las
cajas muestran la dispersión en unos pocos años hito; el **abanico** muestra
cómo se abre esa dispersión año a año, y las **medianas** dejan una sola línea
por estrategia para compararlas sin nada más encima.

El abanico va en un panel por estrategia, con el eje Y compartido, y no todas
superpuestas en un eje: las series son pasos de una misma rampa azul, y cuatro
bandas translúcidas de la misma gama una sobre otra se funden en una mancha. Con
el eje compartido las alturas se siguen comparando de un panel al de al lado.

Las dos vistas arrancan en el año 0, con el capital inicial: es el punto del
que se abre el abanico y el que ancla la lectura de todo lo demás.
"""

from __future__ import annotations

import numpy as np
from matplotlib.patheffects import withStroke

from ...model.results import SimulationResult
from ..theme import (
    BASELINE,
    INK,
    INK_SOFT,
    SURFACE,
    amount_unit,
    clean_axes,
    format_display,
    money_axis,
    series_color,
)

FAN_NOTE = ("Eje horizontal: año · Banda clara: percentil 10 a 90 · "
            "Banda intensa: percentil 25 a 75 · Línea: mediana")
MEDIAN_NOTE = "Eje horizontal: año · Línea: patrimonio neto mediano de cada estrategia"
NOTE_FONT = 8


def _series(strategy, real: bool) -> dict:
    """Percentiles de todos los años, con el capital inicial como año 0.

    Salen de la misma caché que las cajas y la tabla (`distribution_stats`),
    así que cambiar de gráfico no recalcula nada después de la primera vez.
    """
    years = list(range(1, strategy.horizon + 1))
    stats = strategy.distribution_stats(years, real)
    start = strategy.initial_value
    return {p: np.concatenate(([start], stats[p])) for p in (10, 25, 50, 75, 90)}


def _y_label(result: SimulationResult, real: bool) -> str:
    unidad = amount_unit(result.currency)
    moneda = f" ({unidad})" if unidad else ""
    return f"Patrimonio neto{moneda}, en moneda de hoy" if real else f"Patrimonio neto{moneda}"


def _year_ticks(ax, years: list[int], horizon: int):
    """Marcas en los años hito —los de la tabla de abajo— y en el año final.

    El final se rotula aunque no sea hito, porque ahí termina la serie y ahí
    está la cifra que se etiqueta; salvo que quede pegado al último hito, donde
    los dos rótulos se montarían.
    """
    ticks = [y for y in years if 1 <= y <= horizon]
    if not ticks or horizon - ticks[-1] >= max(2, 0.07 * horizon):
        ticks.append(horizon)
    ax.set_xticks(ticks)
    ax.set_xlim(0, horizon)


def draw_fan_chart(canvas, result: SimulationResult, years: list[int], real: bool = False):
    if not result or not years:
        canvas.show_message("Corre la simulación para ver la distribución.")
        return

    strategies = result.strategies
    axes = canvas.columns(len(strategies))
    x = np.arange(0, result.horizon + 1)
    by_axes = {}

    for i, (ax, strategy) in enumerate(zip(axes, strategies)):
        color = series_color(i)
        data = _series(strategy, real)
        by_axes[ax] = (strategy.name, data)

        ax.fill_between(x, data[10], data[90], color=color, alpha=0.20, linewidth=0, zorder=2)
        ax.fill_between(x, data[25], data[75], color=color, alpha=0.42, linewidth=0, zorder=3)
        ax.plot(x, data[50], color=color, linewidth=2, zorder=4)
        ax.axhline(0, color=BASELINE, linewidth=1, zorder=1)

        # La mediana final, rotulada sobre su punto: es la cifra que se busca.
        ax.annotate(
            format_display(float(data[50][-1])),
            xy=(x[-1], data[50][-1]), xytext=(-3, 4), textcoords="offset points",
            ha="right", va="bottom", fontsize=8, fontweight="semibold", color=INK, zorder=6,
            # Halo blanco: la cifra cae sobre la banda, que en la serie navy es
            # casi tan oscura como el texto.
            path_effects=[withStroke(linewidth=2.6, foreground=SURFACE)],
        )

        if len(strategies) >= 2:
            ax.set_title(strategy.name, loc="left", fontsize=10)
        _year_ticks(ax, years, result.horizon)
        clean_axes(ax)
        ax.margins(y=0.08)
        if i > 0:
            ax.tick_params(labelleft=False)

    axes[0].set_ylabel(_y_label(result, real))
    money_axis(axes[0])

    # La nota va bajo el primer panel y sigue de largo por debajo de los demás.
    # Se saca del cálculo de márgenes —si no, `tight_layout` separaría los
    # paneles para hacerle sitio a lo ancho— y los otros paneles reservan su
    # renglón con un rótulo en blanco del mismo cuerpo.
    note = axes[0].set_xlabel(FAN_NOTE, fontsize=NOTE_FONT, color=INK_SOFT, loc="left",
                              labelpad=10)
    if len(axes) > 1:
        note.set_in_layout(False)
        for ax in axes[1:]:
            ax.set_xlabel("Año", fontsize=NOTE_FONT, labelpad=10, alpha=0.0)

    def probe(x_data, _y, ax):
        if x_data is None or ax not in by_axes:
            return None
        year = int(round(x_data))
        if not 0 <= year <= result.horizon:
            return None
        name, data = by_axes[ax]
        m = format_display
        if year == 0:
            return f"{name} · Año 0\ncapital inicial {m(float(data[50][0]))}"
        return (
            f"{name} · Año {year}\n"
            f"p90   {m(float(data[90][year]))}\n"
            f"p75   {m(float(data[75][year]))}\n"
            f"p50   {m(float(data[50][year]))}\n"
            f"p25   {m(float(data[25][year]))}\n"
            f"p10   {m(float(data[10][year]))}"
        )

    canvas.set_hover_probe(probe)
    canvas.finish()


def draw_median_chart(canvas, result: SimulationResult, years: list[int], real: bool = False):
    if not result or not years:
        canvas.show_message("Corre la simulación para ver la distribución.")
        return

    ax = canvas.clear()
    x = np.arange(0, result.horizon + 1)
    medians = []
    for i, strategy in enumerate(result.strategies):
        median = _series(strategy, real)[50]
        medians.append((strategy.name, median))
        ax.plot(x, median, color=series_color(i), linewidth=2.2, label=strategy.name, zorder=3)

    ax.axhline(0, color=BASELINE, linewidth=1, zorder=1)
    _year_ticks(ax, years, result.horizon)
    ax.set_ylabel(_y_label(result, real))
    money_axis(ax)
    clean_axes(ax)
    ax.margins(y=0.10)
    ax.set_xlabel(MEDIAN_NOTE, fontsize=NOTE_FONT, color=INK_SOFT, loc="left", labelpad=10)

    n = len(result.strategies)
    if n >= 2:
        ax.legend(
            loc="lower left", bbox_to_anchor=(0, 1.02), ncol=min(n, 4),
            borderaxespad=0, columnspacing=1.6, handlelength=1.4,
        )

    def probe(x_data, _y, _ax):
        if x_data is None:
            return None
        year = int(round(x_data))
        if not 0 <= year <= result.horizon:
            return None
        lines = [f"Año {year} · mediana"]
        lines += [f"{name}: {format_display(float(median[year]))}" for name, median in medians]
        return "\n".join(lines)

    canvas.set_hover_probe(probe)
    canvas.finish()
