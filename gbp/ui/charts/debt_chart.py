"""Evolución del saldo de la deuda (mediana y rango) por estrategia."""

from __future__ import annotations

import numpy as np

from ...model.results import SimulationResult
from ..theme import INK, clean_axes, series_color


def draw_debt_chart(canvas, result: SimulationResult):
    if not result:
        canvas.show_message("Corre la simulación para ver la deuda.")
        return

    if all(s.debt.max() == 0 for s in result.strategies):
        canvas.show_message(
            "Este caso no tiene apalancamiento.\n"
            "Configura un crédito en la pestaña Apalancamiento para ver su evolución."
        )
        return

    ax = canvas.clear()
    years = np.arange(1, result.horizon + 1)
    peak = max(float(s.debt.max()) for s in result.strategies)
    scale = 1_000_000.0 if peak >= 1_000_000 else 1.0
    unit = "millones" if scale > 1 else "unidades"

    series_data = []
    for i, strategy in enumerate(result.strategies):
        debt = strategy.debt / scale
        median = np.median(debt, axis=0)
        low = np.percentile(debt, 5, axis=0)
        high = np.percentile(debt, 95, axis=0)
        color = series_color(i)
        ax.fill_between(years, low, high, color=color, alpha=0.16, linewidth=0, zorder=1)
        ax.plot(years, median, color=color, linewidth=2, label=strategy.name, zorder=2)
        series_data.append((strategy.name, median, low, high))

    ax.set_xlabel("Año")
    ax.set_ylabel(f"Saldo de la deuda ({unit})")
    ax.set_ylim(bottom=0)
    clean_axes(ax)
    if len(result.strategies) >= 2:
        ax.legend(loc="upper right", ncol=min(len(result.strategies), 3))
    ax.set_title(
        "El saldo de la deuda evoluciona según la amortización y las llamadas a margen",
        loc="left",
        color=INK,
    )

    def probe(x_data, _y, _ax):
        if x_data is None:
            return None
        year = int(round(x_data))
        if not 1 <= year <= result.horizon:
            return None
        lines = [f"Año {year}"]
        for name, median, low, high in series_data:
            lines.append(f"{name}: {median[year - 1]:,.1f}  ({low[year - 1]:,.1f}–{high[year - 1]:,.1f})")
        return "\n".join(lines)

    canvas.set_hover_probe(probe)
    canvas.finish()
