"""Ventana de optimización del portafolio.

Se abre desde «Optimizar portafolio» y **no toca el caso**: muestra las tres
alternativas lado a lado contra el portafolio actual de la estrategia elegida, y
solo cambia algo cuando se pulsa un botón «Aplicar». Al aplicar, la ventana
principal vuelve a simular, así que gráficos, tablas, indicadores y probabilidad
de éxito salen de una corrida nueva.

Una sola estrategia a la vez: si en el panel principal hay varias visibles, se
optimiza la que se elige arriba —por defecto la primera visible— y la ventana lo
dice. Nunca se combinan estrategias en un cálculo.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..engine.optimizer import (
    MAX_EFFICIENCY,
    MAX_RETURN,
    MIN_VOLATILITY,
    OBJECTIVES,
    OptimizationError,
    optimize,
)
from .table_copy import enable_copy
from .theme import INK, NOTE_STYLE, SECTION_STYLE

ORDER = (MAX_RETURN, MIN_VOLATILITY, MAX_EFFICIENCY)
COL_USE, COL_NAME, COL_CURRENCY, COL_CURRENT, COL_MIN, COL_MAX = range(6)


def _pct(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _parse_pct(text: str, default: float) -> float:
    text = text.replace("%", "").replace(",", ".").strip()
    if not text:
        return default
    return float(text) / 100.0


class OptimizerDialog(QDialog):
    def __init__(self, main, parent=None):
        super().__init__(parent or main)
        self.main = main
        self.report = None
        self.setWindowTitle("Optimizar portafolio")
        self.setMinimumSize(760, 560)
        self.resize(1080, 760)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Busca los pesos de los activos que selecciones con tres criterios. Usa los "
            "supuestos de la app (LTCMA y activos propios) y su matriz de correlación. "
            "No cambia el caso: revisa las alternativas y aplica la que quieras."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {INK};")
        layout.addWidget(intro)

        form = QFormLayout()
        self.strategy_box = QComboBox()
        names = [s.name for s in main.scenario.strategies]
        self.strategy_box.addItems(names)
        visible = [n for n in getattr(main, "visible_strategies", names) if n in names]
        if visible:
            self.strategy_box.setCurrentText(visible[0])
        self.strategy_box.currentIndexChanged.connect(self._fill_assets)
        form.addRow("Estrategia a optimizar", self.strategy_box)
        layout.addLayout(form)

        self.scope_note = QLabel("")
        self.scope_note.setWordWrap(True)
        self.scope_note.setStyleSheet(NOTE_STYLE)
        layout.addWidget(self.scope_note)
        if len(visible) > 1:
            self.scope_note.setText(
                f"Hay {len(visible)} estrategias visibles en el panel principal. Se "
                "optimiza solo la elegida arriba; para otra, cámbiala en la lista. "
                "Las estrategias no se combinan en un mismo cálculo."
            )

        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter, 1)

        # --- Activos -----------------------------------------------------
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Activos a considerar")
        title.setStyleSheet(SECTION_STYLE)
        top_layout.addWidget(title)
        self.show_all = QCheckBox("Mostrar todos los activos de la librería")
        self.show_all.toggled.connect(self._fill_assets)
        top_layout.addWidget(self.show_all)
        self.assets_table = QTableWidget(0, 6)
        self.assets_table.setHorizontalHeaderLabels(
            ["Usar", "Activo", "Moneda", "Peso actual", "Mín. %", "Máx. %"]
        )
        self.assets_table.verticalHeader().setVisible(False)
        header = self.assets_table.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for col in (COL_USE, COL_CURRENCY, COL_CURRENT, COL_MIN, COL_MAX):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        top_layout.addWidget(self.assets_table, 1)
        bounds_note = QLabel(
            "Mín. y Máx. son límites opcionales por activo (por defecto 0% y 100%). "
            "Los activos sin marcar quedan en 0%."
        )
        bounds_note.setWordWrap(True)
        bounds_note.setStyleSheet(NOTE_STYLE)
        top_layout.addWidget(bounds_note)
        run_row = QHBoxLayout()
        self.run_button = QPushButton("Calcular alternativas")
        self.run_button.setObjectName("runButton")
        self.run_button.clicked.connect(self.run)
        run_row.addWidget(self.run_button)
        run_row.addStretch(1)
        top_layout.addLayout(run_row)
        splitter.addWidget(top)

        # --- Resultados --------------------------------------------------
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        self.context_label = QLabel("")
        self.context_label.setWordWrap(True)
        self.context_label.setStyleSheet(f"color: {INK};")
        bottom_layout.addWidget(self.context_label)
        self.results_table = QTableWidget(0, 5)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        enable_copy(self.results_table)
        bottom_layout.addWidget(self.results_table, 1)
        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet(f"color: {INK};")
        bottom_layout.addWidget(self.message_label)
        self.assumptions_label = QLabel("")
        self.assumptions_label.setWordWrap(True)
        self.assumptions_label.setStyleSheet(NOTE_STYLE)
        bottom_layout.addWidget(self.assumptions_label)

        apply_row = QHBoxLayout()
        apply_row.addWidget(QLabel("Alternativa:"))
        self.choice_box = QComboBox()
        apply_row.addWidget(self.choice_box, 1)
        self.apply_button = QPushButton("Aplicar a la estrategia")
        self.apply_button.setToolTip(
            "Reemplaza los pesos de la estrategia elegida y vuelve a simular. Sus "
            "flujos, crédito y capital no cambian."
        )
        self.apply_button.clicked.connect(lambda: self._apply(as_new=False))
        self.add_button = QPushButton("Agregar como estrategia nueva")
        self.add_button.setToolTip(
            "Crea una copia de la estrategia con estos pesos, para compararla con la "
            "original en la misma corrida."
        )
        self.add_button.clicked.connect(lambda: self._apply(as_new=True))
        apply_row.addWidget(self.apply_button)
        apply_row.addWidget(self.add_button)
        bottom_layout.addLayout(apply_row)
        splitter.addWidget(bottom)
        splitter.setSizes([320, 420])

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.reject)
        close_row.addWidget(close)
        layout.addLayout(close_row)

        self._fill_assets()
        self._set_apply_enabled(False)

    # ------------------------------------------------------------------
    @property
    def strategy(self):
        name = self.strategy_box.currentText()
        return next((s for s in self.main.scenario.strategies if s.name == name), None)

    def _fill_assets(self, *_):
        strategy = self.strategy
        current = dict(strategy.weights) if strategy is not None else {}
        available = list(self.main.available_assets)
        used = [n for n in current if n in available and current[n] > 0]
        names = used + ([n for n in available if n not in used] if self.show_all.isChecked()
                        else [])
        table = self.assets_table
        table.setRowCount(len(names))
        for row, name in enumerate(names):
            use = QTableWidgetItem()
            use.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            use.setCheckState(Qt.CheckState.Checked if name in used else Qt.CheckState.Unchecked)
            table.setItem(row, COL_USE, use)
            for col, text in ((COL_NAME, name),
                              (COL_CURRENCY, self.main.cmas.by_name(name).currency),
                              (COL_CURRENT, _pct(current.get(name, 0.0), 1))):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if col == COL_CURRENT:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row, col, item)
            for col, text in ((COL_MIN, "0"), (COL_MAX, "100")):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row, col, item)
        self.report = None
        self.results_table.setRowCount(0)
        self.context_label.setText("")
        self.assumptions_label.setText("")
        self.message_label.setText(
            "La estrategia no tiene pesos: marca «Mostrar todos los activos» y elige "
            "cuáles usar." if not used else ""
        )
        self._set_apply_enabled(False)

    def selection(self) -> tuple[list[str], dict[str, tuple[float, float]]]:
        """Activos marcados y sus límites. Levanta `ValueError` con el motivo."""
        names, bounds = [], {}
        for row in range(self.assets_table.rowCount()):
            if self.assets_table.item(row, COL_USE).checkState() != Qt.CheckState.Checked:
                continue
            name = self.assets_table.item(row, COL_NAME).text()
            try:
                lo = _parse_pct(self.assets_table.item(row, COL_MIN).text(), 0.0)
                hi = _parse_pct(self.assets_table.item(row, COL_MAX).text(), 1.0)
            except ValueError:
                raise ValueError(f"{name}: los límites deben ser números en %.") from None
            names.append(name)
            bounds[name] = (lo, hi)
        return names, bounds

    def set_checked(self, names: list[str]):
        """Marca exactamente esos activos (los muestra todos si hace falta)."""
        if any(n not in self._listed() for n in names):
            self.show_all.setChecked(True)
        for row in range(self.assets_table.rowCount()):
            name = self.assets_table.item(row, COL_NAME).text()
            self.assets_table.item(row, COL_USE).setCheckState(
                Qt.CheckState.Checked if name in names else Qt.CheckState.Unchecked
            )

    def _listed(self) -> list[str]:
        return [self.assets_table.item(r, COL_NAME).text()
                for r in range(self.assets_table.rowCount())]

    # ------------------------------------------------------------------
    def run(self):
        strategy = self.strategy
        self.report = None
        self._set_apply_enabled(False)
        self.results_table.setRowCount(0)
        if strategy is None:
            self.message_label.setText("Elige una estrategia.")
            return
        try:
            names, bounds = self.selection()
            if not names:
                raise OptimizationError(
                    "No hay activos seleccionados. Marca al menos uno en «Usar»; con uno "
                    "solo, su peso es 100%."
                )
            self.report = optimize(
                self.main.scenario, strategy.name, names, self.main.cmas,
                self.main.correlations, bounds,
            )
        except ValueError as exc:
            self.message_label.setText(f"No se pudo optimizar: {exc}")
            self.context_label.setText("")
            self.assumptions_label.setText("")
            return
        self._show_report()

    def _show_report(self):
        report = self.report
        self.context_label.setText(
            f"<b>Estrategia:</b> {report.strategy_name} · <b>Moneda base:</b> "
            f"{report.base_currency} · <b>Tasa:</b> "
            + (report.fx_description if report.cop_assets else "no aplica (todo en USD)")
            + " · <b>Riesgo cambiario:</b> no incluido"
        )
        columns = ["", "Actual", *(OBJECTIVES[k] for k in ORDER)]
        table = self.results_table
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(columns)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        outcomes = [report.outcomes.get(k) for k in ORDER]
        stats = [report.current, *(o.stats if o is not None else None for o in outcomes)]
        current_weights = dict(self.strategy.weights) if self.strategy else {}
        current_total = sum(current_weights.values()) or 1.0

        def metric(getter, fmt):
            return [fmt(getter(s)) if s is not None else "—" for s in stats]

        def ratio(s):
            return s.ratio if s.ratio_defined else None

        rows: list[tuple[str, list[str], bool]] = [
            ("Retorno esperado (aritmético anual)", metric(lambda s: s.expected_return, _pct), True),
            ("Retorno compuesto anual", metric(lambda s: s.compound_return, _pct), False),
            ("Volatilidad anual", metric(lambda s: s.volatility, _pct), True),
            ("Retorno / volatilidad",
             metric(ratio, lambda v: "no definida" if v is None else f"{v:.3f}"), True),
        ]
        # Activos del portafolio actual que no se seleccionaron: el actual los
        # tiene, las alternativas no (0%).
        assets = list(report.assets) + [n for n in current_weights
                                        if n not in report.assets and current_weights[n] > 0]
        for name in assets:
            cells = [_pct(current_weights.get(name, 0.0) / current_total, 1)]
            for s in stats[1:]:
                cells.append("—" if s is None else _pct(s.weights.get(name, 0.0), 1))
            suffix = "" if name in report.assets else " (no seleccionado)"
            rows.append((f"Peso · {name}{suffix}", cells, False))

        table.setRowCount(len(rows))
        bold = QFont(table.font())
        bold.setWeight(QFont.Weight.DemiBold)
        for r, (label, cells, strong) in enumerate(rows):
            item = QTableWidgetItem(label)
            if strong:
                item.setFont(bold)
            table.setItem(r, 0, item)
            for c, text in enumerate(cells, start=1):
                cell = QTableWidgetItem(text)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if strong:
                    cell.setFont(bold)
                table.setItem(r, c, cell)

        problems = [f"{o.label}: {o.message}" for o in outcomes if o is not None and not o.ok]
        self.message_label.setText(
            "<br>".join(problems) if problems else
            "Las tres alternativas suman 100%, sin pesos negativos ni apalancamiento."
        )
        self.assumptions_label.setText(
            "Supuestos: " + " ".join(f"• {a}" for a in report.assumptions)
        )
        self.choice_box.clear()
        for key, outcome in zip(ORDER, outcomes):
            if outcome is not None and outcome.ok:
                self.choice_box.addItem(outcome.label, key)
        self._set_apply_enabled(self.choice_box.count() > 0)

    def _set_apply_enabled(self, enabled: bool):
        self.apply_button.setEnabled(enabled)
        self.add_button.setEnabled(enabled)
        self.choice_box.setEnabled(enabled)

    def _apply(self, as_new: bool):
        if self.report is None or self.choice_box.count() == 0:
            return
        key = self.choice_box.currentData()
        outcome = self.report.outcomes[key]
        if not as_new:
            answer = QMessageBox.question(
                self, "Aplicar alternativa",
                f"Se reemplazarán los pesos de «{self.report.strategy_name}» por los de "
                f"«{outcome.label}» y se volverá a simular. Sus flujos, crédito y capital "
                "no cambian. ¿Continuar?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.main.apply_optimization(
            self.report.strategy_name, outcome.stats.weights, outcome.label, as_new=as_new
        )
        self.accept()

