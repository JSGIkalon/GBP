"""Metas del cliente: una tabla chica, vacía por defecto.

Es opcional a propósito. Un caso sin metas se ve y se simula igual que antes de
que existieran; con metas, aparece una pestaña de resultados que dice la
probabilidad de cumplir cada una en cada estrategia.
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

from ...model.goals import Goal
from ..theme import (
    NOTE_STYLE,
    SECTION_STYLE,
    format_money,
)

COLUMNS = ["Meta", "Monto", "Moneda", "Año", "Moneda de hoy"]
COL_NAME, COL_AMOUNT, COL_CURRENCY, COL_YEAR, COL_REAL = range(5)
FINAL = "final"


class GoalsPanel(QWidget):
    changed = Signal()

    def __init__(self, goals: list[Goal], parent=None):
        super().__init__(parent)
        self.goals = goals
        self._loading = False
        self.horizon: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Metas (opcional)")
        title.setStyleSheet(SECTION_STYLE)
        layout.addWidget(title)

        intro = QLabel(
            "Patrimonio mínimo en un año —o al final, como legado—. No cambian la "
            "simulación: se mide qué fracción de los caminos las cumple sin haberse "
            "agotado antes. Sin metas, todo queda como siempre."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(NOTE_STYLE)
        layout.addWidget(intro)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(COLUMNS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        # El combo de moneda es un widget de celda: «ajustar al contenido» no lo
        # mide y la columna quedaba cortando «COP». Ancho fijo suficiente.
        header.setSectionResizeMode(COL_CURRENCY, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(COL_CURRENCY, 84)
        self.table.setMinimumHeight(120)
        self.table.setMaximumHeight(200)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

        # Metas cuyo año cae después del horizonte: no se ajustan solas, se avisa.
        self.horizon_note = QLabel("")
        self.horizon_note.setWordWrap(True)
        self.horizon_note.setStyleSheet(NOTE_STYLE)
        self.horizon_note.setVisible(False)
        layout.addWidget(self.horizon_note)

        buttons = QHBoxLayout()
        add = QPushButton("Agregar meta")
        add.clicked.connect(self._add)
        remove = QPushButton("Quitar seleccionada")
        remove.clicked.connect(self._remove)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.reload(goals)

    def reload(self, goals: list[Goal]):
        self.goals = goals
        self._loading = True
        self.table.setRowCount(len(goals))
        for row, goal in enumerate(goals):
            self._set_row(row, goal)
        self._loading = False
        self._update_horizon_note()

    def set_horizon(self, horizon: int):
        self.horizon = horizon
        self._update_horizon_note()

    def _update_horizon_note(self):
        fuera = [
            g for g in self.goals
            if self.horizon and g.year is not None and g.year > self.horizon
        ]
        if fuera:
            self.horizon_note.setText(
                "Fuera del horizonte de " + f"{self.horizon} años, no se evalúan: "
                + ", ".join(f"{g.name} (año {g.year})" for g in fuera)
                + ". Cambia su año o alarga el horizonte."
            )
        self.horizon_note.setVisible(bool(fuera))

    def _set_row(self, row: int, goal: Goal):
        values = {
            COL_NAME: goal.name,
            COL_AMOUNT: format_money(goal.amount),
            COL_YEAR: FINAL if goal.year is None else str(goal.year),
        }
        for col, text in values.items():
            item = QTableWidgetItem(text)
            if col != COL_NAME:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if col == COL_YEAR:
                item.setToolTip("Un año del horizonte, o «final» para medirla en el último año.")
            self.table.setItem(row, col, item)

        # Solo una casilla: sin quitarle `ItemIsEditable`, un doble clic abría
        # un campo de texto vacío debajo de la casilla que no servía para nada.
        real = QTableWidgetItem()
        real.setFlags(
            (real.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable
        )
        real.setCheckState(Qt.CheckState.Checked if goal.real else Qt.CheckState.Unchecked)
        real.setToolTip(
            "Marcado: el monto está en poder adquisitivo de hoy. Sin marcar: en "
            "valores nominales de ese año."
        )
        self.table.setItem(row, COL_REAL, real)

        currency = QComboBox()
        currency.addItems(["USD", "COP"])
        currency.setCurrentText(goal.currency)
        currency.setToolTip(
            "COP: el monto se convierte a USD con la tasa y la devaluación de la "
            "sección «Pesos colombianos» de Escenario."
        )
        currency.currentTextChanged.connect(
            lambda code, g=goal: self._set_currency(g, code)
        )
        self.table.setCellWidget(row, COL_CURRENCY, currency)

    def _set_currency(self, goal: Goal, code: str):
        if self._loading or goal.currency == code:
            return
        goal.currency = code
        self.changed.emit()

    def _add(self):
        self.goals.append(Goal(name=f"Meta {len(self.goals) + 1}", amount=0.0))
        self.reload(self.goals)
        self.changed.emit()

    def _remove(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.goals):
            del self.goals[row]
            self.reload(self.goals)
            self.changed.emit()

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._loading:
            return
        row, col = item.row(), item.column()
        if row >= len(self.goals):
            return
        goal = self.goals[row]
        text = item.text().strip()
        try:
            if col == COL_NAME:
                goal.name = text or goal.name
            elif col == COL_AMOUNT:
                # Un monto es entero: puntos y comas son separadores de miles.
                value = float(text.replace(".", "").replace(",", "") or 0)
                if value < 0:
                    raise ValueError("negativo")
                goal.amount = value
            elif col == COL_YEAR:
                if text.lower() in ("", FINAL, "fin"):
                    goal.year = None
                else:
                    year = int(float(text))
                    if year < 1:
                        raise ValueError("año")
                    goal.year = year
            elif col == COL_REAL:
                goal.real = item.checkState() == Qt.CheckState.Checked
        except ValueError:
            pass  # se revierte al repintar la fila
        self._loading = True
        self._set_row(row, goal)
        self._loading = False
        self._update_horizon_note()
        self.changed.emit()
