"""Distribución del patrimonio por año hito.

Forma: box plot agrupado. El dato es la **dispersión** de una distribución en
unos pocos cortes de tiempo, y la caja la muestra sin fingir que hay una serie
continua entre año y año.

Percentiles: caja p25–p75, línea vertical p10–p90, mediana marcada. Se usan
percentiles y no una desviación estándar aritmética porque el patrimonio simulado es
lognormal y asimétrico a la derecha: una banda simétrica alrededor de la media
se va demasiado abajo (llega a dar negativa cuando casi ningún camino lo es) y
se queda corta en la cola alta. Los percentiles salen directo de los caminos
simulados sin suponer ninguna forma de distribución.
"""

from __future__ import annotations

import numpy as np

from ...model.results import SimulationResult
from ..theme import (
    BASELINE,
    INK_SOFT,
    clean_axes,
    format_money,
    series_color,
    series_text_color,
)

# Ancho mínimo por caja, en fracción del eje, para que las cinco etiquetas no
# se encabalguen. Por debajo se etiqueta solo la mediana. Calibrado mirando el
# gráfico: con cuatro años hito y tres estrategias la fracción es ~0.048 y las
# cinco etiquetas caben cómodas.
MIN_WIDTH_FOR_LABELS = 0.030


def draw_box_chart(canvas, result: SimulationResult, years: list[int], real: bool = False):
    if not result or not years:
        canvas.show_message("Corre la simulación para ver la distribución.")
        return

    ax = canvas.clear()
    n_strategies = len(result.strategies)
    group_width = 0.8
    box_width = group_width / n_strategies * 0.72
    positions_base = np.arange(len(years), dtype=float)

    peak = max(
        float(np.abs(np.percentile(s.values(real)[:, [y - 1 for y in years]], 90)).max())
        for s in result.strategies
    )
    scale = 1_000_000.0 if peak >= 1_000_000 else 1.0
    unit = "millones" if scale > 1 else "unidades"

    # ¿Caben las cinco etiquetas por caja, o solo la mediana?
    axis_fraction = box_width / max(len(years), 1)
    label_all = axis_fraction >= MIN_WIDTH_FOR_LABELS

    stats_by_mark: list[tuple[float, float, str, dict]] = []
    boxes_to_label: list[tuple[float, dict, str]] = []

    for i, strategy in enumerate(result.strategies):
        data = strategy.values(real)[:, [y - 1 for y in years]] / scale
        offset = (i - (n_strategies - 1) / 2) * (group_width / n_strategies)
        positions = positions_base + offset
        color = series_color(i)
        on_fill = series_text_color(i)

        stats = []
        for column in data.T:
            p10, p25, p50, p75, p90 = np.percentile(column, [10, 25, 50, 75, 90])
            stats.append(
                {
                    "med": p50,
                    "q1": p25,
                    "q3": p75,
                    "whislo": p10,
                    "whishi": p90,
                    "fliers": [],
                    "mean": float(column.mean()),
                    "std": float(column.std()),
                }
            )

        ax.bxp(
            stats,
            positions=positions,
            widths=box_width,
            showfliers=False,
            patch_artist=True,
            boxprops=dict(facecolor=color, edgecolor=color, linewidth=0),
            medianprops=dict(color=on_fill, linewidth=2),
            whiskerprops=dict(color=color, linewidth=1.4),
            capprops=dict(color=color, linewidth=1.4),
        )
        # Una entrada de leyenda por estrategia (bxp no las crea).
        ax.plot([], [], color=color, linewidth=8, label=strategy.name)

        for pos, stat in zip(positions, stats):
            boxes_to_label.append((pos, stat, on_fill, color))
            stats_by_mark.append((pos, box_width, strategy.name, stat))

    ax.set_xticks(positions_base)
    ax.set_xticklabels([f"Año {y}" for y in years])
    ax.set_ylabel(f"Patrimonio neto ({unit}{', en moneda de hoy' if real else ''})")
    ax.axhline(0, color=BASELINE, linewidth=1, zorder=1)
    clean_axes(ax)
    ax.margins(y=0.12)
    ax.tick_params(axis="x", pad=12)

    # Las etiquetas se ponen al final, cuando el eje Y ya tiene su rango
    # definitivo: sin él no se puede saber si una caja tiene alto suficiente
    # para que sus cuartiles no se encabalguen con la mediana.
    span = float(np.ptp(ax.get_ylim())) or 1.0
    for pos, stat, on_fill, fill in boxes_to_label:
        _label_box(ax, pos, stat, on_fill, fill, label_all, span)

    if n_strategies >= 2:
        # Sin `mode="expand"`: estiraba las entradas a los extremos opuestos del
        # eje y con dos estrategias parecía un error de maquetación.
        ax.legend(
            loc="lower left",
            bbox_to_anchor=(0, 1.02),
            ncol=min(n_strategies, 4),
            borderaxespad=0,
            columnspacing=1.6,
            handlelength=1.4,
        )
    if n_strategies >= 2:
        # Sin título, la leyenda necesita algo de aire encima del eje para no
        # quedar pegada al borde superior de la página.
        ax.margins(y=0.12)

    # La nota va **dentro del eje**, no colgando por debajo en coordenadas de
    # eje: con `xy=(0, -0.16)` caía fuera del área de trazado y, en la geometría
    # de página del PDF, aterrizaba justo encima del pie de página —el título y
    # la fecha impresos por `_new_page`— y los dos textos se superponían.
    footnote = "Caja: percentil 25 a 75 · Línea vertical: percentil 10 a 90 · Etiqueta: mediana"
    if not label_all:
        footnote += " — solo se etiqueta la mediana; el resto está en la tabla"
    ax.set_xlabel(footnote, fontsize=8, color=INK_SOFT, loc="left", labelpad=10)

    def probe(x_data, y_data, _ax):
        if x_data is None:
            return None
        for pos, width, name, stat in stats_by_mark:
            if abs(x_data - pos) <= width / 2 and stat["whislo"] <= y_data <= stat["whishi"]:
                return (
                    f"{name}\n"
                    f"p90   {stat['whishi']:,.1f}\n"
                    f"p75   {stat['q3']:,.1f}\n"
                    f"p50   {stat['med']:,.1f}\n"
                    f"p25   {stat['q1']:,.1f}\n"
                    f"p10   {stat['whislo']:,.1f}\n"
                    f"media {stat['mean']:,.1f}  ·  desv. {stat['std']:,.1f}"
                )
        return None

    canvas.set_hover_probe(probe)
    canvas.finish()


# Separación vertical mínima entre dos etiquetas, en fracción del alto del eje.
# Por debajo se encabalgan y es preferible omitir la de adentro.
MIN_GAP = 0.055


def _label_box(
    ax, pos: float, stat: dict, on_fill: str, fill: str, label_all: bool, span: float
):
    """Etiquetas numéricas, redondeadas y sin decimales.

    La mediana y los extremos de la línea vertical van siempre. Los cuartiles se
    omiten cuando la caja es tan baja que su etiqueta chocaría con la de la
    mediana: el valor sigue estando en la tabla y al pasar el mouse.
    """
    ax.text(
        pos,
        stat["med"],
        f"{stat['med']:,.0f}",
        ha="center",
        va="center",
        fontsize=8,
        fontweight="semibold",
        color=on_fill,
        zorder=6,
        # Fondo del color de la caja: sin él, la línea de la mediana cruza su
        # propia etiqueta y parece texto tachado.
        bbox=dict(boxstyle="square,pad=0.12", facecolor=fill, edgecolor="none"),
    )
    if not label_all:
        return

    for value, va in ((stat["whishi"], "bottom"), (stat["whislo"], "top")):
        ax.text(pos, value, f"{value:,.0f}", ha="center", va=va, fontsize=7,
                color=INK_SOFT, zorder=5)

    for value, va, reference in (
        (stat["q3"], "bottom", stat["whishi"]),
        (stat["q1"], "top", stat["whislo"]),
    ):
        room_from_median = abs(value - stat["med"]) / span
        room_from_whisker = abs(reference - value) / span
        if room_from_median < MIN_GAP or room_from_whisker < MIN_GAP:
            continue
        ax.text(pos, value, f"{value:,.0f}", ha="center", va=va, fontsize=7,
                color=INK_SOFT, zorder=5)


def distribution_table_rows(result: SimulationResult, years: list[int], real: bool = False):
    """Los mismos datos del gráfico, para la vista de tabla.

    Además de los percentiles del gráfico incluye la media y la desviación
    estándar del patrimonio, para quien quiera el número crudo.
    """
    rows = []
    for strategy in result.strategies:
        pct = strategy.percentiles(years, real)
        means = strategy.mean(years, real)
        stds = strategy.std(years, real)
        for i, year in enumerate(years):
            rows.append(
                {
                    "Estrategia": strategy.name,
                    "Año": year,
                    "p10": format_money(pct[10][i]),
                    "p25": format_money(pct[25][i]),
                    "Mediana": format_money(pct[50][i]),
                    "p75": format_money(pct[75][i]),
                    "p90": format_money(pct[90][i]),
                    "Media": format_money(means[i]),
                    "Desv. est.": format_money(stds[i]),
                }
            )
    return rows
