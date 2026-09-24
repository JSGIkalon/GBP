"""Evolución del saldo de la deuda (mediana y rango) por estrategia."""

from __future__ import annotations

import numpy as np
from matplotlib.ticker import MaxNLocator

from ...model.results import SimulationResult
from ..theme import amount_unit, clean_axes, format_display, money_axis, series_color


def draw_debt_chart(canvas, result: SimulationResult):
    if not result:
        canvas.show_message("Corre la simulación para ver la deuda.")
        return

    if not any(s.has_debt for s in result.strategies):
        canvas.show_message(
            "Este caso no tiene apalancamiento.\n"
            "Configura un crédito en la pestaña Apalancamiento para ver su evolución."
        )
        return

    ax = canvas.clear()
    years = np.arange(1, result.horizon + 1)
    series_data = []
    for i, strategy in enumerate(result.strategies):
        # Una sola pasada por los tres percentiles, en vez de una por cada uno.
        low, median, high = np.percentile(strategy.debt, [5, 50, 95], axis=0)
        color = series_color(i)
        ax.fill_between(years, low, high, color=color, alpha=0.16, linewidth=0, zorder=1)
        ax.plot(years, median, color=color, linewidth=2, label=strategy.name, zorder=2)
        series_data.append((strategy.name, median, low, high))

    ax.set_xlabel("Año")
    unidad = amount_unit(result.currency)
    ax.set_ylabel(f"Saldo de la deuda ({unidad})" if unidad else "Saldo de la deuda")
    ax.set_ylim(bottom=0)
    money_axis(ax)
    # Los años son enteros: sin esto el eje rotulaba 2.5, 5.0, 7.5…
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    clean_axes(ax)
    n = len(result.strategies)
    if n >= 2:
        # Fuera del área de trazado: un crédito que arranca al máximo deja la
        # esquina superior derecha ocupada, y ahí la leyenda tapaba la línea.
        ax.legend(
            loc="lower left",
            bbox_to_anchor=(0, 1.02),
            ncol=min(n, 3),
            borderaxespad=0,
            columnspacing=1.6,
            handlelength=1.4,
        )
        ax.margins(y=0.12)

    def probe(x_data, _y, _ax):
        if x_data is None:
            return None
        year = int(round(x_data))
        if not 1 <= year <= result.horizon:
            return None
        lines = [f"Año {year}"]
        for name, median, low, high in series_data:
            m = format_display
            lines.append(
                f"{name}: {m(median[year - 1])}  ({m(low[year - 1])}–{m(high[year - 1])})"
            )
        return "\n".join(lines)

    canvas.set_hover_probe(probe)
    canvas.finish()
