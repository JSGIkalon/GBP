"""Las formas en que se puede dibujar la distribución del patrimonio.

Un solo punto de entrada para la pantalla y el informe: los dos piden «la
distribución, del tipo elegido» y no pueden desacompasarse en cuál dibujan.
"""

from __future__ import annotations

from ...model.results import SimulationResult
from .box_chart import draw_box_chart
from .fan_chart import draw_fan_chart, draw_median_chart

BOXES = "cajas"
FAN = "abanico"
MEDIANS = "medianas"

# Clave guardada en Ajustes -> rótulo del desplegable, en el orden en que se ofrecen.
CHART_KINDS = {
    BOXES: "Cajas por año hito",
    FAN: "Abanico de percentiles",
    MEDIANS: "Medianas comparadas",
}


def normalize_kind(kind: str | None) -> str:
    """Un tipo desconocido —un archivo de ajustes de otra versión— cae a las cajas."""
    return kind if kind in CHART_KINDS else BOXES


def draw_distribution(
    canvas, result: SimulationResult, years: list[int], real: bool = False,
    kind: str = BOXES, show_percentile_labels: bool = True,
):
    kind = normalize_kind(kind)
    if kind == FAN:
        draw_fan_chart(canvas, result, years, real)
    elif kind == MEDIANS:
        draw_median_chart(canvas, result, years, real)
    else:
        draw_box_chart(canvas, result, years, real,
                       show_percentile_labels=show_percentile_labels)
