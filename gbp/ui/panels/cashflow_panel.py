"""Panel de flujos: aportes y retiros de **una estrategia**.

Los flujos son de la estrategia, no del escenario: cada una puede tener sus
propios retiros y aportes, que es lo que permite comparar planes completos.
El horizonte y la inflación, en cambio, siguen siendo del escenario.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...model.cashflows import CashFlow, FlowKind, combined_schedule
from ...model.scenario import Scenario
from ...model.strategy import Strategy
from ..theme import format_money

# Encabezados cortos: con los nombres completos la tabla no cabía en el panel
# y Qt recortaba las últimas columnas. El significado va en el tooltip.
COLUMNS = ["Nombre", "Tipo", "Monto anual", "Desde", "Hasta", "Indexa", "Crec. %"]
TOOLTIPS = [
    "Nombre del flujo",
    "Aporte (entra al portafolio) o retiro (sale)",
    "Monto anual en moneda de hoy",
    "Primer año en que ocurre",
    "Último año en que ocurre",
    "Si se marca, el monto crece con la inflación del escenario",
    "Crecimiento real anual, por encima de la inflación",
]


class CashflowPanel(QWidget):
    """Tabla de flujos recurrentes."""

    changed = Signal()

    def __init__(self, scenario: Scenario, strategy: Strategy | None = None, parent=None):
        super().__init__(parent)
        self.scenario = scenario   # aporta horizonte e inflación
        self.strategy = strategy   # dueño de los flujos
        self._loading = False

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Los montos se ingresan en moneda de hoy. Si el flujo indexa inflación, crece "
            "desde el primer año proyectado — la misma convención que usa J.P. Morgan."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #1F2A30;")
        layout.addWidget(intro)

        # Los botones van **encima** de la tabla, igual que en Pesos. Debajo
        # quedaban empujados al fondo del panel, a media pantalla de distancia
        # de la tabla, y no se encontraban: parecía que no se podían agregar
        # flujos.
        buttons = QHBoxLayout()
        add_out = QPushButton("Agregar retiro")
        add_out.clicked.connect(lambda: self._add(FlowKind.OUTFLOW))
        add_in = QPushButton("Agregar aporte")
        add_in.clicked.connect(lambda: self._add(FlowKind.INFLOW))
        remove = QPushButton("Eliminar seleccionado")
        remove.clicked.connect(self._remove)
        buttons.addWidget(add_out)
        buttons.addWidget(add_in)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        for i, tip in enumerate(TOOLTIPS):
            self.table.horizontalHeaderItem(i).setToolTip(tip)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(COLUMNS)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        # "Tipo" lleva un desplegable como widget de celda, y ResizeToContents
        # no mide los widgets: sin un ancho propio el combo sale cortado.
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 110)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table, 1)

        self.summary = QLabel("")
        self.summary.setStyleSheet("color: #5C6770;")
        layout.addWidget(self.summary)

        self.reload(scenario, strategy)

    # ------------------------------------------------------------------
    @property
    def flows(self) -> list[CashFlow]:
        return self.strategy.cashflows if self.strategy is not None else []

    def reload(self, scenario: Scenario, strategy: Strategy | None = None):
        self.scenario = scenario
        self.strategy = strategy
        self.setEnabled(strategy is not None)
        self._loading = True
        self.table.setRowCount(len(self.flows))
        for row, flow in enumerate(self.flows):
            self._set_row(row, flow)
        self._loading = False
        self._update_summary()

    def _set_row(self, row: int, flow: CashFlow):
        self.table.setItem(row, 0, QTableWidgetItem(flow.name))

        combo = QComboBox()
        combo.addItems([FlowKind.OUTFLOW.value, FlowKind.INFLOW.value])
        combo.setCurrentText(flow.kind.value)
        combo.currentTextChanged.connect(lambda text, r=row: self._set_kind(r, text))
        self.table.setCellWidget(row, 1, combo)

        for col, value in ((2, f"{flow.amount:,.0f}"), (3, str(flow.start_year)),
                           (4, str(flow.end_year))):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, col, item)

        indexed = QTableWidgetItem()
        indexed.setFlags(indexed.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        indexed.setCheckState(
            Qt.CheckState.Checked if flow.inflation_indexed else Qt.CheckState.Unchecked
        )
        self.table.setItem(row, 5, indexed)

        growth = QTableWidgetItem(f"{flow.growth * 100:.2f}")
        growth.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table.setItem(row, 6, growth)

    # ------------------------------------------------------------------
    def _set_kind(self, row: int, text: str):
        if self._loading or row >= len(self.flows):
            return
        self.flows[row].kind = FlowKind(text)
        self._update_summary()
        self.changed.emit()

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._loading:
            return
        row, col = item.row(), item.column()
        if row >= len(self.flows):
            return
        flow = self.flows[row]
        try:
            if col == 0:
                flow.name = item.text().strip() or flow.name
            elif col == 2:
                value = float(item.text().replace(",", "").replace(".", ".").strip())
                if value < 0:
                    raise ValueError("negativo")
                flow.amount = value
            elif col == 3:
                flow.start_year = max(1, int(float(item.text())))
                flow.end_year = max(flow.end_year, flow.start_year)
            elif col == 4:
                flow.end_year = max(flow.start_year, int(float(item.text())))
            elif col == 5:
                flow.inflation_indexed = item.checkState() == Qt.CheckState.Checked
            elif col == 6:
                flow.growth = float(item.text().replace(",", ".").replace("%", "")) / 100.0
        except ValueError:
            pass  # se revierte abajo al repintar la fila

        self._loading = True
        self._set_row(row, flow)
        self._loading = False
        self._update_summary()
        self.changed.emit()

    def _add(self, kind: FlowKind):
        if self.strategy is None:
            return
        name = "Gasto de estilo de vida" if kind is FlowKind.OUTFLOW else "Aporte"
        self.strategy.cashflows.append(
            CashFlow(name, kind, 0.0, 1, self.scenario.horizon)
        )
        self.reload(self.scenario, self.strategy)
        self.changed.emit()

    def _remove(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.flows):
            self.strategy.cashflows.pop(row)
            self.reload(self.scenario, self.strategy)
            self.changed.emit()

    def _update_summary(self):
        if not self.flows:
            self.summary.setText("Sin flujos definidos para esta estrategia.")
            return
        schedule = combined_schedule(
            self.flows, self.scenario.horizon, self.scenario.inflation
        )
        inflows = float(schedule[schedule > 0].sum())
        outflows = float(-schedule[schedule < 0].sum())
        self.summary.setText(
            f"Total del horizonte — aportes: {format_money(inflows)} · "
            f"retiros: {format_money(outflows)} · neto: {format_money(inflows - outflows)}"
        )
