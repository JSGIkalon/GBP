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

from ...model.cashflows import (
    CashFlow,
    FlowBasis,
    FlowKind,
    combined_rate_schedule,
    combined_schedule,
)
from ...model.scenario import Scenario
from ...model.strategy import Strategy
from ..theme import format_money

# Encabezados cortos: con los nombres completos la tabla no cabía en el panel
# y Qt recortaba las últimas columnas. El significado va en el tooltip.
COLUMNS = ["Nombre", "Tipo", "Base", "Monto anual", "Desde", "Hasta", "Indexa", "Crec. %"]
TOOLTIPS = [
    "Nombre del flujo",
    "Aporte (entra al portafolio) o retiro (sale)",
    "Monto fijo en moneda de hoy, o porcentaje del patrimonio de cada año",
    "Monto anual en moneda de hoy, o porcentaje si la base es '% patrimonio'",
    "Primer año en que ocurre",
    "Último año en que ocurre",
    "Si se marca, el monto crece con la inflación del escenario. "
    "No aplica a un flujo porcentual: ya se autoindexa con el patrimonio",
    "Crecimiento real anual, por encima de la inflación. "
    "No aplica a un flujo porcentual",
]

COL_NAME, COL_KIND, COL_BASIS, COL_AMOUNT, COL_START, COL_END, COL_INDEX, COL_GROWTH = range(8)


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
            "desde el primer año proyectado — la misma convención que usa J.P. Morgan. "
            "Con base '% patrimonio' el monto se calcula cada año sobre el patrimonio "
            "vigente: el retiro sube y baja con el mercado y el portafolio no se agota."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #3D5560;")
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
        # "Tipo" y "Base" llevan un desplegable como widget de celda, y
        # ResizeToContents no mide los widgets: sin un ancho propio el combo sale
        # cortado.
        header.setSectionResizeMode(COL_KIND, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(COL_KIND, 110)
        header.setSectionResizeMode(COL_BASIS, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(COL_BASIS, 130)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table, 1)

        self.summary = QLabel("")
        self.summary.setStyleSheet("color: #5B7280;")
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
        self.table.setItem(row, COL_NAME, QTableWidgetItem(flow.name))

        kind = QComboBox()
        kind.addItems([FlowKind.OUTFLOW.value, FlowKind.INFLOW.value])
        kind.setCurrentText(flow.kind.value)
        kind.currentTextChanged.connect(lambda text, r=row: self._set_kind(r, text))
        self.table.setCellWidget(row, COL_KIND, kind)

        basis = QComboBox()
        basis.addItems([FlowBasis.AMOUNT.value, FlowBasis.PORTFOLIO_PCT.value])
        basis.setCurrentText(flow.basis.value)
        basis.currentTextChanged.connect(lambda text, r=row: self._set_basis(r, text))
        self.table.setCellWidget(row, COL_BASIS, basis)

        # Un flujo porcentual se escribe en puntos porcentuales —4.00, no 0.04—
        # porque escribir "0.04" en una columna rotulada "Monto anual" al lado de
        # otra fila que dice "1,100,000" invita a leerlo como cuatro centavos.
        monto = f"{flow.amount * 100:,.2f} %" if flow.is_percentage else f"{flow.amount:,.0f}"
        for col, value in ((COL_AMOUNT, monto), (COL_START, str(flow.start_year)),
                           (COL_END, str(flow.end_year))):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, col, item)

        indexed = QTableWidgetItem()
        indexed.setCheckState(
            Qt.CheckState.Checked if flow.inflation_indexed else Qt.CheckState.Unchecked
        )
        growth = QTableWidgetItem("—" if flow.is_percentage else f"{flow.growth * 100:.2f}")
        growth.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Indexación y crecimiento real no significan nada sobre un porcentaje:
        # se muestran apagados en vez de ocultarse, para que se vea que existen y
        # por qué no aplican aquí.
        if flow.is_percentage:
            indexed.setFlags(Qt.ItemFlag.NoItemFlags)
            growth.setFlags(Qt.ItemFlag.ItemIsSelectable)
            tip = "No aplica a un flujo porcentual: el patrimonio ya crece por su cuenta."
            indexed.setToolTip(tip)
            growth.setToolTip(tip)
        else:
            indexed.setFlags(indexed.flags() | Qt.ItemFlag.ItemIsUserCheckable)

        self.table.setItem(row, COL_INDEX, indexed)
        self.table.setItem(row, COL_GROWTH, growth)

    # ------------------------------------------------------------------
    def _set_kind(self, row: int, text: str):
        if self._loading or row >= len(self.flows):
            return
        self.flows[row].kind = FlowKind(text)
        self._update_summary()
        self.changed.emit()

    def _set_basis(self, row: int, text: str):
        if self._loading or row >= len(self.flows):
            return
        flow = self.flows[row]
        nueva = FlowBasis(text)
        if nueva is flow.basis:
            return
        flow.basis = nueva
        # El número que había era de la otra unidad: 1,100,000 leído como
        # fracción sería 110000000% del patrimonio, y 4% leído como monto serían
        # cuatro pesos. Ninguna conversión es correcta, así que se arranca en
        # cero y se vuelve a escribir.
        flow.amount = 0.0
        if flow.is_percentage:
            flow.inflation_indexed = False
            flow.growth = 0.0
        else:
            flow.inflation_indexed = True

        self._loading = True
        self._set_row(row, flow)
        self._loading = False
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
            if col == COL_NAME:
                flow.name = item.text().strip() or flow.name
            elif col == COL_AMOUNT:
                texto = item.text().replace(",", "").replace("%", "").strip()
                value = float(texto)
                if value < 0:
                    raise ValueError("negativo")
                if flow.is_percentage:
                    if value > 100.0:
                        raise ValueError("más del 100% del patrimonio")
                    flow.amount = value / 100.0
                else:
                    flow.amount = value
            elif col == COL_START:
                flow.start_year = max(1, int(float(item.text())))
                flow.end_year = max(flow.end_year, flow.start_year)
            elif col == COL_END:
                flow.end_year = max(flow.start_year, int(float(item.text())))
            elif col == COL_INDEX and not flow.is_percentage:
                flow.inflation_indexed = item.checkState() == Qt.CheckState.Checked
            elif col == COL_GROWTH and not flow.is_percentage:
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
        texto = (
            f"Total del horizonte — aportes: {format_money(inflows)} · "
            f"retiros: {format_money(outflows)} · neto: {format_money(inflows - outflows)}"
        )

        # Los flujos porcentuales no tienen monto fuera de la simulación, así que
        # no se pueden sumar al total. Decirlo aparte es más honesto que dejar
        # que el usuario lea un total que no incluye la mitad de su plan.
        porcentuales = [f for f in self.flows if f.is_percentage]
        if porcentuales:
            rates = combined_rate_schedule(self.flows, self.scenario.horizon)
            activos = rates[rates != 0]
            rango = (
                f"{abs(activos).min():.2%}"
                if activos.size and abs(activos).min() == abs(activos).max()
                else f"{abs(activos).min():.2%}–{abs(activos).max():.2%}"
            ) if activos.size else "0%"
            texto += (
                f"\nAdemás {len(porcentuales)} flujo(s) por porcentaje del patrimonio "
                f"({rango} al año). Su monto depende de cada camino simulado, así que "
                "no entra en los totales de arriba."
            )
        self.summary.setText(texto)
