"""Gráfico de stress tests: caída de cada estrategia por escenario.

Forma: barras agrupadas. El dato es una magnitud (cuánto cae) comparada entre
estrategias, así que la barra es la forma correcta y el cero es la referencia.
"""

from __future__ import annotations

import numpy as np

from ...engine.stress import StressScenario
from ...model.allocation import Allocation
from ..theme import BASELINE, INK, INK_SOFT, clean_axes, series_color

BAR_GAP = 0.02


def draw_stress_chart(
    canvas,
    allocations: list[Allocation],
    scenarios: list[StressScenario],
    initial_value: float = 0.0,
):
    if not allocations or not scenarios:
        canvas.show_message("Define al menos una estrategia y un escenario de estrés.")
        return

    ax = canvas.clear()
    n = len(allocations)
    group_width = 0.8
    bar_width = group_width / n - BAR_GAP
    positions = np.arange(len(scenarios), dtype=float)

    marks = []
    for i, allocation in enumerate(allocations):
        impacts = np.array([s.impact(allocation) for s in scenarios]) * 100.0
        offset = (i - (n - 1) / 2) * (group_width / n)
        x = positions + offset
        color = series_color(i)
        ax.bar(x, impacts, width=bar_width, color=color, linewidth=0,
               label=allocation.name, zorder=2)

        for xi, value in zip(x, impacts):
            ax.text(
                xi,
                value - 0.8 if value < 0 else value + 0.8,
                f"{value:.1f}%",
                ha="center",
                va="top" if value < 0 else "bottom",
                fontsize=8,
                color=INK_SOFT,
                zorder=4,
            )
            marks.append((xi, bar_width, value, allocation.name, i))

    ax.set_xticks(positions)
    ax.set_xticklabels(
        ["\n".join(_wrap(s.name)) for s in scenarios], fontsize=8
    )
    ax.set_ylabel("Impacto sobre el portafolio (%)")
    ax.axhline(0, color=BASELINE, linewidth=1, zorder=3)
    clean_axes(ax)
    ax.margins(y=0.16)
    if n >= 2:
        # Fuera del área de trazado: abajo a la izquierda tapaba la barra más honda.
        ax.legend(
            loc="lower left",
            bbox_to_anchor=(0, 1.02, 1, 0.12),
            mode="expand",
            ncol=min(n, 3),
            borderaxespad=0,
        )
    ax.set_title(
        "Cada crisis golpea con distinta fuerza según la asignación del portafolio",
        loc="left",
        color=INK,
        pad=28 if n >= 2 else 10,
    )

    def probe(x_data, y_data, _ax):
        if x_data is None:
            return None
        for xi, width, value, name, _idx in marks:
            inside = (min(0, value) <= y_data <= max(0, value))
            if abs(x_data - xi) <= width / 2 and inside:
                text = f"{name}\nImpacto {value:.2f}%"
                if initial_value:
                    text += f"\n{value / 100 * initial_value:,.0f}"
                return text
        return None

    canvas.set_hover_probe(probe)
    canvas.finish()


def _wrap(text: str, width: int = 18) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width and current:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines
