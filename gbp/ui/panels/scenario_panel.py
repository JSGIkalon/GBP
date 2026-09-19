"""Panel del escenario: nombre, capital inicial, horizonte e inflación."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...model.scenario import Scenario
from ..theme import INK_SOFT, STATUS_WARNING, format_money, status_dot


class ScenarioPanel(QWidget):
    """Datos generales del caso del cliente."""

    changed = Signal()
    # La confirmación y el vaciado los hace la ventana: el panel solo pide.
    reset_requested = Signal()

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

        # El campo está en unidades, no en millones, y eso no se ve: escribir
        # "40" queriendo decir 40 millones deja un caso de cuarenta dólares que
        # proyecta en negativo desde el primer año, sin ningún aviso. El eco
        # formateado lo hace evidente mientras se escribe.
        self.initial_hint = QLabel("")
        self.initial_hint.setWordWrap(True)
        form.addRow("", self.initial_hint)

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

        # Empezar de cero tiene que ser un botón visible, no una entrada de menú.
        # La app abre la primera vez con el caso de ejemplo y desde entonces
        # restaura la sesión anterior, así que sin esto las tres estrategias de
        # ejemplo vuelven para siempre y no hay forma de sacarlas todas juntas.
        reset_note = QLabel(
            "Vacía el caso por completo —capital, horizonte, inflación y todas las "
            "estrategias— y olvida la sesión guardada. Los supuestos de mercado no "
            "se tocan."
        )
        reset_note.setWordWrap(True)
        reset_note.setStyleSheet(f"color: {INK_SOFT};")
        layout.addWidget(reset_note)

        self.reset_button = QPushButton("Empezar de cero")
        self.reset_button.clicked.connect(self.reset_requested.emit)
        row = QHBoxLayout()
        row.addWidget(self.reset_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.reload(scenario)

    def reload(self, scenario: Scenario):
        self.scenario = scenario
        self._loading = True
        self.name_edit.setText(scenario.name)
        self.initial_value.setValue(scenario.initial_value)
        self.horizon.setValue(scenario.horizon)
        self.inflation.setValue(scenario.inflation * 100.0)
        self._loading = False
        self._update_initial_hint()

    def _update_initial_hint(self):
        """Eco del capital en la escala legible, y aviso si parece un desliz.

        Un capital por debajo de mil no es imposible, pero en esta herramienta
        casi siempre es alguien que escribió los millones sin los ceros. Se
        avisa, no se impide: el semáforo dice lo que pasa y deja decidir.
        """
        value = self.initial_value.value()
        if value <= 0:
            self.initial_hint.setText(
                f"<span style='color:{INK_SOFT};'>Sin capital inicial. La estrategia "
                "necesita capital o aportes para poder simular.</span>"
            )
        elif value < 1_000:
            self.initial_hint.setText(
                status_dot(
                    STATUS_WARNING,
                    f"Son <b>{value:,.0f}</b> — el campo está en unidades, no en "
                    f"millones. Para {value:,.0f} millones escribe "
                    f"<b>{value * 1_000_000:,.0f}</b>.",
                )
            )
        else:
            self.initial_hint.setText(
                f"<span style='color:{INK_SOFT};'>= {format_money(value)}</span>"
            )

    def _on_change(self, *_):
        if self._loading:
            return
        self.scenario.name = self.name_edit.text().strip() or "Caso sin título"
        self.scenario.initial_value = self.initial_value.value()
        self.scenario.horizon = self.horizon.value()
        self.scenario.inflation = self.inflation.value() / 100.0
        self._update_initial_hint()
        self.changed.emit()
