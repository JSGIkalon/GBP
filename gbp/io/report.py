"""Informe PDF de una corrida: el registro de la simulación y lo que se entrega.

El PDF se arma **con matplotlib**, no con una librería de maquetación. Dos
razones, y las dos pesan:

1. **No agrega dependencia al ejecutable.** matplotlib ya viaja dentro del .exe
   porque dibuja todos los gráficos de la app; una librería de PDF sumaría otro
   paquete a empaquetar y otra cosa que puede fallar congelada.
2. **Los gráficos del informe son los mismos de la pantalla.** Se reusan las
   funciones de `gbp/ui/charts/`, así que el PDF no puede desincronizarse de lo
   que el usuario vio: si cambia un gráfico, cambia en los dos lados.

El precio es que las tablas se dibujan como tablas de matplotlib y hay que
paginarlas a mano. Está resuelto en `_table_pages`.

El informe es un registro: cada página lleva la fecha y el número de caminos.
La semilla del sorteo es fija en el motor y no se expone en la interfaz ni en
el documento —no es un parámetro que el analista deba conocer ni decidir.

Estructura
----------
Portada · supuestos del caso · **asignación (con su tabla debajo)** ·
**supuestos resumen** · proyección · deuda · **anexo**.

**En el cuerpo va la tabla de la gráfica que explica, debajo de ella**: los
supuestos resumen antes de la proyección —dicen con qué retorno, volatilidad y
Sharpe se generó la nube de trayectorias que viene a continuación— y la
asignación de activos bajo su propia lámina, que es el detalle exacto de las
barras que se tienen delante. En el anexo obligaban a irse al final del documento
para leer la cifra de lo que se estaba mirando.

El resto de las tablas sí viven en el anexo, y ahí **cada estrategia ocupa una
hoja**: su proyección en las dos unidades y su deuda, repartidas en una retícula
de dos columnas. La ficha completa de una estrategia es una sola
página que se puede arrancar y entregar; por tema, había que recorrer el anexo
entero para armarla.

Detrás de esas hojas va una más con los **ingresos y retiros año por año**, una
tabla por estrategia. No cabe en la retícula porque tiene una fila por año del
horizonte, y hace falta para comprobar que un flujo indexado crece como se
esperaba y que uno porcentual se recalcula sobre el patrimonio vigente.

Cada gráfica del cuerpo cita las hojas de su tema. Los números se reservan antes
de escribir la primera página, en `_build_annex`, porque el PDF se escribe de una
sola pasada con `PdfPages`.

La distribución se imprime **dos veces**: en valores nominales y en moneda de
hoy. Son la misma proyección contada en dos unidades y las dos hacen falta —la
nominal es la que verá en su extracto, la real es la que dice qué podrá comprar—
así que el informe no obliga a elegir una en la ventana de exportación.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure

from ..model.groups import group_summary
from ..model.results import SimulationResult
from ..model.scenario import Scenario, SimulationSettings
from ..ui.charts.allocation_chart import allocation_table_rows, draw_allocation_chart
from ..ui.charts.box_chart import distribution_table_rows, draw_box_chart
from ..ui.charts.debt_chart import draw_debt_chart
from ..ui.theme import (
    BLUE_MID,
    INK,
    INK_SOFT,
    LEADER,
    NAVY,
    NEUTRAL,
    apply_matplotlib_style,
    format_money,
    series_color,
)

PAGE_SIZE = (11.69, 8.27)  # A4 apaisado: los gráficos son anchos, no altos
MARGIN = 0.06

DISCLAIMER = (
    "Las proyecciones son hipotéticas, se basan en supuestos de mercado de largo plazo "
    "y no reflejan resultados reales ni garantizan rendimientos futuros. El modelo no "
    "incorpora impuestos ni comisiones de gestión. Documento preparado por Ikalon "
    "Investments para uso del destinatario."
)


@dataclass
class ReportOptions:
    """Lo que el usuario decide en la ventana de exportación."""

    title: str = "Proyección patrimonial"
    client: str = ""
    author: str = ""
    report_date: date = field(default_factory=date.today)
    notes: str = ""
    include_distribution: bool = True
    include_summary: bool = True
    include_allocation: bool = True
    include_debt: bool = True
    include_inputs: bool = True
    include_flows: bool = True
    include_disclaimer: bool = True
    # Resolvedor de clases y librería: hacen falta para que los activos propios
    # salgan agrupados en su clase declarada y documentados como tales.
    resolver: object | None = None
    cmas: object | None = None

    @property
    def date_text(self) -> str:
        meses = [
            "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
        ]
        return f"{self.report_date.day} de {meses[self.report_date.month - 1]} de {self.report_date.year}"


class _FigureCanvas:
    """Adaptador mínimo para reusar las funciones de gráfico sobre una figura.

    Las funciones de `gbp/ui/charts/` esperan el lienzo de Qt: le piden un eje
    con `clear()`, le cuelgan un `hover probe` y llaman a `finish()`. Fuera de la
    interfaz no hay mouse, así que el probe se descarta y `finish()` solo ajusta
    márgenes. Así el PDF usa exactamente el mismo código de dibujo que la
    pantalla, sin duplicarlo.
    """

    def __init__(self, figure: Figure, rect=(0.06, 0.12, 0.88, 0.72)):
        self.figure = figure
        self._rect = rect

    def clear(self):
        return self.figure.add_axes(self._rect)

    def panels(self, height_ratios):
        """Los mismos ejes apilados que ofrece el lienzo de Qt, dentro del rect.

        No se usa `Figure.subplots`: repartiría la figura entera e ignoraría el
        rect, y el gráfico se comería la cabecera y el pie de la página.
        """
        x, y, width, height = self._rect
        ratios = list(height_ratios)
        gap = 0.10 * height / max(len(ratios) - 1, 1)  # aire entre paneles
        usable = height - gap * (len(ratios) - 1)
        alturas = [usable * r / sum(ratios) for r in ratios]

        ejes = []
        top = y + height
        for alto in alturas:
            top -= alto
            ejes.append(self.figure.add_axes((x, top, width, alto)))
            top -= gap
        return ejes

    def set_hover_probe(self, _probe):
        pass

    def finish(self):
        pass

    def show_message(self, message: str):
        ax = self.figure.add_axes(self._rect)
        ax.axis("off")
        ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=10, color=INK_SOFT)


# ----------------------------------------------------------------------
def _new_page(pdf: PdfPages, options: ReportOptions, eyebrow: str, page_no: int) -> Figure:
    figure = Figure(figsize=PAGE_SIZE, dpi=150)
    figure.patch.set_facecolor("white")

    figure.text(MARGIN, 0.955, eyebrow.upper(), color=NAVY, fontsize=9,
                fontweight="semibold")
    figure.text(1 - MARGIN, 0.955, "IKALON", color=NAVY, fontsize=11,
                fontweight="semibold", ha="right")
    _add_rule(figure, 0.945)
    figure.text(
        MARGIN, 0.035,
        f"{options.title} · {options.date_text}",
        color=INK_SOFT, fontsize=7.5,
    )
    figure.text(1 - MARGIN, 0.035, str(page_no), color=INK_SOFT, fontsize=7.5, ha="right")
    return figure


def _add_rule(figure: Figure, y: float):
    from matplotlib.lines import Line2D

    figure.add_artist(
        Line2D([MARGIN, 1 - MARGIN], [y, y], color=NEUTRAL, linewidth=1,
               transform=figure.transFigure)
    )


def _swatch(figure: Figure, x: float, y: float, color: str):
    """Cuadrito de color de la serie, en coordenadas de figura."""
    from matplotlib.patches import Rectangle

    figure.add_artist(
        Rectangle((x, y), 0.009, 0.010, facecolor=color, edgecolor="none",
                  transform=figure.transFigure)
    )


def _wrap(text: str, width: int) -> list[str]:
    """Corte por palabras. `textwrap` no respeta los saltos que el usuario puso."""
    import textwrap

    lines: list[str] = []
    for paragraph in text.splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(paragraph, width=width))
    return lines


# ----------------------------------------------------------------------
# Las cuatro cifras de cabecera de la portada: lo que define la corrida antes
# de mirar un solo resultado. El mismo patrón "número grande / eyebrow debajo"
# que usan las tarjetas KPI del cuerpo, para que la portada anticipe el
# lenguaje visual del resto del informe en vez de abrir con un párrafo.
def _cover_kpis(scenario: Scenario, result: SimulationResult,
                settings: SimulationSettings) -> list[tuple[str, str]]:
    return [
        (format_money(scenario.initial_value), "Capital inicial"),
        (f"{scenario.horizon} años", "Horizonte"),
        (f"{scenario.inflation:.2%}", "Inflación anual"),
        (f"{result.n_paths:,}", "Simulaciones"),
    ]


def _cover(pdf: PdfPages, options: ReportOptions, scenario: Scenario,
           result: SimulationResult, settings: SimulationSettings):
    figure = Figure(figsize=PAGE_SIZE, dpi=150)
    figure.patch.set_facecolor("white")

    figure.text(
        MARGIN, 0.93, "PROYECCIÓN PATRIMONIAL · CONFIDENCIAL",
        color=BLUE_MID, fontsize=9, fontweight="semibold",
    )
    figure.text(MARGIN, 0.86, options.title, color=NAVY, fontsize=28,
                fontweight="semibold", va="top")

    y = 0.74
    ficha = " · ".join(
        value for value in (
            f"Caso {scenario.name}" if scenario.name else "",
            options.client, options.date_text,
            f"Preparado por {options.author}" if options.author else "",
        ) if value
    )
    if ficha:
        figure.text(MARGIN, y, ficha, color=INK_SOFT, fontsize=10)
        y -= 0.045

    # Las cuatro tarjetas de cabecera, repartidas a ancho igual sobre el
    # margen de la página.
    _add_rule(figure, y)
    y -= 0.05
    kpis = _cover_kpis(scenario, result, settings)
    ancho = (1 - 2 * MARGIN) / len(kpis)
    for i, (value, label) in enumerate(kpis):
        x = MARGIN + i * ancho
        figure.text(x, y, value, color=NAVY, fontsize=26, fontweight="semibold", va="top")
        figure.text(x, y - 0.075, label.upper(), color=INK_SOFT, fontsize=8.5,
                    fontweight="semibold")
    y -= 0.12
    _add_rule(figure, y)
    y -= 0.07

    best = max(result.strategies, key=lambda s: s.success_probability)
    figure.text(
        MARGIN, y,
        f"{best.name} sostiene el plan en el {best.success_probability:.1%} de los caminos",
        color=INK, fontsize=15, fontweight="semibold",
    )
    y -= 0.045
    detalle = " · ".join(
        f"{s.name}: {s.success_probability:.1%}" for s in result.strategies
    )
    figure.text(MARGIN, y, detalle, color=INK_SOFT, fontsize=9.5)
    y -= 0.05

    if options.notes.strip():
        y -= 0.02
        figure.text(MARGIN, y, "NOTAS", color=NAVY, fontsize=8.5, fontweight="semibold")
        y -= 0.032
        for line in _wrap(options.notes, 105):
            figure.text(MARGIN, y, line, color=INK, fontsize=9.5)
            y -= 0.028

    if options.include_disclaimer:
        for i, line in enumerate(_wrap(DISCLAIMER, 135)):
            figure.text(MARGIN, 0.10 - i * 0.022, line, color=INK_SOFT, fontsize=7.5)

    pdf.savefig(figure)


# El borde inferior deja sitio para tres cosas apiladas bajo el eje: la nota que
# el propio gráfico escribe como `xlabel`, la nota al pie de la página —que con
# la cita al anexo llega a dos líneas— y el pie impreso por `_new_page`.
CHART_RECT = (0.08, 0.19, 0.86, 0.67)
# La asignación de activos rotula cada barra con el nombre de su sub-clase
# —"Emerging Markets Sovereign Debt" y parecidos—, así que necesita un margen
# izquierdo mucho más ancho o el texto se sale de la hoja.
ALLOCATION_RECT = (0.26, 0.19, 0.68, 0.67)
# Línea base de la nota al pie: el bloque crece hacia **arriba** desde aquí, para
# que la última línea nunca invada el pie de página por mucho que se alargue.
FOOTNOTE_BASE = 0.060
FOOTNOTE_STEP = 0.021
# Cuánto hay que correr el titular de esa lámina, en fracción del ancho del eje,
# para que quede alineado con el margen de la página como en el resto.
ALLOCATION_TITLE_X = (MARGIN - ALLOCATION_RECT[0]) / ALLOCATION_RECT[2]


def _chart_page(pdf: PdfPages, options: ReportOptions, page_no: int, eyebrow: str,
                draw, footnote: str = "", rect=CHART_RECT) -> int:
    """Página de un gráfico.

    **La página no pone titular propio.** Cada gráfico ya abre con su frase
    descriptiva —es una regla del manual de marca y vive dentro de la función
    que lo dibuja—, así que agregar otro encima lo duplicaba palabra por
    palabra. La nota al pie extra sí se agrega: dice lo que el gráfico en
    pantalla deja al tooltip, que en papel no existe.
    """
    figure = _new_page(pdf, options, eyebrow, page_no)
    draw(_FigureCanvas(figure, rect=rect))
    # Por **debajo** de la nota que el propio gráfico escribe bajo su eje —el box
    # plot explica ahí sus percentiles—, no encima: a la misma altura las dos
    # líneas quedaban pegadas y con sangrías distintas. Se apila de abajo hacia
    # arriba: escrita hacia abajo desde un tope fijo, una nota de dos líneas se
    # montaba sobre la fecha del pie de página.
    _footnote(figure, footnote)
    pdf.savefig(figure)
    return page_no + 1


BASE_TABLE_FONTSIZE = 8.0
# Alto de una fila de tabla en fracción de figura, por punto de cuerpo. Vale
# 0.03124 al cuerpo base, que es el alto de fila de siempre.
#
# `_draw_table` **lo impone**, no lo hereda. matplotlib fija el alto de celda al
# crear la tabla, a partir del cuerpo de letra de los rcParams, y `set_fontsize`
# después solo cambia el texto: una tabla a 5.5 puntos conservaba filas de 8 y
# se salía por debajo de la hoja aunque la cuenta dijera que cabía. Impuesto
# aquí, el alto es proporcional al cuerpo y la cuenta es cierta por construcción.
ROW_HEIGHT_PER_POINT = 0.03124 / 8.0
# Alto útil de una tabla a página completa, bajo el titular y sobre la nota.
FULL_TABLE_HEIGHT = 0.72


def _rows_that_fit(height: float, fontsize: float) -> int:
    """Filas de datos que caben en un alto dado, descontando el encabezado.

    Antes era un número fijo, y por eso una tabla de treinta filas se salía de
    la hoja: veintiséis filas solo caben si el cuerpo de letra es pequeño, y el
    cuerpo lo decide el ancho de la columna, no el número de filas.
    """
    return max(1, int(height / (fontsize * ROW_HEIGHT_PER_POINT)) - 1)


ROWS_PER_PAGE = _rows_that_fit(FULL_TABLE_HEIGHT, BASE_TABLE_FONTSIZE)
# Por debajo de este cuerpo la tabla deja de ser legible impresa, y es preferible
# gastar una hoja por estrategia antes que apretarlas todas en una ilegible.
MIN_TABLE_FONTSIZE = 5.5
TABLE_GAP = 0.02
# Ancho medio de un glifo de Jost en fracción del cuerpo de letra, y aire a cada
# lado del texto de una celda, en pulgadas. De los dos sale el cuerpo con que una
# tabla cabe en un ancho dado, y con él el punto en que un tema deja de caber en
# una hoja y se reparte en una hoja por estrategia.
CHAR_WIDTH_EM = 0.52
CELL_PADDING_INCHES = 0.07


def _column_weights(columns: list[str], rows: list[list[str]]) -> list[float]:
    """Cuánto ancho pide cada columna, medido en caracteres de su texto más largo.

    Las columnas de una tabla de matplotlib son todas igual de anchas por
    defecto, y eso no sirve aquí: "Renta variable" y "Peso" no necesitan lo
    mismo, así que la columna angosta sobraba de espacio mientras la ancha
    escupía su texto encima de la vecina.
    """
    return [
        float(max([len(str(c))] + [len(str(row[i])) for row in rows if i < len(row)]))
        for i, c in enumerate(columns)
    ]


def _fit_fontsize(columns: list[str], rows: list[list[str]], width_inches: float,
                  ceiling: float = BASE_TABLE_FONTSIZE) -> float:
    """Cuerpo de letra con que la tabla cabe en ese ancho, sin pasar del techo.

    Puede devolver un valor por debajo de `MIN_TABLE_FONTSIZE`: quien llama
    decide entonces si aprieta o si reparte la tabla en más hojas. Decidirlo
    aquí escondería esa elección dentro de un cálculo de tipografía.
    """
    caracteres = sum(_column_weights(columns, rows))
    disponible = width_inches - CELL_PADDING_INCHES * len(columns)
    if caracteres <= 0 or disponible <= 0:
        return ceiling
    return min(ceiling, disponible * 72.0 / (caracteres * CHAR_WIDTH_EM))


def _footnote(figure: Figure, text: str):
    """Nota al pie de una página de tablas, apilada de abajo hacia arriba.

    Se corta por palabras: escrita de una sola tirada, una nota larga se salía
    por el borde derecho de la hoja sin que nada lo avisara.
    """
    if not text:
        return
    for i, line in enumerate(reversed(_wrap(text, 150))):
        figure.text(MARGIN, FOOTNOTE_BASE + i * FOOTNOTE_STEP, line,
                    color=INK_SOFT, fontsize=7.5)


def _draw_table(ax, columns: list[str], rows: list[list[str]], fontsize: float):
    """Estilo de tabla del informe: sin rejilla, regla bajo cada fila."""
    table = ax.table(cellText=rows, colLabels=columns, loc="upper center", cellLoc="right")
    table.auto_set_font_size(False)
    table.set_fontsize(fontsize)

    # Cada columna se lleva el ancho que pide su texto más largo, no una parte
    # igual: así la de sub-clase respira y la de peso no sobra de sitio. Y el
    # alto de fila se impone en vez de heredarlo, para que sea proporcional al
    # cuerpo de letra (ver `ROW_HEIGHT_PER_POINT`).
    pesos = _column_weights(columns, rows)
    total = sum(pesos) or 1.0
    alto_fila = fontsize * ROW_HEIGHT_PER_POINT / ax.get_position().height
    for (_, col), cell in table.get_celld().items():
        cell.set_width(pesos[col] / total)
        cell.set_height(alto_fila)

    for (row, col), cell in table.get_celld().items():
        cell.visible_edges = "B"
        cell.set_edgecolor(NEUTRAL)
        cell.set_linewidth(0.6)
        if col == 0:
            cell.set_text_props(ha="left")
        if row == 0:
            cell.set_text_props(color=NAVY, fontweight="semibold")
            cell.set_edgecolor(LEADER)
            cell.set_linewidth(1.2)
        else:
            cell.set_text_props(color=INK)
    return table


def _table_pages(pdf: PdfPages, options: ReportOptions, page_no: int, eyebrow: str,
                 lede: str, columns: list[str], rows: list[list[str]],
                 footnote: str = "", rows_per_page: int | None = None) -> int:
    """Una tabla sola, paginada. matplotlib no pagina solo: se corta a mano."""
    if not rows:
        rows = [["Sin datos"] + [""] * (len(columns) - 1)]
    rows_per_page = rows_per_page or ROWS_PER_PAGE

    chunks = [rows[i:i + rows_per_page] for i in range(0, len(rows), rows_per_page)]
    for i, chunk in enumerate(chunks):
        figure = _new_page(pdf, options, eyebrow, page_no)
        title = lede if i == 0 else f"{lede} (continúa)"
        figure.text(MARGIN, 0.90, title, color=INK, fontsize=14,
                    fontweight="semibold", va="top")

        ax = figure.add_axes((MARGIN, 0.10, 1 - 2 * MARGIN, 0.76))
        ax.axis("off")
        _draw_table(ax, columns, chunk, BASE_TABLE_FONTSIZE)

        _footnote(figure, footnote)
        pdf.savefig(figure)
        page_no += 1
    return page_no


def _topic_page(pdf: PdfPages, options: ReportOptions, page_no: int,
                tabla: "_AnnexTable", eyebrow: str = "Anexo",
                lede: str | None = None) -> int:
    """Un tema: **una tabla por estrategia**, lado a lado en la hoja.

    El cuerpo de letra sale del ancho que le toca a cada columna, no de un valor
    fijo: con dos estrategias las tablas quedan holgadas y con cuatro se aprietan.
    Si aun así el resultado no sería legible, el tema se reparte en una hoja por
    estrategia, que es lo que hacía el informe antes.

    Las estrategias más cortas simplemente terminan antes; no se rellenan con
    filas vacías porque el alto de celda de matplotlib no depende del número de
    filas, así que las tablas quedan alineadas igual.
    """
    bloques = tabla.per_strategy
    if not bloques:
        bloques = [("Sin datos", [])]
    if lede is None:
        lede = f"Tabla {tabla.number} · {tabla.kind}"

    ancho_util = 1 - 2 * MARGIN
    ancho = (ancho_util - TABLE_GAP * (len(bloques) - 1)) / len(bloques)
    fontsize = min(
        _fit_fontsize(tabla.columns, filas, ancho * PAGE_SIZE[0])
        for _, filas in bloques
    )

    if fontsize < MIN_TABLE_FONTSIZE:
        for nombre, filas in bloques:
            page_no = _table_pages(
                pdf, options, page_no, eyebrow, f"{lede} — {nombre}",
                tabla.columns, filas, tabla.footnote,
            )
        return page_no

    # Cuántas filas caben depende del cuerpo de letra, que a su vez depende del
    # ancho de columna: con más estrategias la letra encoge y caben más filas.
    por_pagina = _rows_that_fit(FULL_TABLE_HEIGHT, fontsize)
    paginas = max(1, -(-max(len(filas) for _, filas in bloques) // por_pagina))
    for p in range(paginas):
        figure = _new_page(pdf, options, eyebrow, page_no)
        figure.text(MARGIN, 0.90, lede if p == 0 else f"{lede} (continúa)",
                    color=INK, fontsize=14, fontweight="semibold", va="top")

        for i, (nombre, filas) in enumerate(bloques):
            x = MARGIN + i * (ancho + TABLE_GAP)
            _swatch(figure, x, 0.845, series_color(i))
            figure.text(x + 0.016, 0.845, nombre.upper(), color=NAVY, fontsize=8.5,
                        fontweight="semibold")
            chunk = filas[p * por_pagina:(p + 1) * por_pagina]
            if not chunk:
                figure.text(x, 0.80, "Sin datos", color=INK_SOFT, fontsize=8)
                continue
            ax = figure.add_axes((x, 0.10, ancho, 0.72))
            ax.axis("off")
            _draw_table(ax, tabla.columns, chunk, fontsize)

        _footnote(figure, tabla.footnote)
        pdf.savefig(figure)
        page_no += 1
    return page_no


# Geometría de la hoja de anexo de una estrategia. El contenido empieza por
# debajo del nombre de la estrategia y termina por encima de la nota al pie.
ANNEX_TOP = 0.84
ANNEX_BOTTOM = 0.10
ANNEX_TITLE_DROP = 0.035  # lo que baja el rótulo de una tabla antes de la tabla
ANNEX_BLOCK_GAP = 0.030   # aire entre una tabla y el rótulo de la siguiente
# Por debajo de esto, lo que cabe en la columna es un encabezado y un par de
# filas: no es una tabla, es un cabo suelto, y conviene empezar en la otra.
MIN_ROWS_IN_COLUMN = 4


def _annex_layout(bloques: list["_AnnexBlock"], row_height: float
                  ) -> list[list[tuple[int, float, "_AnnexBlock", list[list[str]], bool]]]:
    """Reparte las tablas en dos columnas, por su alto real.

    No es una retícula de celdas iguales: una tabla de cuatro filas y una de
    quince no ocupan lo mismo, y repartir la hoja en cuartos dejaba a una
    desbordada sobre la de abajo y a la otra con media hoja en blanco. Cada
    tabla se coloca en la columna que tenga más sitio libre y baja el cursor de
    esa columna exactamente lo que mide.

    Devuelve una lista de hojas; cada hoja es una lista de
    `(columna, tope, bloque, filas, continúa)`.
    """
    hojas: list[list[tuple[int, float, _AnnexBlock, list[list[str]], bool]]] = [[]]
    cursores = [ANNEX_TOP, ANNEX_TOP]

    for bloque in bloques:
        filas = bloque.rows or [["Sin datos"] + [""] * (len(bloque.columns) - 1)]
        i = 0
        while i < len(filas):
            columna = 0 if cursores[0] >= cursores[1] else 1
            sitio = cursores[columna] - ANNEX_BOTTOM - ANNEX_TITLE_DROP
            caben = int(sitio / row_height) - 1  # menos la fila de encabezado
            if caben < MIN_ROWS_IN_COLUMN:
                if not hojas[-1]:
                    # Ni en una hoja vacía cabe: se fuerza aquí antes que dar
                    # vueltas abriendo hojas que tampoco servirían.
                    caben = max(1, caben)
                else:
                    hojas.append([])
                    cursores = [ANNEX_TOP, ANNEX_TOP]
                    continue

            trozo = filas[i:i + caben]
            tope = cursores[columna]
            hojas[-1].append((columna, tope, bloque, trozo, i > 0))
            cursores[columna] = (
                tope - ANNEX_TITLE_DROP - (len(trozo) + 1) * row_height - ANNEX_BLOCK_GAP
            )
            i += caben

    return hojas


def _strategy_annex_page(pdf: PdfPages, options: ReportOptions, page_no: int,
                         anexo: "_StrategyAnnex", footnote: str = "") -> int:
    """El anexo de una estrategia: **todas sus tablas en una hoja**.

    Las tablas se reparten en dos columnas. Es la disposición que cabe: a una
    sola columna la asignación se comería la hoja entera y la proyección se
    iría a la siguiente, que es justo lo que esta página viene a evitar.

    Si aun así no caben todas, las que sobran siguen en otra hoja de la misma
    estrategia. Nunca se mezcla con el anexo de otra: la ficha de una estrategia
    se arranca del informe y se entrega, y para eso tiene que ser suya entera.
    """
    bloques = anexo.blocks
    if not bloques:
        bloques = [_AnnexBlock("Sin datos", ["Indicador", "Valor"], [])]

    ancho = (1 - 2 * MARGIN - TABLE_GAP) / 2

    # El cuerpo de letra lo fija la tabla más exigente de la hoja: dos tablas de
    # la misma hoja con cuerpos distintos se leen como si una fuera menos
    # importante que la otra, y aquí todas son la misma ficha.
    fontsize = max(
        MIN_TABLE_FONTSIZE,
        min(_fit_fontsize(b.columns, b.rows, ancho * PAGE_SIZE[0]) for b in bloques),
    )
    row_height = fontsize * ROW_HEIGHT_PER_POINT

    titulo = f"Anexo · Hoja {anexo.number} · {anexo.name}"
    for p, hoja in enumerate(_annex_layout(bloques, row_height)):
        figure = _new_page(pdf, options, "Anexo", page_no)
        _swatch(figure, MARGIN, 0.883, series_color(anexo.index))
        figure.text(MARGIN + 0.018, 0.90, titulo if p == 0 else f"{titulo} (continúa)",
                    color=INK, fontsize=14, fontweight="semibold", va="top")

        for columna, tope, bloque, filas, continua in hoja:
            x = MARGIN + columna * (ancho + TABLE_GAP)
            etiqueta = f"{bloque.kind} (continúa)" if continua else bloque.kind
            figure.text(x, tope, etiqueta.upper(), color=NAVY, fontsize=8,
                        fontweight="semibold", va="top")
            alto = (len(filas) + 1) * row_height
            ax = figure.add_axes((x, tope - ANNEX_TITLE_DROP - alto, ancho, alto))
            ax.axis("off")
            _draw_table(ax, bloque.columns, filas, fontsize)

        _footnote(figure, footnote)
        pdf.savefig(figure)
        page_no += 1
    return page_no


# Alto máximo que la tabla de asignación le puede quitar a su gráfica. Más que
# esto y la gráfica —que es lo que se mira primero— queda de tira.
ALLOCATION_TABLE_HEIGHT = 0.34
ALLOCATION_LABEL_DROP = 0.028


def _allocation_page(pdf: PdfPages, options: ReportOptions, page_no: int,
                     scenario: Scenario, footnote: str = "") -> int:
    """La asignación de activos: la gráfica y, **debajo, su tabla**.

    La tabla no va al anexo. Es el detalle exacto de la gráfica que se tiene
    delante —qué sub-clase pesa cuánto en cada estrategia—, y mandarla al final
    del documento obligaba a pasar diez hojas para leer la cifra de la barra que
    se está mirando.

    La tabla se lleva el alto que pide, hasta un tope; lo que sobre continúa en
    una hoja aparte, porque la gráfica no puede quedar reducida a una tira.
    """
    columnas = ["Clase de activo", "Sub-clase", "Peso"]
    por_estrategia: dict[str, list[list[str]]] = {}
    for row in allocation_table_rows(scenario, options.resolver):
        por_estrategia.setdefault(row["Estrategia"], []).append(
            [row[c] for c in columnas]
        )
    bloques = [
        (s.name, por_estrategia[s.name])
        for s in scenario.strategies if por_estrategia.get(s.name)
    ]

    def dibujar(canvas):
        draw_allocation_chart(canvas, scenario, options.resolver, ALLOCATION_TITLE_X)

    if not bloques:
        return _chart_page(pdf, options, page_no, "Asignación de activos",
                           dibujar, footnote, rect=ALLOCATION_RECT)

    ancho = (1 - 2 * MARGIN - TABLE_GAP * (len(bloques) - 1)) / len(bloques)
    por_ancho = min(
        _fit_fontsize(columnas, filas, ancho * PAGE_SIZE[0]) for _, filas in bloques
    )
    # El cuerpo también sale del **alto**: si la tabla se pasa por una o dos
    # filas, encoge un punto y entra entera. Partirla gastaba una hoja de
    # continuación para una fila suelta, que es peor negocio que medio punto
    # menos de letra.
    filas_max = max(len(filas) for _, filas in bloques)
    por_alto = ALLOCATION_TABLE_HEIGHT / ((filas_max + 1) * ROW_HEIGHT_PER_POINT)
    fontsize = max(MIN_TABLE_FONTSIZE, min(por_ancho, por_alto))
    row_height = fontsize * ROW_HEIGHT_PER_POINT

    caben = _rows_that_fit(ALLOCATION_TABLE_HEIGHT, fontsize)
    visibles = min(max(len(filas) for _, filas in bloques), caben)
    alto_tabla = (visibles + 1) * row_height
    tope_tabla = ANNEX_BOTTOM + alto_tabla

    figure = _new_page(pdf, options, "Asignación de activos", page_no)
    base_grafica = tope_tabla + ALLOCATION_LABEL_DROP + 0.045
    x, _, ancho_grafica, _ = ALLOCATION_RECT
    tope_grafica = ALLOCATION_RECT[1] + ALLOCATION_RECT[3]
    dibujar(_FigureCanvas(
        figure, rect=(x, base_grafica, ancho_grafica, tope_grafica - base_grafica)
    ))

    for i, (nombre, filas) in enumerate(bloques):
        columna_x = MARGIN + i * (ancho + TABLE_GAP)
        _swatch(figure, columna_x, tope_tabla + ALLOCATION_LABEL_DROP - 0.004,
                series_color(i))
        figure.text(columna_x + 0.016, tope_tabla + ALLOCATION_LABEL_DROP,
                    nombre.upper(), color=NAVY, fontsize=8, fontweight="semibold",
                    va="top")
        ax = figure.add_axes((columna_x, ANNEX_BOTTOM, ancho, alto_tabla))
        ax.axis("off")
        _draw_table(ax, columnas, filas[:visibles], fontsize)

    _footnote(figure, footnote)
    pdf.savefig(figure)
    page_no += 1

    # Lo que no cupo debajo de la gráfica sigue en su propia hoja, con la misma
    # disposición de una tabla por estrategia.
    resto = [(nombre, filas[visibles:]) for nombre, filas in bloques]
    if any(filas for _, filas in resto):
        page_no = _topic_page(
            pdf, options, page_no,
            _AnnexTable(number=0, kind=ALLOCATION, columns=columnas,
                        per_strategy=[(n, f) for n, f in resto if f],
                        footnote=footnote),
            eyebrow="Asignación de activos",
            lede="Asignación de activos (continúa)",
        )
    return page_no


# ----------------------------------------------------------------------
# Texto en columnas
#
# "Con qué se construyó esta proyección" y "Supuestos declarados por el
# analista" van en la **misma página**, en dos columnas. Son las dos mitades de
# una sola pregunta —de dónde salen estos números— y separarlas en dos hojas
# obligaba a pasar página para contestarla entera.
#
# Cada columna lleva su propio flujo: si una se pasa de largo, continúa en la
# columna equivalente de la página siguiente en vez de invadir a su vecina. Por
# eso las figuras se crean a demanda y se guardan todas al final: la columna
# izquierda puede necesitar una página más que la derecha, así que las dos tienen
# que poder seguir escribiendo sobre páginas ya empezadas.

CONTENT_TOP = 0.90
CONTENT_BOTTOM = 0.10
COLUMN_LEFT_X = MARGIN
COLUMN_RIGHT_X = 0.53
# Ancho de corte del texto. En una columna cabe algo menos de la mitad que a
# página completa; los dos valores están calibrados por debajo del máximo
# teórico, porque el ancho real depende del glifo y no del número de caracteres.
COLUMN_WRAP = 62
SINGLE_WRAP = 130


LINE_STEP = 0.024
HEADING_STEP = 0.032


class _ColumnFlow:
    """Páginas de texto creadas a demanda y guardadas al final."""

    def __init__(self, pdf: PdfPages, options: ReportOptions, eyebrow: str, page_no: int):
        self._pdf = pdf
        self._options = options
        self._eyebrow = eyebrow
        self._first_page = page_no
        self._figures: list[Figure] = []

    def figure(self, index: int) -> Figure:
        while len(self._figures) <= index:
            self._figures.append(
                _new_page(
                    self._pdf, self._options, self._eyebrow,
                    self._first_page + len(self._figures),
                )
            )
        return self._figures[index]

    def new_page_index(self) -> int:
        """Índice de una hoja nueva, más allá de todas las ya empezadas."""
        index = len(self._figures)
        self.figure(index)
        return index

    def flush(self) -> int:
        """Guarda las páginas en orden y devuelve el número de la siguiente."""
        self.figure(0)  # una sección vacía sigue mereciendo su hoja
        for figure in self._figures:
            self._pdf.savefig(figure)
        return self._first_page + len(self._figures)


class _Column:
    """Cursor que escribe recorriendo una lista de regiones.

    Una región es un hueco de una página: `(hoja, x, tope)`. Encadenarlas es lo
    que permite que los supuestos del caso empiecen en la columna izquierda y,
    cuando se pasan de largo, **sigan en el hueco que dejó libre la columna
    derecha** en vez de abrir una hoja nueva con cuatro líneas sueltas.

    Agotadas las regiones previstas, se abren hojas nuevas repitiendo `tail`,
    que es el patrón de columnas de una página en blanco.
    """

    def __init__(self, flow: _ColumnFlow, wrap: int,
                 regions: list[tuple[int, float, float]],
                 tail: list[tuple[float, float]] | None = None):
        self._flow = flow
        self.wrap = wrap
        self._regions = list(regions)
        self._tail = list(tail) if tail else [(regions[0][1], CONTENT_TOP)]
        self._index = 0
        self._tail_page = 0
        self.page, self.x, self.y = self._regions[0]

    def _advance(self):
        self._index += 1
        if self._index < len(self._regions):
            self.page, self.x, self.y = self._regions[self._index]
            return
        k = self._index - len(self._regions)
        if k % len(self._tail) == 0:
            self._tail_page = self._flow.new_page_index()
        self.page = self._tail_page
        self.x, self.y = self._tail[k % len(self._tail)]

    def _room(self, height: float):
        """Cambia de región si el bloque no cabe entero.

        Un bloque más alto que una región entera no cabe en ninguna parte:
        cambiar de región solo lo movería, así que se escribe donde esté.
        """
        if height <= CONTENT_TOP - CONTENT_BOTTOM and self.y - height < CONTENT_BOTTOM:
            self._advance()

    def reserve(self, height: float):
        """Pide sitio para un bloque que no se debe partir."""
        self._room(height)

    def title(self, text: str):
        self._room(0.075)
        figure = self._flow.figure(self.page)
        figure.text(self.x, self.y, text, color=INK, fontsize=13,
                    fontweight="semibold", va="top")
        self.y -= 0.075

    def heading(self, text: str, swatch: str | None = None, *, auto_break: bool = True):
        if auto_break:
            self._room(HEADING_STEP * 2)
        figure = self._flow.figure(self.page)
        if swatch is None:
            figure.text(self.x, self.y, text, color=NAVY, fontsize=8.5,
                        fontweight="semibold")
        else:
            # La viñeta de color es un rectángulo, no un carácter: Jost no trae
            # el glifo "●" y matplotlib lo dibujaría como un cuadro vacío.
            _swatch(figure, self.x, self.y, swatch)
            figure.text(self.x + 0.018, self.y, text, color=NAVY, fontsize=9,
                        fontweight="semibold")
        self.y -= HEADING_STEP

    def write(self, text: str, *, color=INK, fontsize: float = 8.5,
              weight: str = "normal", indent: float = 0.01,
              step: float = LINE_STEP, auto_break: bool = True,
              lines: list[str] | None = None):
        if lines is None:
            lines = _wrap(text, self.wrap)
        if auto_break:
            self._room(len(lines) * step)
        figure = self._flow.figure(self.page)
        for line in lines:
            figure.text(self.x + indent, self.y, line, color=color,
                        fontsize=fontsize, fontweight=weight)
            self.y -= step

    def pair(self, label: str, value: str, label_width: float = 0.13):
        self._room(0.028)
        figure = self._flow.figure(self.page)
        figure.text(self.x + 0.01, self.y, label, color=INK_SOFT, fontsize=9)
        figure.text(self.x + 0.01 + label_width, self.y, value, color=INK, fontsize=9.5)
        self.y -= 0.028

    def gap(self, height: float = 0.014):
        self.y -= height


def _flow_text(flow) -> str:
    """Una línea que describe el flujo tal como se configuró."""
    if flow.is_percentage:
        return (
            f"{flow.kind.value.capitalize()} · {flow.name}: "
            f"{flow.amount:.2%} del patrimonio al año, años "
            f"{flow.start_year}–{flow.end_year}, recalculado cada año sobre "
            "el patrimonio vigente"
        )
    return (
        f"{flow.kind.value.capitalize()} · {flow.name}: "
        f"{format_money(flow.amount)} al año, años "
        f"{flow.start_year}–{flow.end_year}"
        f"{', indexado a inflación' if flow.inflation_indexed else ''}"
        f"{f', crecimiento real {flow.growth:.2%}' if flow.growth else ''}"
    )


def _strategy_paragraphs(strategy, scenario: Scenario,
                         options: ReportOptions) -> list[tuple[str, dict]]:
    """Los párrafos de una estrategia, con su estilo, en orden de lectura."""
    # Primero la lectura agrupada, que es la que se mira en una reunión, y
    # debajo el detalle por sub-clase, que es el que hace falta para
    # reproducir el caso.
    resumen = group_summary(strategy.weights, options.resolver)
    pesos = " · ".join(
        f"{name} {weight:.1%}" for name, weight in strategy.weights.items()
    ) or "sin pesos definidos"
    capital = (
        format_money(strategy.initial_value) if strategy.has_own_initial
        else f"{format_money(scenario.initial_value)} (del escenario)"
    )

    parrafos: list[tuple[str, dict]] = [
        (f"Por clase de activo: {resumen}", {"weight": "semibold"}),
        (f"Detalle por sub-clase: {pesos}", {}),
        (f"Capital inicial: {capital}", {}),
    ]

    if strategy.cashflows:
        parrafos.extend((_flow_text(f), {}) for f in strategy.cashflows)
    else:
        parrafos.append(("Sin flujos.", {"color": INK_SOFT}))

    if strategy.has_loan:
        loan = strategy.loan
        tasa = (
            f"tasa fija {loan.rate:.2%}" if loan.rate_mode.value == "fija"
            else f"caja + {loan.spread:.2%}"
        )
        ltv = (
            f", LTV máx. {loan.max_ltv:.0%} y objetivo {loan.effective_target_ltv:.0%} "
            "tras la llamada a margen"
            if loan.max_ltv is not None else ", sin control de LTV"
        )
        parrafos.append((
            f"Crédito · {loan.name}: {format_money(loan.principal)} en el año "
            f"{loan.start_year}, plazo {loan.term_years} años, {tasa}, intereses "
            f"{loan.interest_mode.value}, amortización {loan.amortization.value}{ltv}",
            {},
        ))
    else:
        parrafos.append(("Sin apalancamiento.", {"color": INK_SOFT}))

    return parrafos


def _write_case_inputs(col: _Column, scenario: Scenario, options: ReportOptions):
    """Los inputs del caso, para que el informe sea reproducible sin el .gbp.json."""
    col.title("Con qué se construyó esta proyección")
    col.heading("ESCENARIO")
    for label, value in (
        ("Capital inicial", format_money(scenario.initial_value)),
        ("Horizonte", f"{scenario.horizon} años"),
        ("Inflación anual", f"{scenario.inflation:.2%}"),
    ):
        col.pair(label, value)

    for i, strategy in enumerate(scenario.strategies):
        # La estrategia se mide entera y se pide sitio de una vez: partida entre
        # dos columnas, su titular quedaba en una y sus flujos en la otra, y no
        # se veía de quién eran los números.
        parrafos = [
            (_wrap(texto, col.wrap), estilo)
            for texto, estilo in _strategy_paragraphs(strategy, scenario, options)
        ]
        alto = HEADING_STEP + sum(len(lineas) for lineas, _ in parrafos) * LINE_STEP
        col.gap(0.016)
        col.reserve(alto)

        col.heading(strategy.name.upper(), swatch=series_color(i), auto_break=False)
        for lineas, estilo in parrafos:
            col.write("", lines=lineas, auto_break=False, **estilo)


def _write_custom_assets(col: _Column, propios: list):
    """Activos propios.

    No es opcional cuando los hay: un supuesto que fijó el analista y que no
    está publicado por nadie tiene que quedar escrito en el documento que ve el
    cliente, o la proyección no se puede auditar.
    """
    col.title("Supuestos declarados por el analista")
    col.write(
        "Estas clases de activo no están en el LTCMA: sus supuestos los fijó quien "
        "preparó este informe. Sus correlaciones se derivan del promedio de la "
        "clase de activo indicada, salvo que el activo esté anclado a uno solo "
        "de la librería, como se indica abajo. Los valores están en dólares.",
        color=INK_SOFT, indent=0.0,
    )
    col.gap(0.02)
    for asset in propios:
        col.heading(asset.name.upper(), swatch=NAVY)
        correlacion = (
            f"anclada a '{asset.correlation_source}'" if asset.correlation_source
            else f"promedio de {asset.asset_class}"
        )
        col.write(
            f"Clase: {asset.asset_class} · retorno compuesto {asset.compound_return:.2%}"
            f" · volatilidad {asset.volatility:.2%} · yield {asset.yield_:.2%}"
            f" · correlación: {correlacion}"
        )
        if asset.notes:
            col.write(f"Notas: {asset.notes}", color=INK_SOFT)
        col.gap(0.014)


def _inputs_pages(pdf: PdfPages, options: ReportOptions, page_no: int,
                  scenario: Scenario) -> int:
    """Supuestos del caso y activos propios, en dos columnas de la misma página.

    Sin activos propios no hay segunda columna, y el texto usa la página entera:
    una columna sola de media hoja dejaría la otra mitad en blanco.
    """
    propios = _custom_used(scenario, options)
    flow = _ColumnFlow(pdf, options, "Supuestos del caso", page_no)

    if not propios:
        _write_case_inputs(
            _Column(flow, SINGLE_WRAP, [(0, COLUMN_LEFT_X, CONTENT_TOP)]),
            scenario, options,
        )
        return flow.flush()

    # Los activos propios se escriben **primero** aunque vayan a la derecha: son
    # pocas líneas y de largo conocido, así que dejan medido el hueco que queda
    # libre bajo ellos, y los supuestos del caso —que sí se pasan de largo—
    # pueden continuar ahí en vez de abrir otra hoja.
    derecha = _Column(flow, COLUMN_WRAP, [(0, COLUMN_RIGHT_X, CONTENT_TOP)])
    _write_custom_assets(derecha, propios)

    regiones = [(0, COLUMN_LEFT_X, CONTENT_TOP)]
    sobra = derecha.y - 0.03
    if sobra - CONTENT_BOTTOM > 0.12:  # menos que eso es una tira, no una columna
        regiones.append((derecha.page, COLUMN_RIGHT_X, sobra))

    _write_case_inputs(
        _Column(flow, COLUMN_WRAP, regiones,
                tail=[(COLUMN_LEFT_X, CONTENT_TOP), (COLUMN_RIGHT_X, CONTENT_TOP)]),
        scenario, options,
    )
    return flow.flush()


def _custom_used(scenario: Scenario, options: ReportOptions) -> list:
    """Activos propios que el caso usa, para documentarlos en el informe."""
    if options.cmas is None:
        return []
    usados = []
    for name in scenario.asset_names:
        try:
            asset = options.cmas.by_name(name)
        except KeyError:
            continue
        if asset.is_custom:
            usados.append(asset)
    return usados


# ----------------------------------------------------------------------
@dataclass
class _AnnexTable:
    """Un **tema** del anexo, ya numerado, con una tabla por estrategia.

    El anexo se arma **antes** de escribir ninguna página porque las gráficas
    del cuerpo citan sus números. Sin reservarlos primero habría que escribir el
    PDF en dos pasadas.

    El número es del tema, no de cada estrategia: una gráfica compara todas las
    estrategias y su detalle vive en una sola hoja, así que la cita es una sola
    referencia.
    """

    number: int
    kind: str
    columns: list[str]
    per_strategy: list[tuple[str, list[list[str]]]]
    footnote: str = ""

    @property
    def title(self) -> str:
        return self.kind

    @property
    def strategies(self) -> list[str]:
        return [name for name, _ in self.per_strategy]


# Temas del anexo, en el orden en que se imprimen. El orden importa: sigue al
# del cuerpo, así que quien lee una gráfica encuentra su tabla antes que la de
# la gráfica siguiente.
ALLOCATION = "Asignación de activos"
DISTRIBUTION = "Patrimonio neto proyectado · valores nominales"
DISTRIBUTION_REAL = "Patrimonio neto proyectado · moneda de hoy"
SUMMARY = "Supuestos resumen"
DEBT = "Llamadas a margen y liquidación forzada"

DISTRIBUTION_COLUMNS = [
    "Año", "p10", "p25", "Mediana", "p75", "p90", "Media", "Desv. est.",
]

SUMMARY_INDICATORS = [
    ("Probabilidad de éxito", lambda s, real: f"{s.success_probability:.1%}"),
    ("Retorno compuesto de largo plazo",
     lambda s, real: f"{s.summary.compound_return:.2%}"),
    ("Volatilidad de largo plazo", lambda s, real: f"{s.summary.volatility:.2%}"),
    ("Yield de largo plazo", lambda s, real: f"{s.summary.yield_:.2%}"),
    ("Sharpe de largo plazo", lambda s, real: f"{s.summary.sharpe_ratio:.2f}"),
    ("Patrimonio mediano final",
     lambda s, real: format_money(float(np.median(s.terminal_values(real))))),
    ("CVaR 5% al final", lambda s, real: format_money(s.cvar(s.horizon, 0.05, real))),
    ("Cambio del patrimonio en el último año",
     lambda s, real: f"{s.last_year_change(real):.2%}"),
]


def _summary_table(options: ReportOptions, result: SimulationResult,
                   real: bool, moneda: str) -> _AnnexTable | None:
    """Los supuestos resumen, que van **en el cuerpo** y no en el anexo.

    Es la única tabla que no es material de consulta: dice con qué retorno,
    volatilidad y Sharpe se generó la nube de trayectorias, así que se lee justo
    antes de mirarla. En el anexo obligaba a ir al final del documento para
    entender la gráfica que se tenía delante.

    Reusa `_AnnexTable` porque comparte maquetación —una tabla por estrategia,
    lado a lado— pero va sin número: no se cita, se lee donde está.
    """
    if not options.include_summary:
        return None
    return _AnnexTable(
        number=0,
        kind=SUMMARY,
        columns=["Indicador", "Valor"],
        per_strategy=[
            (s.name, [[label, getter(s, real)] for label, getter in SUMMARY_INDICATORS])
            for s in result.strategies
        ],
        footnote=(
            "El Sharpe usa como tasa libre de riesgo el retorno de la clase de caja. "
            "El retorno compuesto ya lleva descontado el arrastre de la volatilidad. "
            "El cambio del último año no es rentabilidad: es la variación del "
            f"patrimonio neto con aportes y retiros incluidos. {moneda}"
        ),
    )


FLOWS = "Flujos y valor de portafolio por año"

FLOW_COLUMNS = [
    "Año", "Flujos netos", "Flujos netos acumulados",
    "Valor portafolio", "Valor portafolio (moneda de hoy)",
]


@dataclass
class _AnnexBlock:
    """Una tabla del anexo de una estrategia, con su rótulo."""

    kind: str
    columns: list[str]
    rows: list[list[str]]


@dataclass
class _StrategyAnnex:
    """El anexo de **una** estrategia: todas sus tablas en una hoja.

    El anexo se organizaba por tema, con la tabla de cada estrategia al lado de
    la de las demás. Leerlo así obliga a recorrer el anexo entero para armar la
    ficha de una estrategia: su asignación en una hoja, su proyección en otra,
    su deuda en una tercera. Organizado por estrategia, esa ficha es una sola
    página y se puede arrancar y entregar.
    """

    number: int
    name: str
    index: int
    blocks: list[_AnnexBlock]

    def block(self, kind: str) -> _AnnexBlock | None:
        for block in self.blocks:
            if block.kind == kind:
                return block
        return None


def _build_annex(
    options: ReportOptions,
    scenario: Scenario,
    result: SimulationResult,
    years: list[int],
    con_deuda: bool,
) -> list[_StrategyAnnex]:
    """El anexo: una entrada por estrategia, con todas sus tablas.

    Solo entra la tabla de una sección que el usuario haya pedido: un anexo con
    el detalle de una gráfica que no está en el documento no lo entendería nadie.
    """
    distribuciones: dict[tuple[str, bool], list[list[str]]] = {}
    if options.include_distribution:
        # Las dos unidades, siempre: la nominal es la que verá en su extracto y
        # la real es la que dice qué podrá comprar. Elegir una escondía la otra.
        for es_real in (False, True):
            for row in distribution_table_rows(result, years, es_real):
                distribuciones.setdefault((row["Estrategia"], es_real), []).append(
                    [str(row[c]) for c in DISTRIBUTION_COLUMNS]
                )

    anexos: list[_StrategyAnnex] = []
    for i, strategy in enumerate(result.strategies):
        bloques: list[_AnnexBlock] = []

        # La asignación **no** entra: vive debajo de su propia gráfica, en el
        # cuerpo, que es donde hace falta leerla.
        for kind, es_real in ((DISTRIBUTION, False), (DISTRIBUTION_REAL, True)):
            filas = distribuciones.get((strategy.name, es_real))
            if filas:
                bloques.append(_AnnexBlock(kind, DISTRIBUTION_COLUMNS, filas))

        if con_deuda:
            bloques.append(_AnnexBlock(
                DEBT, ["Indicador", "Valor"],
                [
                    ["Probabilidad de llamada a margen",
                     f"{strategy.margin_call_probability:.1%}"],
                    ["Llamadas promedio por camino",
                     f"{strategy.margin_calls.mean():.2f}"
                     if strategy.margin_calls.size else "0.00"],
                    ["Liquidación forzada máxima",
                     format_money(float(strategy.forced_sales.max()))
                     if strategy.forced_sales.size else "0"],
                ],
            ))

        # Sin ninguna sección pedida no hay hoja que escribir: una página con el
        # nombre de la estrategia y nada debajo no es un anexo.
        if bloques:
            anexos.append(_StrategyAnnex(
                number=len(anexos) + 1, name=strategy.name, index=i, blocks=bloques,
            ))

    return anexos


def _flows_table(result: SimulationResult) -> _AnnexTable | None:
    """Flujos netos y valor de portafolio año por año, una tabla por estrategia.

    Va en el cuerpo, junto a las demás tablas de la estrategia, y no en el
    anexo: tiene una fila por año del horizonte —treinta, no cuatro— pero es
    la que responde la pregunta que sigue a la de asignación y proyección, que
    es cuánto queda cada año y de dónde sale ese cambio.
    """
    bloques: list[tuple[str, list[list[str]]]] = []
    for strategy in result.strategies:
        serie = strategy.flow_history()
        if not (serie["aportes"].any() or serie["retiros"].any()):
            continue
        valores = strategy.flow_value_series()
        bloques.append((
            strategy.name,
            [
                [
                    str(year),
                    format_money(float(valores["neto"][year - 1])),
                    format_money(float(valores["acumulado"][year - 1])),
                    format_money(float(valores["valor_nominal"][year - 1])),
                    format_money(float(valores["valor_real"][year - 1])),
                ]
                for year in range(1, strategy.horizon + 1)
            ],
        ))

    if not bloques:
        return None
    return _AnnexTable(
        number=0, kind=FLOWS, columns=FLOW_COLUMNS, per_strategy=bloques,
        footnote=(
            "Flujos netos: aportes menos retiros, medianos sobre los caminos "
            "simulados. Valor portafolio: patrimonio neto mediano al cierre de cada "
            "año, en valores nominales y en moneda de hoy descontada a la inflación "
            "del escenario."
        ),
    )


def _cite(annex: list[_StrategyAnnex], kind: str, extra: str = "") -> str:
    """Remite a las hojas del anexo que traen el detalle de un tema.

    El anexo va por estrategia, así que el detalle de una gráfica —que compara
    todas— está repartido entre sus hojas, una por estrategia.
    """
    numeros = [a.number for a in annex if a.block(kind) is not None]
    if not numeros:
        return extra
    if len(numeros) == 1:
        cita = f"Detalle en el Anexo · Hoja {numeros[0]}."
    else:
        cita = f"Detalle en el Anexo · Hojas {numeros[0]} a {numeros[-1]}."
    return f"{extra} {cita}".strip()


def build_report(
    path: str | Path,
    options: ReportOptions,
    scenario: Scenario,
    result: SimulationResult,
    settings: SimulationSettings,
) -> Path:
    """Escribe el PDF y devuelve la ruta.

    Orden del documento: portada, supuestos del caso, asignación, supuestos
    resumen, proyección, deuda y anexo. **La única tabla del cuerpo son los
    supuestos resumen**, justo antes de la proyección que explican; las demás
    viven en el anexo, un tema por hoja con la tabla de cada estrategia al lado
    de la de las demás, y cada gráfica cita la suya.

    El anexo va **por estrategia**: una hoja con su asignación, su proyección en
    las dos unidades y su deuda, en vez de una hoja por tema con todas las
    estrategias. Detrás van los ingresos y retiros año por año, que por su largo
    —una fila por año del horizonte— no caben en esa retícula.
    """
    apply_matplotlib_style()
    path = Path(path)
    # Las cifras en dinero de los supuestos resumen son nominales. La unidad ya
    # no se configura: la distribución se imprime en las dos y el resumen usa la
    # que se lee en un extracto.
    real = False
    years = settings.milestones_within(scenario.horizon)
    moneda = "Valores nominales."
    con_deuda = options.include_debt and any(s.debt.max() > 0 for s in result.strategies)

    annex = _build_annex(options, scenario, result, years, con_deuda)
    flows = _flows_table(result) if options.include_flows else None

    with PdfPages(path) as pdf:
        _cover(pdf, options, scenario, result, settings)
        page = 2

        if options.include_inputs:
            page = _inputs_pages(pdf, options, page, scenario)

        if options.include_allocation:
            page = _allocation_page(
                pdf, options, page, scenario,
                "Los pesos están normalizados sobre el total cargado de cada "
                "estrategia. La agrupación en clases es una vista de lectura: los "
                "pesos se cargan siempre por sub-clase.",
            )

        # Los supuestos resumen van **antes** de la proyección: dicen con qué
        # retorno, volatilidad y Sharpe se generó la nube que viene a
        # continuación, y es lo que hay que tener en la cabeza al mirarla.
        resumen = _summary_table(options, result, real, moneda)
        if resumen is not None:
            page = _topic_page(
                pdf, options, page, resumen,
                eyebrow="Supuestos resumen", lede="Con qué se proyecta cada estrategia",
            )

        if options.include_distribution:
            # La misma gráfica dos veces, en las dos unidades. Van seguidas y no
            # en extremos del documento: la comparación entre nominal y real es
            # justo lo que hay que poder hacer de un vistazo.
            for kind, es_real in ((DISTRIBUTION, False), (DISTRIBUTION_REAL, True)):
                unidad = (
                    "Valores en moneda de hoy, descontados a la inflación del escenario."
                    if es_real else "Valores nominales."
                )
                page = _chart_page(
                    pdf, options, page,
                    f"Distribución · {'moneda de hoy' if es_real else 'nominal'}",
                    lambda canvas, r=es_real: draw_box_chart(canvas, result, years, r),
                    _cite(
                        annex, kind,
                        "Percentiles calculados sobre los caminos simulados, sin "
                        f"suponer forma de distribución. {unidad}",
                    ),
                )

        if con_deuda:
            page = _chart_page(
                pdf, options, page, "Deuda",
                lambda canvas: draw_debt_chart(canvas, result),
                _cite(
                    annex, DEBT,
                    "Línea: mediana. Banda: percentil 5 al 95.",
                ),
            )

        if flows is not None:
            page = _topic_page(
                pdf, options, page, flows,
                eyebrow="Flujos y valor de portafolio",
                lede="Flujos netos y patrimonio mediano, año por año",
            )

        for anexo in annex:
            page = _strategy_annex_page(
                pdf, options, page, anexo,
                footnote=(
                    "Percentiles calculados sobre los caminos simulados, sin suponer "
                    "forma de distribución. La asignación de esta estrategia va con "
                    "su gráfica, en el cuerpo del informe."
                ),
            )

        info = pdf.infodict()
        info["Title"] = options.title
        info["Author"] = options.author or "Ikalon Investments"
        info["Subject"] = f"Proyección patrimonial — {scenario.name}"
        info["Creator"] = "GBP — Ikalon Investments"

    return path
