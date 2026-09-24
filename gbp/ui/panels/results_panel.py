"""Pestañas de resultados: distribución, supuestos, asignación y deuda.

La distribución hace el trabajo que antes se repartía entre dos pestañas: el
box plot muestra el rango y la tabla de abajo trae las cifras exactas, que es
además la vista alternativa al color que exige el manual de marca.

Y se muestra **dos veces**, en dos pestañas: en valores nominales y en moneda de
hoy. Ajustar por inflación no es una preferencia de configuración —la nominal es
la que verá en su extracto y la real es la que dice qué podrá comprar—, así que
las dos están siempre a un clic en vez de detrás de una casilla que cambia el
significado de todo lo demás sin decirlo.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...model.results import SimulationResult
from ...model.scenario import Scenario, SimulationSettings
from ..charts.allocation_chart import allocation_table_rows, draw_allocation_chart
from ..charts.box_chart import distribution_table_rows, draw_box_chart
from ..charts.canvas import ChartCanvas
from ..charts.debt_chart import draw_debt_chart
from ..theme import format_money

EMPTY = "Carga los datos del caso y pulsa «Correr simulación»."


def _table(columns: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for i in range(1, len(columns)):
        header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
    return table


def _fill(table: QTableWidget, rows: list[dict], columns: list[str]):
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, column in enumerate(columns):
            item = QTableWidgetItem(str(row.get(column, "")))
            if c > 0:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(r, c, item)


class ResultsPanel(QTabWidget):
    """Todas las vistas de resultado de una corrida."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result: SimulationResult | None = None
        self.settings = SimulationSettings()
        self.years: list[int] = []
        # Los percentiles p10/p25/p75/p90 se pueden ocultar del gráfico: la
        # mediana es la cifra que importa y las demás siempre están en la
        # tabla de abajo, así que ocultarlas despeja la caja sin perder nada.
        self.show_percentile_labels = True

        # --- Distribución, en las dos unidades ---------------------------
        self.range_columns = [
            "Estrategia", "Año", "p10", "p25", "Mediana", "p75", "p90", "Media", "Desv. est.",
        ]
        self.box_canvas, self.range_table = self._add_distribution_tab(
            "Distribución",
            "Valores nominales: el patrimonio tal como aparecerá en el extracto.",
        )
        self.real_canvas, self.real_table = self._add_distribution_tab(
            "Ajustada por inflación",
            "Valores en moneda de hoy, descontados a la inflación del escenario: "
            "lo que ese patrimonio podría comprar hoy.",
        )

        # --- Flujos y valor de portafolio ---------------------------------
        flows = QWidget()
        f_layout = QVBoxLayout(flows)
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Portafolio:"))
        self.flows_selector = QComboBox()
        self.flows_selector.currentIndexChanged.connect(self._show_flows)
        selector_row.addWidget(self.flows_selector, 1)
        f_layout.addLayout(selector_row)
        self.flow_columns = [
            "Año", "Flujos netos", "Flujos netos acumulados",
            "Valor portafolio", "Valor portafolio (moneda de hoy)",
        ]
        self.flows_table = _table(self.flow_columns)
        f_layout.addWidget(self.flows_table, 1)
        flows_note = QLabel(
            "Flujos netos: aportes menos retiros, medianos sobre los caminos simulados. "
            "Valor portafolio: patrimonio neto mediano al cierre de cada año, en "
            "valores nominales y en moneda de hoy."
        )
        flows_note.setWordWrap(True)
        flows_note.setStyleSheet("color: #5B7280;")
        f_layout.addWidget(flows_note)
        self.addTab(flows, "Flujos y valor")

        # --- Supuestos --------------------------------------------------
        summary = QWidget()
        s_layout = QVBoxLayout(summary)
        self.summary_columns = [
            "Indicador", *[f"Estrategia {i + 1}" for i in range(8)]
        ]
        self.summary_table = _table(["Indicador"])
        s_layout.addWidget(self.summary_table, 1)
        note = QLabel(
            "Los supuestos resumen explican con qué se construyó la proyección; no son "
            "una predicción. El Sharpe usa como tasa libre de riesgo el retorno de la "
            "clase de caja. El retorno compuesto es el que capitaliza año tras año: ya "
            "lleva descontado el arrastre de la volatilidad sobre el retorno aritmético, "
            "y es el único que se muestra porque es el que gobierna la proyección.\n\n"
            "El cambio del patrimonio en el último año no es rentabilidad: es la "
            "variación mediana del patrimonio neto entre el penúltimo año y el último, "
            "aportes y retiros incluidos. Dice si al final del horizonte el plan todavía "
            "crece o ya se está consumiendo. Las cifras en dinero son nominales."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #5B7280;")
        s_layout.addWidget(note)
        self.addTab(summary, "Supuestos")

        # --- Asignación de activos --------------------------------------
        allocation = QWidget()
        a_layout = QVBoxLayout(allocation)
        self.allocation_canvas = ChartCanvas(height=5.2)
        a_layout.addWidget(self.allocation_canvas, 3)
        self.allocation_columns = [
            "Estrategia", "Clase de activo", "Sub-clase", "Peso",
        ]
        self.allocation_table = _table(self.allocation_columns)
        a_layout.addWidget(self.allocation_table, 2)
        allocation_note = QLabel(
            "Los pesos están normalizados sobre el total cargado de cada estrategia. "
            "La agrupación en cuatro clases es una vista de lectura: los pesos se "
            "cargan siempre por sub-clase."
        )
        allocation_note.setWordWrap(True)
        allocation_note.setStyleSheet("color: #5B7280;")
        a_layout.addWidget(allocation_note)
        self.addTab(allocation, "Asignación")

        # --- Deuda ------------------------------------------------------
        debt = QWidget()
        de_layout = QVBoxLayout(debt)
        self.debt_canvas = ChartCanvas(height=4.0)
        de_layout.addWidget(self.debt_canvas, 3)
        self.debt_columns = [
            "Estrategia", "Prob. llamada a margen", "Llamadas promedio", "Liquidación máxima",
        ]
        self.debt_table = _table(self.debt_columns)
        de_layout.addWidget(self.debt_table, 1)
        self.addTab(debt, "Deuda")

        self.clear()

    # ------------------------------------------------------------------
    def _add_distribution_tab(self, title: str, note: str):
        """Una pestaña de distribución: box plot, tabla y la nota de su unidad."""
        page = QWidget()
        layout = QVBoxLayout(page)
        canvas = ChartCanvas(height=4.6)
        layout.addWidget(canvas, 3)
        toggle = QCheckBox("Mostrar percentiles p10/p25/p75/p90 en el gráfico")
        toggle.setChecked(True)
        toggle.toggled.connect(self._toggle_percentile_labels)
        layout.addWidget(toggle)
        table = _table(self.range_columns)
        layout.addWidget(table, 2)
        label = QLabel(note)
        label.setWordWrap(True)
        label.setStyleSheet("color: #5B7280;")
        layout.addWidget(label)
        self.addTab(page, title)
        return canvas, table

    def _toggle_percentile_labels(self, checked: bool):
        """Un solo interruptor para las dos unidades: es la misma preferencia de lectura."""
        self.show_percentile_labels = checked
        for checkbox in self.findChildren(QCheckBox):
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)
        if self.result is not None:
            self._draw_distributions()

    def _draw_distributions(self):
        for canvas, real in ((self.box_canvas, False), (self.real_canvas, True)):
            draw_box_chart(
                canvas, self.result, self.years, real,
                show_percentile_labels=self.show_percentile_labels,
            )

    def clear(self):
        self.result = None
        self.years = []
        for canvas in (self.box_canvas, self.real_canvas, self.debt_canvas):
            canvas.show_message(EMPTY)
        for table in (self.range_table, self.real_table, self.summary_table, self.debt_table,
                      self.flows_table):
            table.setRowCount(0)
        self.flows_selector.clear()

    def show_allocation(self, scenario: Scenario, resolver=None):
        """La asignación no depende de la simulación: se ve sin haberla corrido.

        Es lo que hace útil la pestaña mientras se arma el caso: los pesos se
        editan al lado y aquí se ve de inmediato en qué queda el reparto.
        """
        draw_allocation_chart(self.allocation_canvas, scenario, resolver)
        _fill(
            self.allocation_table,
            allocation_table_rows(scenario, resolver),
            self.allocation_columns,
        )

    def show_result(self, result: SimulationResult, settings: SimulationSettings, horizon: int):
        self.result = result
        self.settings = settings
        self.years = settings.milestones_within(horizon)

        self._draw_distributions()
        for table, real in ((self.range_table, False), (self.real_table, True)):
            _fill(table, distribution_table_rows(result, self.years, real), self.range_columns)

        self._show_summary(result)
        self._show_debt(result)
        self._show_flows_selector(result)

    # ------------------------------------------------------------------
    def _show_flows_selector(self, result: SimulationResult):
        self.flows_selector.blockSignals(True)
        self.flows_selector.clear()
        self.flows_selector.addItems(result.names)
        self.flows_selector.blockSignals(False)
        self._show_flows(0)

    def _show_flows(self, index: int):
        if self.result is None or index < 0 or index >= len(self.result.strategies):
            self.flows_table.setRowCount(0)
            return
        strategy = self.result.strategies[index]
        valores = strategy.flow_value_series()
        rows = [
            {
                "Año": year,
                "Flujos netos": format_money(float(valores["neto"][year - 1])),
                "Flujos netos acumulados": format_money(float(valores["acumulado"][year - 1])),
                "Valor portafolio": format_money(float(valores["valor_nominal"][year - 1])),
                "Valor portafolio (moneda de hoy)": format_money(
                    float(valores["valor_real"][year - 1])
                ),
            }
            for year in range(1, strategy.horizon + 1)
        ]
        _fill(self.flows_table, rows, self.flow_columns)

    # ------------------------------------------------------------------
    def _show_summary(self, result: SimulationResult, real: bool = False):
        names = result.names
        columns = ["Indicador", *names]
        self.summary_table.setColumnCount(len(columns))
        self.summary_table.setHorizontalHeaderLabels(columns)
        header = self.summary_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(columns)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        indicators = [
            ("Probabilidad de éxito", lambda s: f"{s.success_probability:.1%}"),
            ("Retorno compuesto de largo plazo", lambda s: f"{s.summary.compound_return:.2%}"),
            ("Volatilidad de largo plazo", lambda s: f"{s.summary.volatility:.2%}"),
            ("Yield de largo plazo", lambda s: f"{s.summary.yield_:.2%}"),
            ("Sharpe de largo plazo", lambda s: f"{s.summary.sharpe_ratio:.2f}"),
            (
                "Patrimonio mediano final",
                lambda s: format_money(float(np.median(s.terminal_values(real)))),
            ),
            (
                "CVaR 5% al final",
                lambda s: format_money(s.cvar(s.horizon, 0.05, real)),
            ),
            (
                "Cambio del patrimonio en el último año",
                lambda s: f"{s.last_year_change(real):.2%}",
            ),
        ]

        self.summary_table.setRowCount(len(indicators))
        for r, (label, getter) in enumerate(indicators):
            self.summary_table.setItem(r, 0, QTableWidgetItem(label))
            for c, strategy in enumerate(result.strategies, start=1):
                item = QTableWidgetItem(getter(strategy))
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                self.summary_table.setItem(r, c, item)

    def _show_debt(self, result: SimulationResult):
        draw_debt_chart(self.debt_canvas, result)
        rows = []
        for strategy in result.strategies:
            rows.append(
                {
                    "Estrategia": strategy.name,
                    "Prob. llamada a margen": f"{strategy.margin_call_probability:.1%}",
                    "Llamadas promedio": (
                        f"{strategy.margin_calls.mean():.2f}"
                        if strategy.margin_calls.size else "0.00"
                    ),
                    "Liquidación máxima": (
                        format_money(float(strategy.forced_sales.max()))
                        if strategy.forced_sales.size else "0"
                    ),
                }
            )
        _fill(self.debt_table, rows, self.debt_columns)
