"""Panel de capital propio de una estrategia.

Por defecto todas las estrategias arrancan con el capital del escenario, que es
lo que mantiene honesta la comparación: mismo punto de partida, distinta
estrategia. Marcar la casilla permite darle a esta estrategia un capital propio,
para el caso menos común de comparar planes que parten de montos distintos.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ...model.scenario import Scenario
from ...model.strategy import Strategy
from ..theme import INK_SOFT, format_money


class CapitalPanel(QWidget):
    """Capital inicial heredado del escenario o propio de la estrategia."""

    changed = Signal()

    def __init__(self, scenario: Scenario, strategy: Strategy | None = None, parent=None):
        super().__init__(parent)
        self.scenario = scenario
        self.strategy = strategy
        self._loading = False

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Lo normal es que todas las estrategias partan del mismo capital: así la "
            "comparación mide la estrategia y no el punto de partida."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #3D5560;")
        layout.addWidget(intro)

        self.inherited = QLabel("")
        self.inherited.setWordWrap(True)
        self.inherited.setStyleSheet(f"color: {INK_SOFT};")
        layout.addWidget(self.inherited)

        form = QFormLayout()
        form.setSpacing(10)

        self.use_own = QCheckBox("Usar un capital inicial propio para esta estrategia")
        self.use_own.stateChanged.connect(self._on_change)
        form.addRow("", self.use_own)

        self.amount = QDoubleSpinBox()
        self.amount.setRange(0.0, 1e13)
        self.amount.setDecimals(0)
        self.amount.setGroupSeparatorShown(True)
        self.amount.setSingleStep(1_000_000)
        self.amount.valueChanged.connect(self._on_change)
        form.addRow("Capital inicial propio", self.amount)

        layout.addLayout(form)

        note = QLabel(
            "El horizonte y la inflación siempre vienen del escenario: son el eje común "
            "de la comparación y no se pueden cambiar por estrategia."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {INK_SOFT};")
        layout.addWidget(note)
        layout.addStretch(1)

        self.reload(scenario, strategy)

    def reload(self, scenario: Scenario, strategy: Strategy | None = None):
        self.scenario = scenario
        self.strategy = strategy
        self.setEnabled(strategy is not None)

        self._loading = True
        own = strategy.initial_value if strategy is not None else None
        self.use_own.setChecked(own is not None)
        self.amount.setValue(own if own is not None else scenario.initial_value)
        self.amount.setEnabled(own is not None)
        self._loading = False

        self.inherited.setText(
            f"Capital del escenario: {format_money(scenario.initial_value)}"
        )

    def _on_change(self, *_):
        if self._loading or self.strategy is None:
            return
        self.amount.setEnabled(self.use_own.isChecked())
        self.strategy.initial_value = (
            self.amount.value() if self.use_own.isChecked() else None
        )
        self.changed.emit()
