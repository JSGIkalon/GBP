"""Panel del escenario: nombre, capital inicial, horizonte e inflación."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...model.scenario import Scenario


class ScenarioPanel(QWidget):
    """Datos generales del caso del cliente."""

    changed = Signal()

    def __init__(self, scenario: Scenario, parent=None):
        super().__init__(parent)
        self.scenario = scenario
        self._loading = False

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Datos del caso. Se guardan en el archivo del cliente, no en la librería "
            "de supuestos."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #1F2A30;")
        layout.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(10)

        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._on_change)
        form.addRow("Nombre del caso", self.name_edit)

        self.initial_value = QDoubleSpinBox()
        self.initial_value.setRange(0.0, 1e13)
        self.initial_value.setDecimals(0)
        self.initial_value.setGroupSeparatorShown(True)
        self.initial_value.setSingleStep(1_000_000)
        self.initial_value.valueChanged.connect(self._on_change)
        form.addRow("Capital inicial", self.initial_value)

        self.horizon = QSpinBox()
        self.horizon.setRange(1, 100)
        self.horizon.setSuffix(" años")
        self.horizon.valueChanged.connect(self._on_change)
        form.addRow("Horizonte del análisis", self.horizon)

        self.inflation = QDoubleSpinBox()
        self.inflation.setRange(-10.0, 50.0)
        self.inflation.setDecimals(2)
        self.inflation.setSuffix(" %")
        self.inflation.setSingleStep(0.1)
        self.inflation.valueChanged.connect(self._on_change)
        form.addRow("Inflación anual", self.inflation)

        layout.addLayout(form)

        note = QLabel(
            "La inflación indexa los flujos marcados como tales y permite ver los "
            "resultados en poder adquisitivo de hoy."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #5C6770;")
        layout.addWidget(note)
        layout.addStretch(1)

        self.reload(scenario)

    def reload(self, scenario: Scenario):
        self.scenario = scenario
        self._loading = True
        self.name_edit.setText(scenario.name)
        self.initial_value.setValue(scenario.initial_value)
        self.horizon.setValue(scenario.horizon)
        self.inflation.setValue(scenario.inflation * 100.0)
        self._loading = False

    def _on_change(self, *_):
        if self._loading:
            return
        self.scenario.name = self.name_edit.text().strip() or "Caso sin título"
        self.scenario.initial_value = self.initial_value.value()
        self.scenario.horizon = self.horizon.value()
        self.scenario.inflation = self.inflation.value() / 100.0
        self.changed.emit()
