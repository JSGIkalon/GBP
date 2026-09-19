"""Pestañas de resultados: distribución, supuestos, estrés y deuda.

La distribución hace el trabajo que antes se repartía entre dos pestañas: el
box plot muestra el rango y la tabla de abajo trae las cifras exactas, que es
además la vista alternativa al color que exige el manual de marca.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...engine.stress import StressScenario
from ...model.results import SimulationResult
from ...model.scenario import Scenario, SimulationSettings
from ..charts.box_chart import distribution_table_rows, draw_box_chart
from ..charts.canvas import ChartCanvas
from ..charts.debt_chart import draw_debt_chart
from ..charts.stress_chart import draw_stress_chart
from ..theme import BLUE_MID, INK_SOFT, format_money, status_color, status_dot

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

        # --- Distribución ----------------------------------------------
        distribution = QWidget()
        d_layout = QVBoxLayout(distribution)
        self.box_canvas = ChartCanvas(height=4.6)
        d_layout.addWidget(self.box_canvas, 3)
        self.range_columns = [
            "Estrategia", "Año", "p10", "p25", "Mediana", "p75", "p90", "Media", "Desv. est.",
        ]
        self.range_table = _table(self.range_columns)
        d_layout.addWidget(self.range_table, 2)
        self.addTab(distribution, "Distribución")

        # --- Supuestos --------------------------------------------------
        summary = QWidget()
        s_layout = QVBoxLayout(summary)
        self.headline = QLabel(EMPTY)
        self.headline.setWordWrap(True)
        self.headline.setStyleSheet("font-size: 13px;")
        s_layout.addWidget(self.headline)
        self.summary_columns = [
            "Indicador", *[f"Estrategia {i + 1}" for i in range(8)]
        ]
        self.summary_table = _table(["Indicador"])
        s_layout.addWidget(self.summary_table, 1)
        note = QLabel(
            "Los supuestos resumen explican con qué se construyó la proyección; no son "
            "una predicción. El Sharpe usa como tasa libre de riesgo el retorno de la "
            "clase de caja."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #5C6770;")
        s_layout.addWidget(note)
        self.addTab(summary, "Supuestos")

        # --- Stress test ------------------------------------------------
        stress = QWidget()
        st_layout = QVBoxLayout(stress)
        self.stress_canvas = ChartCanvas(height=4.0)
        st_layout.addWidget(self.stress_canvas, 3)
        self.stress_columns = ["Escenario", "Estrategia", "Impacto %", "Pérdida"]
        self.stress_table = _table(self.stress_columns)
        st_layout.addWidget(self.stress_table, 2)
        stress_note = QLabel(
            "Los shocks son estimaciones editables por clase de activo, no retornos de "
            "índices reales. El cálculo desde series históricas queda para cuando se "
            "incorporen datos de mercado."
        )
        stress_note.setWordWrap(True)
        stress_note.setStyleSheet("color: #5C6770;")
        st_layout.addWidget(stress_note)
        self.addTab(stress, "Stress test")

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
    def clear(self):
        self.result = None
        for canvas in (self.box_canvas, self.debt_canvas):
            canvas.show_message(EMPTY)
        self.headline.setText(EMPTY)
        for table in (self.range_table, self.summary_table, self.debt_table):
            table.setRowCount(0)

    def show_stress(
        self, scenario: Scenario, scenarios: list[StressScenario]
    ):
        """El stress test no depende de la simulación: se puede ver sin correrla.

        El impacto se calcula sobre el capital con que arranca cada estrategia,
        que puede ser el del escenario o uno propio.
        """
        strategies = [s for s in scenario.strategies if s.asset_names]
        allocations = [s.allocation for s in strategies]
        draw_stress_chart(self.stress_canvas, allocations, scenarios, scenario.initial_value)

        rows = []
        for stress in scenarios:
            for strategy in strategies:
                impact = stress.impact(strategy.allocation)
                capital = strategy.resolved_initial(scenario.initial_value)
                rows.append(
                    {
                        "Escenario": stress.name,
                        "Estrategia": strategy.name,
                        "Impacto %": f"{impact * 100:.2f}",
                        "Pérdida": format_money(impact * capital),
                    }
                )
        _fill(self.stress_table, rows, self.stress_columns)

    def show_result(self, result: SimulationResult, settings: SimulationSettings, horizon: int):
        self.result = result
        self.settings = settings
        years = settings.milestones_within(horizon)
        real = settings.show_real_values

        draw_box_chart(self.box_canvas, result, years, real)
        _fill(
            self.range_table,
            distribution_table_rows(result, years, real),
            self.range_columns,
        )

        self._show_summary(result, real)
        self._show_debt(result)

    # ------------------------------------------------------------------
    def _show_summary(self, result: SimulationResult, real: bool):
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
            ("Retorno de largo plazo", lambda s: f"{s.summary.arithmetic_return:.2%}"),
            ("Volatilidad de largo plazo", lambda s: f"{s.summary.volatility:.2%}"),
            ("Retorno compuesto", lambda s: f"{s.summary.compound_return:.2%}"),
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

        best = max(result.strategies, key=lambda s: s.success_probability)
        probability = best.success_probability

        # El color del semáforo vive solo dentro del círculo: el texto va en Ink
        # y el énfasis lo lleva el azul de énfasis en la cifra que es el argumento.
        lede = status_dot(
            status_color(probability),
            f"<b>{best.name}</b> es la estrategia con mayor probabilidad de sostener "
            f"el plan: <b style='color:#007ABA;'>{probability:.1%}</b>",
        )
        detail = " · ".join(
            f"{s.name} {s.success_probability:.1%}" for s in result.strategies
        )
        self.headline.setText(
            f"<div style='font-size:15px;'>{lede}</div>"
            f"<div style='color:{BLUE_MID}; margin-top:4px;'>{detail}</div>"
            f"<div style='color:{INK_SOFT}; font-size:12px;'>{result.n_paths:,} simulaciones · "
            f"semilla {result.seed if result.seed is not None else 'aleatoria'}"
            f"{' · valores en moneda de hoy' if real else ' · valores nominales'}</div>"
        )

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
