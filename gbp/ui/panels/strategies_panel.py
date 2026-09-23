"""Panel de estrategias: cada una es un caso completo a comparar.

Una estrategia no es solo una mezcla de activos: lleva sus propios aportes y
retiros, su propio crédito y, si se quiere, su propio capital. Por eso este
panel agrupa cuatro sub-pestañas —Pesos, Flujos, Crédito y Capital— para la
estrategia elegida en el selector de arriba.

Las clases de activo se eligen de un desplegable por fila, poblado con las que
están a la vez en la librería de CMAs y en la matriz de correlación del LTCMA:
si una clase no tiene correlación no se puede simular, así que no se ofrece.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...model.allocation import Allocation
from ...model.assets import CMASet
from ...model.groups import group_weights
from ...model.scenario import Scenario
from ...model.strategy import Strategy
from ..theme import (
    BLUE_MID,
    INK_SOFT,
    MAX_SERIES,
    STATUS_CRITICAL,
    STATUS_GOOD,
    series_color,
    status_dot,
)
from .capital_panel import CapitalPanel
from .cashflow_panel import CashflowPanel
from .leverage_panel import LeveragePanel


class StrategiesPanel(QWidget):
    """Selector de estrategias y editor completo de la seleccionada."""

    changed = Signal()

    def __init__(self, scenario: Scenario, cmas: CMASet, available: list[str],
                 resolver=None, parent=None):
        super().__init__(parent)
        self.scenario = scenario
        self.cmas = cmas
        self.available = available
        # Sin resolvedor la vista agrupada clasifica por palabras clave, que es
        # lo correcto mientras no haya activos propios.
        self.resolver = resolver
        self._loading = False

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Cada estrategia es un caso completo —pesos, flujos, crédito y capital— y "
            "todas se simulan con los mismos sorteos de mercado, así que las diferencias "
            "vienen de la estrategia y no del azar."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #3D5560;")
        layout.addWidget(intro)

        layout.addLayout(self._build_selector())
        layout.addWidget(self._build_editor(), 1)

        self.reload(scenario, cmas, available, resolver)

    # ------------------------------------------------------------------
    def _build_selector(self) -> QVBoxLayout:
        """Selector compacto arriba, no una lista lateral.

        Una lista a la izquierda se comía un cuarto del ancho del panel y dejaba
        las tablas del editor recortadas. Con el selector arriba, el editor usa
        todo el ancho disponible.
        """
        block = QVBoxLayout()

        row = QHBoxLayout()
        label = QLabel("ESTRATEGIA")
        label.setStyleSheet("color: #4D849E; font-weight: 600; letter-spacing: 2px;")
        row.addWidget(label)
        self.selector = QComboBox()
        self.selector.currentIndexChanged.connect(self._on_select)
        row.addWidget(self.selector, 1)
        block.addLayout(row)

        # Los botones van en su propia fila: junto al desplegable no caben y Qt
        # los recorta a media palabra.
        buttons = QHBoxLayout()
        for text, slot in (
            ("Nueva", self._add_strategy),
            ("Duplicar", self._duplicate_strategy),
            ("Renombrar", self._rename_strategy),
            ("Eliminar", self._remove_strategy),
            ("Borrar todas", self._remove_all_strategies),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        block.addLayout(buttons)

        self.badges = QLabel("")
        self.badges.setWordWrap(True)
        self.badges.setStyleSheet(f"color: {INK_SOFT};")
        block.addWidget(self.badges)

        return block

    def _build_editor(self) -> QWidget:
        panel = QWidget()
        column = QVBoxLayout(panel)
        column.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()

        self.tabs.addTab(self._build_weights_tab(), "Pesos")

        self.cashflow_panel = CashflowPanel(self.scenario)
        self.cashflow_panel.changed.connect(self._on_child_changed)
        self.tabs.addTab(self.cashflow_panel, "Flujos")

        self.leverage_panel = LeveragePanel(self.scenario)
        self.leverage_panel.changed.connect(self._on_child_changed)
        self.tabs.addTab(self.leverage_panel, "Crédito")

        self.capital_panel = CapitalPanel(self.scenario)
        self.capital_panel.changed.connect(self._on_child_changed)
        self.tabs.addTab(self.capital_panel, "Capital")

        column.addWidget(self.tabs, 1)
        return panel

    def _build_weights_tab(self) -> QWidget:
        tab = QWidget()
        column = QVBoxLayout(tab)

        # Barra de acciones propia, encima de la tabla: antes compartía fila con
        # el desplegable y los cuatro widgets no cabían, así que Qt los recortaba.
        actions = QHBoxLayout()
        add_asset = QPushButton("Agregar clase de activo")
        add_asset.clicked.connect(self._add_asset_row)
        remove_asset = QPushButton("Quitar clase")
        remove_asset.clicked.connect(self._remove_asset_row)
        normalize = QPushButton("Normalizar a 100%")
        normalize.clicked.connect(self._normalize)
        actions.addWidget(add_asset)
        actions.addWidget(remove_asset)
        actions.addWidget(normalize)
        actions.addStretch(1)
        column.addLayout(actions)

        self.weights_table = QTableWidget(0, 2)
        self.weights_table.setHorizontalHeaderLabels(["Clase de activo", "Peso %"])
        self.weights_table.verticalHeader().setVisible(False)
        # Las filas deben dar cabida al QComboBox con su padding; con menos, los
        # descendentes de la tipografía ("g", "y") salen cortados.
        self.weights_table.verticalHeader().setDefaultSectionSize(40)
        self.weights_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.weights_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.weights_table.setColumnWidth(1, 90)
        self.weights_table.itemChanged.connect(self._on_weight_changed)
        column.addWidget(self.weights_table, 1)

        self.total_label = QLabel("")
        self.total_label.setWordWrap(True)  # la frase completa no cabe en una línea
        column.addWidget(self.total_label)

        # Vista agrupada: 59 sub-clases no se leen en comité, cuatro sí. Es
        # derivada y de solo lectura — los pesos se cargan por sub-clase, que es
        # el nivel al que existen retorno, volatilidad y correlación.
        grouped_label = QLabel("POR CLASE DE ACTIVO")
        grouped_label.setStyleSheet(
            f"color: {BLUE_MID}; font-weight: 600; letter-spacing: 2px; font-size: 12px;"
        )
        column.addWidget(grouped_label)

        self.grouped_table = QTableWidget(0, 2)
        self.grouped_table.setHorizontalHeaderLabels(["Clase de activo", "Peso %"])
        self.grouped_table.verticalHeader().setVisible(False)
        self.grouped_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grouped_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.grouped_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.grouped_table.verticalHeader().setDefaultSectionSize(26)
        grouped_header = self.grouped_table.horizontalHeader()
        grouped_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        grouped_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.grouped_table.setColumnWidth(1, 90)
        # Alto fijo: son cuatro grupos como mucho, y una tabla que estira le
        # robaria espacio a la de pesos, que es donde se trabaja.
        self.grouped_table.setMaximumHeight(5 * 26 + 34)
        column.addWidget(self.grouped_table)

        return tab

    # ------------------------------------------------------------------
    def reload(self, scenario: Scenario, cmas: CMASet, available: list[str],
               resolver=None):
        self.scenario = scenario
        self.cmas = cmas
        self.available = available
        if resolver is not None:
            self.resolver = resolver
        self._refresh_list()
        if self.scenario.strategies:
            self.selector.setCurrentIndex(0)
        self._render_current()

    def _refresh_list(self):
        current = self.selector.currentIndex()
        self._loading = True
        self.selector.clear()
        for i, strategy in enumerate(self.scenario.strategies):
            self.selector.addItem(strategy.name)
            self.selector.setItemData(
                i, f"Color de la serie: {series_color(i)}", Qt.ItemDataRole.ToolTipRole
            )
        self._loading = False
        if 0 <= current < self.selector.count():
            self.selector.setCurrentIndex(current)
        elif self.selector.count():
            self.selector.setCurrentIndex(0)

    @property
    def current(self) -> Strategy | None:
        row = self.selector.currentIndex()
        if 0 <= row < len(self.scenario.strategies):
            return self.scenario.strategies[row]
        return None

    def _on_select(self, _row: int):
        if self._loading:
            return
        self._render_current()

    def _update_badges(self, strategy: Strategy | None):
        """Resumen de lo que trae la estrategia, para no tener que abrir cada pestaña."""
        if strategy is None:
            self.badges.setText("Crea una estrategia para empezar.")
            return
        marks = []
        marks.append(
            f"{len(strategy.cashflows)} flujo(s)" if strategy.cashflows else "sin flujos"
        )
        marks.append("con crédito" if strategy.has_loan else "sin crédito")
        marks.append(
            "capital propio" if strategy.has_own_initial else "capital del escenario"
        )
        self.badges.setText(" · ".join(marks))

    def _render_current(self):
        strategy = self.current
        self._update_badges(strategy)
        self._render_weights(strategy)
        self.cashflow_panel.reload(self.scenario, strategy)
        self.leverage_panel.reload(self.scenario, strategy)
        self.capital_panel.reload(self.scenario, strategy)

    def _on_child_changed(self):
        """Un cambio en flujos, crédito o capital: solo refresca las marcas.

        **No se reconstruye el selector.** Ninguno de esos paneles cambia el
        nombre de una estrategia, así que la lista no tiene nada que actualizar;
        y reconstruirla movía el índice actual, lo que reemitía la selección y
        volvía a cargar el editor **en mitad de la edición**. El efecto visible
        era que la casilla de apalancamiento se desmarcaba sola en cuanto se
        pulsaba, para toda estrategia que no fuera la primera de la lista.
        """
        self._update_badges(self.current)
        self.changed.emit()

    # ------------------------------------------------------------------
    def _render_weights(self, strategy: Strategy | None):
        self._loading = True
        self.weights_table.setRowCount(0)
        if strategy is not None:
            names = list(strategy.weights)
            self.weights_table.setRowCount(len(names))
            for row, name in enumerate(names):
                self._set_weight_row(row, name, strategy.weights[name])
        self._loading = False
        self._update_total()

    def _set_weight_row(self, row: int, name: str, weight: float):
        combo = QComboBox()
        combo.addItems(self.available)
        if name in self.available:
            combo.setCurrentText(name)
        else:
            # Una clase que ya no está disponible (se borró de la librería, o el
            # caso viene de otra máquina). Se muestra para que se vea el problema.
            combo.insertItem(0, name)
            combo.setCurrentIndex(0)
        combo.currentTextChanged.connect(
            lambda text, r=row: self._on_asset_changed(r, text)
        )
        self.weights_table.setCellWidget(row, 0, combo)

        item = QTableWidgetItem(f"{weight * 100:.2f}")
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.weights_table.setItem(row, 1, item)

    def _row_asset_name(self, row: int) -> str | None:
        combo = self.weights_table.cellWidget(row, 0)
        return combo.currentText() if combo is not None else None

    def _on_asset_changed(self, row: int, new_name: str):
        """Cambiar la clase de una fila conserva su peso."""
        strategy = self.current
        if self._loading or strategy is None:
            return
        names = list(strategy.weights)
        if row >= len(names):
            return
        old_name = names[row]
        if new_name == old_name:
            return
        if new_name in strategy.weights:
            QMessageBox.warning(
                self,
                "Clase repetida",
                f"'{new_name}' ya está en esta estrategia. Ajusta su peso en su propia fila.",
            )
            self._render_weights(strategy)
            return
        # Se reconstruye el dict para conservar el orden de las filas.
        strategy.allocation.weights = {
            (new_name if k == old_name else k): v for k, v in strategy.weights.items()
        }
        self._render_weights(strategy)
        self.changed.emit()

    def _render_grouped(self, strategy: Strategy | None):
        grouped = (
            group_weights(strategy.weights, self.resolver)
            if strategy is not None
            else {}
        )
        self.grouped_table.setRowCount(len(grouped))
        for row, (name, weight) in enumerate(grouped.items()):
            label = QTableWidgetItem(name)
            self.grouped_table.setItem(row, 0, label)
            value = QTableWidgetItem(f"{weight * 100:.1f}")
            value.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.grouped_table.setItem(row, 1, value)

    def _update_total(self):
        strategy = self.current
        self._render_grouped(strategy)
        if strategy is None:
            self.total_label.setText(
                f"<span style='color:{INK_SOFT};'>Sin estrategia seleccionada.</span>"
            )
            return
        total = strategy.allocation.total * 100.0
        # Semáforo: el color vive dentro del círculo, nunca en el texto.
        if abs(total - 100.0) < 1e-4:
            self.total_label.setText(
                status_dot(STATUS_GOOD, f"Los pesos suman <b>{total:.2f}%</b>")
            )
        else:
            self.total_label.setText(
                status_dot(
                    STATUS_CRITICAL,
                    f"Los pesos suman <b>{total:.2f}%</b> — deben sumar 100% para simular",
                )
            )

    def _on_weight_changed(self, item: QTableWidgetItem):
        if self._loading or item.column() != 1:
            return
        strategy = self.current
        if strategy is None:
            return
        name = self._row_asset_name(item.row())
        if name is None:
            return
        try:
            value = float(item.text().replace(",", ".").replace("%", "").strip()) / 100.0
        except ValueError:
            self._loading = True
            item.setText(f"{strategy.weights.get(name, 0.0) * 100:.2f}")
            self._loading = False
            return
        if value < 0:
            QMessageBox.warning(self, "Peso inválido", "Los pesos no pueden ser negativos.")
            self._loading = True
            item.setText(f"{strategy.weights.get(name, 0.0) * 100:.2f}")
            self._loading = False
            return
        strategy.allocation.weights[name] = value
        self._update_total()
        self.changed.emit()

    # ------------------------------------------------------------------
    def _unique_name(self, base: str) -> str:
        existing = {s.name for s in self.scenario.strategies}
        if base not in existing:
            return base
        i = 2
        while f"{base} {i}" in existing:
            i += 1
        return f"{base} {i}"

    def _add_strategy(self):
        if len(self.scenario.strategies) >= MAX_SERIES:
            QMessageBox.information(
                self,
                "Demasiadas estrategias",
                f"La comparación admite hasta {MAX_SERIES} estrategias, que es el límite "
                "de tonos distinguibles de la gama de la marca.",
            )
            return
        name, ok = QInputDialog.getText(
            self, "Nueva estrategia", "Nombre:", text=self._unique_name("Estrategia")
        )
        if not ok or not name.strip():
            return
        if name.strip() in {s.name for s in self.scenario.strategies}:
            QMessageBox.warning(self, "Nombre repetido", "Ya existe una estrategia con ese nombre.")
            return
        self.scenario.strategies.append(Strategy(allocation=Allocation(name.strip(), {})))
        self._refresh_list()
        self.selector.setCurrentIndex(len(self.scenario.strategies) - 1)
        self._render_current()
        self.changed.emit()

    def _duplicate_strategy(self):
        strategy = self.current
        if strategy is None:
            return
        if len(self.scenario.strategies) >= MAX_SERIES:
            QMessageBox.information(
                self, "Demasiadas estrategias", f"El máximo es {MAX_SERIES}."
            )
            return
        name, ok = QInputDialog.getText(
            self,
            "Duplicar estrategia",
            "Nombre:",
            text=self._unique_name(f"{strategy.name} (copia)"),
        )
        if not ok or not name.strip():
            return
        if name.strip() in {s.name for s in self.scenario.strategies}:
            QMessageBox.warning(self, "Nombre repetido", "Ya existe una estrategia con ese nombre.")
            return
        # Copia profunda: editar el duplicado no debe tocar el original.
        self.scenario.strategies.append(strategy.copy(name.strip()))
        self._refresh_list()
        self.selector.setCurrentIndex(len(self.scenario.strategies) - 1)
        self._render_current()
        self.changed.emit()

    def _rename_strategy(self):
        strategy = self.current
        if strategy is None:
            return
        name, ok = QInputDialog.getText(
            self, "Renombrar estrategia", "Nombre:", text=strategy.name
        )
        if not ok or not name.strip() or name.strip() == strategy.name:
            return
        if name.strip() in {s.name for s in self.scenario.strategies}:
            QMessageBox.warning(self, "Nombre repetido", "Ya existe una estrategia con ese nombre.")
            return
        strategy.name = name.strip()
        self._refresh_list()
        self._render_current()
        self.changed.emit()

    def _remove_strategy(self):
        row = self.selector.currentIndex()
        if not 0 <= row < len(self.scenario.strategies):
            return
        name = self.scenario.strategies[row].name
        if QMessageBox.question(
            self,
            "Eliminar estrategia",
            f"¿Eliminar '{name}' con sus flujos y su crédito?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.scenario.strategies.pop(row)
        self._refresh_list()
        self._render_current()
        self.changed.emit()

    def _remove_all_strategies(self):
        """Vacía la comparación para empezar de cero sin crear un caso nuevo.

        A diferencia de «Nuevo caso», conserva capital, horizonte e inflación:
        lo normal al rehacer una comparación es cambiar las estrategias, no el
        escenario.
        """
        total = len(self.scenario.strategies)
        if not total:
            return
        if QMessageBox.question(
            self,
            "Borrar todas las estrategias",
            f"¿Borrar las {total} estrategias con sus pesos, flujos y créditos?\n\n"
            "El capital, el horizonte y la inflación del escenario se conservan. "
            "Esto no se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.scenario.strategies.clear()
        self._refresh_list()
        self._render_current()
        self.changed.emit()

    # ------------------------------------------------------------------
    def _add_asset_row(self):
        strategy = self.current
        if strategy is None:
            QMessageBox.information(self, "Sin estrategia", "Crea primero una estrategia.")
            return
        libres = [n for n in self.available if n not in strategy.weights]
        if not libres:
            QMessageBox.information(
                self,
                "Sin clases disponibles",
                "Esta estrategia ya usa todas las clases de activo disponibles.",
            )
            return
        strategy.allocation.weights[libres[0]] = 0.0
        self._render_weights(strategy)
        self.weights_table.setCurrentCell(self.weights_table.rowCount() - 1, 1)
        self.changed.emit()

    def _remove_asset_row(self):
        strategy = self.current
        row = self.weights_table.currentRow()
        if strategy is None or row < 0:
            return
        name = self._row_asset_name(row)
        if name is None:
            return
        strategy.allocation.weights.pop(name, None)
        self._render_weights(strategy)
        self.changed.emit()

    def _normalize(self):
        strategy = self.current
        if strategy is None or strategy.allocation.total <= 0:
            return
        total = strategy.allocation.total
        for name in strategy.allocation.weights:
            strategy.allocation.weights[name] /= total
        self._render_weights(strategy)
        self.changed.emit()
