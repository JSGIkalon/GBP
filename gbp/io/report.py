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

El informe es un registro: cada página lleva la fecha, la semilla y el número de
caminos, que es lo que permite reproducir la corrida exacta más adelante.

Estructura
----------
Portada · supuestos del caso · asignación de activos · gráficas · **anexo**.

Las tablas de datos van todas al anexo y cada gráfica cita la suya por número.
La excepción es la de supuestos resumen, que se queda en el cuerpo: no es un
dato que se consulte sino la explicación de con qué se proyectó. Los números del
anexo se reservan antes de escribir la primera página —ver `_build_annex`—
porque las gráficas del cuerpo los citan y el PDF se escribe de una sola pasada.
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
def _cover(pdf: PdfPages, options: ReportOptions, scenario: Scenario,
           result: SimulationResult, settings: SimulationSettings):
    figure = Figure(figsize=PAGE_SIZE, dpi=150)
    figure.patch.set_facecolor("white")

    figure.text(MARGIN, 0.88, "IKALON INVESTMENTS", color=NAVY, fontsize=10,
                fontweight="semibold")
    figure.text(MARGIN, 0.80, options.title, color=NAVY, fontsize=30,
                fontweight="semibold", va="top")

    y = 0.66
    for label, value in (
        ("Cliente", options.client),
        ("Caso", scenario.name),
        ("Fecha", options.date_text),
        ("Preparado por", options.author),
    ):
        if not value:
            continue
        figure.text(MARGIN, y, label, color=INK_SOFT, fontsize=9)
        figure.text(MARGIN + 0.14, y, value, color=INK, fontsize=12)
        y -= 0.05

    _add_rule(figure, y - 0.02)
    y -= 0.08

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

    y -= 0.06
    ficha = (
        f"Capital inicial {format_money(scenario.initial_value)} · "
        f"horizonte {scenario.horizon} años · inflación {scenario.inflation:.2%} · "
        f"{result.n_paths:,} simulaciones · "
        f"semilla {result.seed if result.seed is not None else 'aleatoria'} · "
        f"valores {'en moneda de hoy' if settings.show_real_values else 'nominales'}"
    )
    for line in _wrap(ficha, 110):
        figure.text(MARGIN, y, line, color=INK_SOFT, fontsize=9)
        y -= 0.028

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


CHART_RECT = (0.08, 0.16, 0.86, 0.70)
# La asignación de activos rotula cada barra con el nombre de su sub-clase
# —"Emerging Markets Sovereign Debt" y parecidos—, así que necesita un margen
# izquierdo mucho más ancho o el texto se sale de la hoja.
ALLOCATION_RECT = (0.26, 0.16, 0.68, 0.70)
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
    if footnote:
        # Por **debajo** de la nota que el propio gráfico escribe bajo su eje
        # —el box plot explica ahí sus percentiles—, no encima: a la misma
        # altura las dos líneas quedaban pegadas y con sangrías distintas.
        for i, line in enumerate(_wrap(footnote, 150)):
            figure.text(MARGIN, 0.062 - i * 0.021, line, color=INK_SOFT, fontsize=7.5)
    pdf.savefig(figure)
    return page_no + 1


def _table_pages(pdf: PdfPages, options: ReportOptions, page_no: int, eyebrow: str,
                 lede: str, columns: list[str], rows: list[list[str]],
                 footnote: str = "", rows_per_page: int = 26) -> int:
    """Tabla paginada. matplotlib no pagina solo, así que se corta a mano."""
    if not rows:
        rows = [["Sin datos"] + [""] * (len(columns) - 1)]

    chunks = [rows[i:i + rows_per_page] for i in range(0, len(rows), rows_per_page)]
    for i, chunk in enumerate(chunks):
        figure = _new_page(pdf, options, eyebrow, page_no)
        _add_rule(figure, 0.945)
        title = lede if i == 0 else f"{lede} (continúa)"
        figure.text(MARGIN, 0.90, title, color=INK, fontsize=14,
                    fontweight="semibold", va="top")

        ax = figure.add_axes((MARGIN, 0.10, 1 - 2 * MARGIN, 0.76))
        ax.axis("off")
        table = ax.table(
            cellText=chunk, colLabels=columns, loc="upper center", cellLoc="right",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1, 1.55)
        for (row, col), cell in table.get_celld().items():
            cell.set_linewidth(0)
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

        if footnote:
            figure.text(MARGIN, 0.072, footnote, color=INK_SOFT, fontsize=7.5)
        pdf.savefig(figure)
        page_no += 1
    return page_no


def _summary_rows(result: SimulationResult, real: bool) -> tuple[list[str], list[list[str]]]:
    indicators = [
        ("Probabilidad de éxito", lambda s: f"{s.success_probability:.1%}"),
        ("Retorno de largo plazo", lambda s: f"{s.summary.arithmetic_return:.2%}"),
        ("Volatilidad de largo plazo", lambda s: f"{s.summary.volatility:.2%}"),
        ("Retorno compuesto", lambda s: f"{s.summary.compound_return:.2%}"),
        ("Yield de largo plazo", lambda s: f"{s.summary.yield_:.2%}"),
        ("Sharpe de largo plazo", lambda s: f"{s.summary.sharpe_ratio:.2f}"),
        ("Patrimonio mediano final",
         lambda s: format_money(float(np.median(s.terminal_values(real))))),
        ("CVaR 5% al final", lambda s: format_money(s.cvar(s.horizon, 0.05, real))),
    ]
    columns = ["Indicador", *result.names]
    rows = [[label, *[getter(s) for s in result.strategies]] for label, getter in indicators]
    return columns, rows


def _inputs_pages(pdf: PdfPages, options: ReportOptions, page_no: int,
                  scenario: Scenario) -> int:
    """Los inputs del caso, para que el informe sea reproducible sin el .gbp.json."""
    figure = _new_page(pdf, options, "Supuestos del caso", page_no)
    figure.text(MARGIN, 0.90, "Con qué se construyó esta proyección",
                color=INK, fontsize=14, fontweight="semibold", va="top")

    y = 0.83
    figure.text(MARGIN, y, "ESCENARIO", color=NAVY, fontsize=8.5, fontweight="semibold")
    y -= 0.035
    for label, value in (
        ("Capital inicial", format_money(scenario.initial_value)),
        ("Horizonte", f"{scenario.horizon} años"),
        ("Inflación anual", f"{scenario.inflation:.2%}"),
    ):
        figure.text(MARGIN + 0.01, y, label, color=INK_SOFT, fontsize=9)
        figure.text(MARGIN + 0.16, y, value, color=INK, fontsize=9.5)
        y -= 0.028

    for i, strategy in enumerate(scenario.strategies):
        if y < 0.16:
            pdf.savefig(figure)
            page_no += 1
            figure = _new_page(pdf, options, "Supuestos del caso", page_no)
            _add_rule(figure, 0.945)
            y = 0.90

        y -= 0.03
        # La viñeta de color es un rectángulo, no un carácter: Jost no trae el
        # glifo "●" y matplotlib lo dibujaría como un cuadro vacío en el PDF.
        _swatch(figure, MARGIN, y, series_color(i))
        figure.text(MARGIN + 0.018, y, strategy.name.upper(), color=NAVY, fontsize=9,
                    fontweight="semibold")
        y -= 0.032

        # Primero la lectura agrupada, que es la que se mira en una reunión, y
        # debajo el detalle por sub-clase, que es el que hace falta para
        # reproducir el caso.
        resumen = group_summary(strategy.weights, options.resolver)
        for line in _wrap(f"Por clase de activo: {resumen}", 130):
            figure.text(MARGIN + 0.01, y, line, color=INK, fontsize=8.5,
                        fontweight="semibold")
            y -= 0.024

        pesos = " · ".join(
            f"{name} {weight:.1%}" for name, weight in strategy.weights.items()
        ) or "sin pesos definidos"
        for line in _wrap(f"Detalle por sub-clase: {pesos}", 130):
            figure.text(MARGIN + 0.01, y, line, color=INK, fontsize=8.5)
            y -= 0.024

        capital = (
            format_money(strategy.initial_value) if strategy.has_own_initial
            else f"{format_money(scenario.initial_value)} (del escenario)"
        )
        figure.text(MARGIN + 0.01, y, f"Capital inicial: {capital}", color=INK, fontsize=8.5)
        y -= 0.024

        if strategy.cashflows:
            for flow in strategy.cashflows:
                texto = (
                    f"{flow.kind.value.capitalize()} · {flow.name}: "
                    f"{format_money(flow.amount)} al año, años {flow.start_year}–{flow.end_year}"
                    f"{', indexado a inflación' if flow.inflation_indexed else ''}"
                    f"{f', crecimiento real {flow.growth:.2%}' if flow.growth else ''}"
                )
                for line in _wrap(texto, 130):
                    figure.text(MARGIN + 0.01, y, line, color=INK, fontsize=8.5)
                    y -= 0.024
        else:
            figure.text(MARGIN + 0.01, y, "Sin flujos.", color=INK_SOFT, fontsize=8.5)
            y -= 0.024

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
            texto = (
                f"Crédito · {loan.name}: {format_money(loan.principal)} en el año "
                f"{loan.start_year}, plazo {loan.term_years} años, {tasa}, intereses "
                f"{loan.interest_mode.value}, amortización {loan.amortization.value}{ltv}"
            )
            for line in _wrap(texto, 130):
                figure.text(MARGIN + 0.01, y, line, color=INK, fontsize=8.5)
                y -= 0.024
        else:
            figure.text(MARGIN + 0.01, y, "Sin apalancamiento.", color=INK_SOFT, fontsize=8.5)
            y -= 0.024

    pdf.savefig(figure)
    page_no += 1

    propios = _custom_used(scenario, options)
    if propios:
        page_no = _custom_assets_page(pdf, options, page_no, propios)
    return page_no


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


def _custom_assets_page(pdf: PdfPages, options: ReportOptions, page_no: int,
                        propios: list) -> int:
    """Página de activos propios.

    No es opcional cuando los hay: un supuesto que fijó el analista y que no
    está publicado por nadie tiene que quedar escrito en el documento que ve el
    cliente, o la proyección no se puede auditar.
    """
    figure = _new_page(pdf, options, "Activos propios", page_no)
    figure.text(MARGIN, 0.90, "Supuestos declarados por el analista",
                color=INK, fontsize=14, fontweight="semibold", va="top")

    y = 0.83
    for line in _wrap(
        "Estas clases de activo no están en el LTCMA: sus supuestos los fijó quien "
        "preparó este informe, y sus correlaciones se derivan del promedio de la "
        "clase de activo indicada. Los valores están en dólares.", 130
    ):
        figure.text(MARGIN, y, line, color=INK_SOFT, fontsize=8.5)
        y -= 0.024

    y -= 0.02
    for asset in propios:
        _swatch(figure, MARGIN, y, NAVY)
        figure.text(MARGIN + 0.018, y, asset.name.upper(), color=NAVY, fontsize=9,
                    fontweight="semibold")
        y -= 0.032
        detalle = (
            f"Clase: {asset.asset_class} · retorno compuesto {asset.compound_return:.2%}"
            f" · volatilidad {asset.volatility:.2%} · yield {asset.yield_:.2%}"
        )
        for line in _wrap(detalle, 130):
            figure.text(MARGIN + 0.01, y, line, color=INK, fontsize=8.5)
            y -= 0.024
        if asset.notes:
            for line in _wrap(f"Notas: {asset.notes}", 130):
                figure.text(MARGIN + 0.01, y, line, color=INK_SOFT, fontsize=8.5)
                y -= 0.024
        y -= 0.014

    pdf.savefig(figure)
    return page_no + 1


# ----------------------------------------------------------------------
@dataclass
class _AnnexTable:
    """Una tabla del anexo, ya numerada.

    Se arma **antes** de escribir ninguna página porque las gráficas del cuerpo
    citan su número: "Detalle en el Anexo · Tabla 2". Sin reservar los números
    primero habría que escribir el PDF en dos pasadas.
    """

    number: int
    title: str
    columns: list[str]
    rows: list[list[str]]
    footnote: str = ""

    @property
    def reference(self) -> str:
        return f"Anexo · Tabla {self.number}"


DISTRIBUTION_COLUMNS = [
    "Estrategia", "Año", "p10", "p25", "Mediana", "p75", "p90", "Media", "Desv. est.",
]


def _build_annex(
    options: ReportOptions,
    scenario: Scenario,
    result: SimulationResult,
    years: list[int],
    real: bool,
    con_deuda: bool,
    moneda: str,
) -> list[_AnnexTable]:
    """Las tablas del anexo, numeradas en el orden en que se imprimirán.

    Solo entra la tabla de una sección que el usuario haya pedido: un anexo con
    el detalle de una gráfica que no está en el documento no lo entendería nadie.
    """
    tablas: list[tuple[str, list[str], list[list[str]], str]] = []

    if options.include_allocation:
        columnas = ["Estrategia", "Clase de activo", "Sub-clase", "Peso"]
        tablas.append((
            "Asignación de activos por sub-clase",
            columnas,
            [[row[c] for c in columnas]
             for row in allocation_table_rows(scenario, options.resolver)],
            "Pesos normalizados sobre el total cargado de cada estrategia.",
        ))

    if options.include_distribution:
        tablas.append((
            "Patrimonio neto proyectado por año hito",
            DISTRIBUTION_COLUMNS,
            [[str(row[c]) for c in DISTRIBUTION_COLUMNS]
             for row in distribution_table_rows(result, years, real)],
            moneda,
        ))

    if con_deuda:
        tablas.append((
            "Llamadas a margen y liquidación forzada",
            ["Estrategia", "Prob. llamada a margen", "Llamadas promedio",
             "Liquidación máxima"],
            [[s.name, f"{s.margin_call_probability:.1%}",
              f"{s.margin_calls.mean():.2f}" if s.margin_calls.size else "0.00",
              format_money(float(s.forced_sales.max())) if s.forced_sales.size else "0"]
             for s in result.strategies],
            "",
        ))

    return [
        _AnnexTable(number=i, title=titulo, columns=columnas, rows=filas, footnote=nota)
        for i, (titulo, columnas, filas, nota) in enumerate(tablas, start=1)
    ]


def build_report(
    path: str | Path,
    options: ReportOptions,
    scenario: Scenario,
    result: SimulationResult,
    settings: SimulationSettings,
) -> Path:
    """Escribe el PDF y devuelve la ruta.

    Orden del documento: portada, supuestos del caso, asignación de activos,
    y luego las gráficas. **Las tablas van todas al anexo**, salvo la de
    supuestos resumen, que es narrativa y no dato de consulta. Cada gráfica cita
    la tabla que la respalda, de modo que el cuerpo se lee de corrido y el
    detalle está donde se busca: al final.
    """
    apply_matplotlib_style()
    path = Path(path)
    real = settings.show_real_values
    years = settings.milestones_within(scenario.horizon)
    moneda = "Valores en moneda de hoy." if real else "Valores nominales."
    con_deuda = options.include_debt and any(s.debt.max() > 0 for s in result.strategies)

    annex = _build_annex(options, scenario, result, years, real, con_deuda, moneda)
    por_titulo = {t.title: t for t in annex}

    def cita(titulo: str, extra: str = "") -> str:
        tabla = por_titulo.get(titulo)
        if tabla is None:
            return extra
        return f"{extra} Detalle en el {tabla.reference}.".strip()

    with PdfPages(path) as pdf:
        _cover(pdf, options, scenario, result, settings)
        page = 2

        if options.include_inputs:
            page = _inputs_pages(pdf, options, page, scenario)

        if options.include_allocation:
            page = _chart_page(
                pdf, options, page, "Asignación de activos",
                lambda canvas: draw_allocation_chart(
                    canvas, scenario, options.resolver, ALLOCATION_TITLE_X
                ),
                cita(
                    "Asignación de activos por sub-clase",
                    "Los pesos están normalizados sobre el total cargado de cada "
                    "estrategia.",
                ),
                rect=ALLOCATION_RECT,
            )

        if options.include_distribution:
            page = _chart_page(
                pdf, options, page, "Distribución",
                lambda canvas: draw_box_chart(canvas, result, years, real),
                cita(
                    "Patrimonio neto proyectado por año hito",
                    "Percentiles calculados sobre los caminos simulados, sin suponer "
                    f"forma de distribución. {moneda}",
                ),
            )

        if options.include_summary:
            columns, rows = _summary_rows(result, real)
            page = _table_pages(
                pdf, options, page, "Supuestos resumen",
                "Con qué retorno y qué riesgo se proyectó cada estrategia",
                columns, rows,
                "El Sharpe usa como tasa libre de riesgo el retorno de la clase de caja. "
                "Los supuestos resumen explican la proyección; no son una predicción.",
            )

        if con_deuda:
            page = _chart_page(
                pdf, options, page, "Deuda",
                lambda canvas: draw_debt_chart(canvas, result),
                cita(
                    "Llamadas a margen y liquidación forzada",
                    "Línea: mediana. Banda: percentil 5 al 95.",
                ),
            )

        for tabla in annex:
            page = _table_pages(
                pdf, options, page, "Anexo",
                f"Tabla {tabla.number} · {tabla.title}",
                tabla.columns, tabla.rows, tabla.footnote,
            )

        info = pdf.infodict()
        info["Title"] = options.title
        info["Author"] = options.author or "Ikalon Investments"
        info["Subject"] = f"Proyección patrimonial — {scenario.name}"
        info["Creator"] = "GBP — Ikalon Investments"

    return path
