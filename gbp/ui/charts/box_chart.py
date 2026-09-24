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
    amount_unit,
    clean_axes,
    format_display,
    larger_scales,
    money_axis,
    series_color,
    series_text_color,
)

# Ancho mínimo por caja, en fracción del eje, para que las cinco etiquetas no
# se encabalguen. Por debajo se etiqueta solo la mediana. Calibrado mirando el
# gráfico: con cuatro años hito y tres estrategias la fracción es ~0.048 y las
# cinco etiquetas caben cómodas.
MIN_WIDTH_FOR_LABELS = 0.030
# Largo de la etiqueta con que se calibró el umbral de arriba (cifras en
# millones sin decimales, como «44»). El umbral escala con el largo real.
CALIBRATION_DIGITS = 3


def _box_stats(strategy, years: list[int], real: bool) -> list[dict]:
    """Percentiles, media y desviación de cada año hito, sin escalar.

    Vienen de la caché de la estrategia (`distribution_stats`), que es la
    misma que usa la tabla: con un millón de caminos, ocultar o mostrar las
    etiquetas de percentiles tardaba segundos recalculando cifras que no
    habían cambiado.
    """
    s = strategy.distribution_stats(years, real)
    return [
        {
            "med": float(s[50][i]), "q1": float(s[25][i]), "q3": float(s[75][i]),
            "whislo": float(s[10][i]), "whishi": float(s[90][i]),
            "mean": float(s["mean"][i]), "std": float(s["std"][i]),
        }
        for i in range(len(years))
    ]


def draw_box_chart(
    canvas, result: SimulationResult, years: list[int], real: bool = False,
    show_percentile_labels: bool = True,
):
    if not result or not years:
        canvas.show_message("Corre la simulación para ver la distribución.")
        return

    ax = canvas.clear()
    n_strategies = len(result.strategies)
    group_width = 0.8
    box_width = group_width / n_strategies * 0.72
    positions_base = np.arange(len(years), dtype=float)

    raw_stats = [_box_stats(s, years, real) for s in result.strategies]

    stats_by_mark: list[tuple[float, float, str, dict]] = []
    boxes_to_label: list[tuple[float, dict, str]] = []

    for i, strategy in enumerate(result.strategies):
        offset = (i - (n_strategies - 1) / 2) * (group_width / n_strategies)
        positions = positions_base + offset
        color = series_color(i)
        on_fill = series_text_color(i)

        stats = [{**stat, "fliers": []} for stat in raw_stats[i]]

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
    ax.axhline(0, color=BASELINE, linewidth=1, zorder=1)
    clean_axes(ax)

    def set_scale(scale):
        unidad = amount_unit(result.currency, scale)
        moneda = f" ({unidad})" if unidad else ""
        ax.set_ylabel(
            f"Patrimonio neto{moneda}, en moneda de hoy" if real else f"Patrimonio neto{moneda}"
        )
        money_axis(ax, scale=scale)

    # Aire arriba y abajo: para las etiquetas de p10/p90 y, con dos o más
    # estrategias, para la leyenda sobre el eje.
    ax.margins(y=0.12)
    ax.tick_params(axis="x", pad=12)
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

    # La escala del gráfico: la de Ajustes, o una mayor si con ella las
    # etiquetas no caben horizontales. Se mide con los márgenes ya puestos
    # —con la escala de Ajustes, que es la de rótulos más largos—, porque el
    # ancho útil del eje depende de ellos. Todo el gráfico usa la misma escala
    # y el rótulo del eje la dice.
    set_scale(None)
    canvas.layout_now()
    style = _chart_style(ax, boxes_to_label, box_width)
    scale = style["scale"]
    set_scale(scale)

    # ¿Caben las cinco etiquetas por caja, o solo la mediana? El umbral
    # depende del largo de la cifra más larga en la escala elegida.
    digits = max(
        len(format_display(stat[k], scale)) for stats in raw_stats for stat in stats
        for k in ("whishi", "whislo")
    )
    axis_fraction = box_width / max(len(years), 1)
    label_all = axis_fraction >= MIN_WIDTH_FOR_LABELS * digits / CALIBRATION_DIGITS

    # Las etiquetas se ponen al final, cuando el eje Y ya tiene su rango
    # definitivo: sin él no se puede saber si una caja tiene alto suficiente
    # para que sus cuartiles no se encabalguen con la mediana.
    span = float(np.ptp(ax.get_ylim())) or 1.0
    for pos, stat, on_fill, fill in boxes_to_label:
        _label_box(ax, pos, stat, on_fill, fill, label_all and show_percentile_labels, span,
                   style)

    # La nota va **dentro del eje**, no colgando por debajo en coordenadas de
    # eje: con `xy=(0, -0.16)` caía fuera del área de trazado y, en la geometría
    # de página del PDF, aterrizaba justo encima del pie de página —el título y
    # la fecha impresos por `_new_page`— y los dos textos se superponían.
    footnote = "Caja: percentil 25 a 75 · Línea vertical: percentil 10 a 90 · Etiqueta: mediana"
    if not (label_all and show_percentile_labels):
        footnote += " — solo se etiqueta la mediana; el resto está en la tabla"
    ax.set_xlabel(footnote, fontsize=8, color=INK_SOFT, loc="left", labelpad=10)

    def probe(x_data, y_data, _ax):
        if x_data is None:
            return None
        for pos, width, name, stat in stats_by_mark:
            if abs(x_data - pos) <= width / 2 and stat["whislo"] <= y_data <= stat["whishi"]:
                def m(v):
                    return format_display(v, scale)

                return (
                    f"{name}\n"
                    f"p90   {m(stat['whishi'])}\n"
                    f"p75   {m(stat['q3'])}\n"
                    f"p50   {m(stat['med'])}\n"
                    f"p25   {m(stat['q1'])}\n"
                    f"p10   {m(stat['whislo'])}\n"
                    f"media {m(stat['mean'])}  ·  desv. {m(stat['std'])}"
                )
        return None

    canvas.set_hover_probe(probe)
    canvas.finish()


# Separación vertical mínima entre dos etiquetas, en fracción del alto del eje.
# Por debajo se encabalgan y es preferible omitir la de adentro.
MIN_GAP = 0.055


# Tamaño de la mediana, y el mínimo legible antes de pasar a otra escala.
MEDIAN_FONT = 8.0
MIN_MEDIAN_FONT = 6.5


def _renderer(figure):
    canvas = getattr(figure, "canvas", None)
    if canvas is not None and hasattr(canvas, "get_renderer"):
        return canvas.get_renderer()
    return figure._get_renderer()


def _medians_fit(ax, boxes, box_width: float, scale: str, fontsize: float) -> bool:
    """Si las medianas, puestas horizontales, no tocan otra etiqueta ni otra caja.

    Se **miden** con el renderizador en vez de estimarlas por número de
    caracteres: la estimación fallaba justo en el caso que importa, tres
    estrategias con cifras completas, y las etiquetas se pisaban. Una etiqueta
    puede ser más ancha que su propia caja, pero no puede invadir la vecina.
    """
    renderer = _renderer(ax.figure)
    to_px = ax.transData.transform
    gap = 5.0  # píxeles de aire hasta lo vecino
    labels, cajas = [], []
    for pos, stat, *_ in boxes:
        text = ax.text(pos, stat["med"], format_display(stat["med"], scale),
                       ha="center", va="center", fontsize=fontsize, fontweight="semibold")
        bbox = text.get_window_extent(renderer)
        text.remove()
        labels.append((bbox.x0 - gap, bbox.x1 + gap, bbox.y0, bbox.y1))
        (x0, y0), (x1, y1) = to_px([(pos - box_width / 2, stat["q1"]),
                                    (pos + box_width / 2, stat["q3"])])
        cajas.append((x0, x1, min(y0, y1), max(y0, y1)))

    def hit(a, b):
        return a[0] < b[1] and b[0] < a[1] and a[2] < b[3] and b[2] < a[3]

    for i, label in enumerate(labels):
        for j in range(len(labels)):
            if j != i and (hit(label, labels[j]) or hit(label, cajas[j])):
                return False
    return True


def _chart_style(ax, boxes, box_width: float) -> dict:
    """Escala y tamaño de letra de las etiquetas: **siempre horizontales**.

    Con cifras completas la mediana de una caja puede ser más ancha que el
    espacio hasta la caja vecina. Primero se achica la letra, hasta un mínimo
    legible; si ni así caben, el gráfico pasa a la siguiente escala —de la
    elegida en Ajustes a miles, millones o miles de millones— hasta que quepan.
    El eje dice en qué escala quedó. Las etiquetas nunca van verticales.
    """
    scales = larger_scales()
    # Antes una escala mayor con letra normal que una cifra diminuta: la letra
    # solo se achica si ni en miles de millones cabe a tamaño normal.
    for fontsize in (MEDIAN_FONT, 7.0, MIN_MEDIAN_FONT):
        for scale in scales:
            if _medians_fit(ax, boxes, box_width, scale, fontsize):
                return {"scale": scale, "fontsize": fontsize}
    return {"scale": scales[-1], "fontsize": MIN_MEDIAN_FONT}


def _label_box(
    ax, pos: float, stat: dict, on_fill: str, fill: str, label_all: bool, span: float,
    style: dict | None = None,
):
    """Etiquetas numéricas, horizontales, en la escala del gráfico.

    La mediana y los extremos de la línea vertical van siempre. Los cuartiles se
    omiten cuando la caja es tan baja que su etiqueta chocaría con la de la
    mediana: el valor sigue estando en la tabla y al pasar el mouse.
    """
    style = style or {"fontsize": MEDIAN_FONT, "scale": None}
    scale = style["scale"]
    ax.text(
        pos,
        stat["med"],
        format_display(stat["med"], scale),
        ha="center",
        va="center",
        fontsize=style["fontsize"],
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
        ax.text(pos, value, format_display(value, scale), ha="center", va=va, fontsize=7,
                color=INK_SOFT, zorder=5)

    for value, va, reference in (
        (stat["q3"], "bottom", stat["whishi"]),
        (stat["q1"], "top", stat["whislo"]),
    ):
        room_from_median = abs(value - stat["med"]) / span
        room_from_whisker = abs(reference - value) / span
        if room_from_median < MIN_GAP or room_from_whisker < MIN_GAP:
            continue
        ax.text(pos, value, format_display(value, scale), ha="center", va=va, fontsize=7,
                color=INK_SOFT, zorder=5)


def distribution_table_rows(result: SimulationResult, years: list[int], real: bool = False):
    """Los mismos datos del gráfico, para la vista de tabla.

    Además de los percentiles del gráfico incluye la media y la desviación
    estándar del patrimonio, para quien quiera el número crudo.
    """
    rows = []
    for strategy in result.strategies:
        # Las mismas cifras que el gráfico, de la misma caché: no se recalculan.
        pct = strategy.distribution_stats(years, real)
        means, stds = pct["mean"], pct["std"]
        for i, year in enumerate(years):
            rows.append(
                {
                    "Estrategia": strategy.name,
                    "Año": year,
                    "p10": format_display(pct[10][i]),
                    "p25": format_display(pct[25][i]),
                    "Mediana": format_display(pct[50][i]),
                    "p75": format_display(pct[75][i]),
                    "p90": format_display(pct[90][i]),
                    "Media": format_display(means[i]),
                    "Desv. est.": format_display(stds[i]),
                }
            )
    return rows
