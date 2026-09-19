"""Panel de apalancamiento: condiciones del crédito de **una estrategia**.

El crédito es de la estrategia, no del escenario: se puede comparar un plan
apalancado contra uno sin deuda en la misma corrida y sobre los mismos sorteos
de mercado.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...model.leverage import Amortization, InterestMode, LoanTerms, RateMode
from ...model.scenario import Scenario
from ...model.strategy import Strategy
from ..theme import STATUS_WARNING, status_dot


class LeveragePanel(QWidget):
    """Condiciones del crédito de una estrategia."""

    changed = Signal()

    def __init__(self, scenario: Scenario, strategy: Strategy | None = None, parent=None):
        super().__init__(parent)
        self.scenario = scenario
        self.strategy = strategy
        self._loading = False

        layout = QVBoxLayout(self)

        self.enabled = QCheckBox("Esta estrategia usa apalancamiento")
        self.enabled.stateChanged.connect(self._on_toggle)
        layout.addWidget(self.enabled)

        self.box = QGroupBox("Condiciones del crédito")
        form = QFormLayout(self.box)
        form.setSpacing(10)

        self.name = QLineEdit()
        self.name.textChanged.connect(self._on_change)
        form.addRow("Nombre", self.name)

        self.principal = QDoubleSpinBox()
        self.principal.setRange(0.0, 1e13)
        self.principal.setDecimals(0)
        self.principal.setGroupSeparatorShown(True)
        self.principal.setSingleStep(1_000_000)
        self.principal.valueChanged.connect(self._on_change)
        form.addRow("Monto del crédito", self.principal)

        self.start_year = QSpinBox()
        self.start_year.setRange(1, 100)
        self.start_year.valueChanged.connect(self._on_change)
        form.addRow("Año de desembolso", self.start_year)

        self.term_years = QSpinBox()
        self.term_years.setRange(1, 100)
        self.term_years.setSuffix(" años")
        self.term_years.valueChanged.connect(self._on_change)
        form.addRow("Plazo", self.term_years)

        self.rate_mode = QComboBox()
        self.rate_mode.addItems([RateMode.FIXED.value, RateMode.SPREAD_OVER_CASH.value])
        self.rate_mode.currentTextChanged.connect(self._on_change)
        form.addRow("Tipo de tasa", self.rate_mode)

        self.rate = QDoubleSpinBox()
        self.rate.setRange(-50.0, 100.0)
        self.rate.setDecimals(2)
        self.rate.setSuffix(" %")
        self.rate.setSingleStep(0.25)
        self.rate.valueChanged.connect(self._on_change)
        form.addRow("Tasa fija anual", self.rate)

        self.spread = QDoubleSpinBox()
        self.spread.setRange(-50.0, 100.0)
        self.spread.setDecimals(2)
        self.spread.setSuffix(" %")
        self.spread.setSingleStep(0.25)
        self.spread.valueChanged.connect(self._on_change)
        form.addRow("Spread sobre la tasa de caja", self.spread)

        self.interest_mode = QComboBox()
        self.interest_mode.addItems([InterestMode.PAID.value, InterestMode.CAPITALIZED.value])
        self.interest_mode.currentTextChanged.connect(self._on_change)
        form.addRow("Intereses", self.interest_mode)

        self.amortization = QComboBox()
        self.amortization.addItems([a.value for a in Amortization])
        self.amortization.currentTextChanged.connect(self._on_change)
        form.addRow("Amortización", self.amortization)

        self.use_ltv = QCheckBox("Controlar LTV (llamada a margen)")
        self.use_ltv.stateChanged.connect(self._on_change)
        form.addRow("", self.use_ltv)

        self.max_ltv = QDoubleSpinBox()
        self.max_ltv.setRange(1.0, 99.0)
        self.max_ltv.setDecimals(1)
        self.max_ltv.setSuffix(" %")
        self.max_ltv.valueChanged.connect(self._on_change)
        form.addRow("LTV máximo", self.max_ltv)

        self.target_ltv = QDoubleSpinBox()
        self.target_ltv.setRange(1.0, 99.0)
        self.target_ltv.setDecimals(1)
        self.target_ltv.setSuffix(" %")
        self.target_ltv.valueChanged.connect(self._on_change)
        form.addRow("LTV objetivo tras la llamada", self.target_ltv)

        layout.addWidget(self.box)

        # Un crédito marcado pero con monto 0 no hace nada en la simulación, y
        # eso no se ve por ningún lado. Se dice aquí en vez de impedirlo: al
        # marcar la casilla el monto siempre arranca en 0.
        self.warning = QLabel("")
        self.warning.setWordWrap(True)
        layout.addWidget(self.warning)

        note = QLabel(
            "La amortización se calcula sobre el principal original con una tasa de "
            "referencia fija, de modo que la cuota no cambie entre escenarios. Si los "
            "intereses se capitalizan, el saldo remanente se cancela íntegro al vencimiento."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #5C6770;")
        layout.addWidget(note)
        layout.addStretch(1)

        self.reload(scenario, strategy)

    # ------------------------------------------------------------------
    def reload(self, scenario: Scenario, strategy: Strategy | None = None):
        self.scenario = scenario
        self.strategy = strategy
        self.setEnabled(strategy is not None)
        loan = strategy.loan if strategy is not None else None
        self._loading = True
        # La casilla refleja si la estrategia **tiene** crédito, no si su monto
        # ya es mayor que cero: al marcarla el monto todavía es 0 y con la
        # condición anterior la casilla se desmarcaba sola antes de poder
        # escribir nada. Que un crédito de monto 0 no afecte la simulación lo
        # decide `LoanTerms.active`, no esta pantalla.
        self.enabled.setChecked(loan is not None)
        loan = loan or LoanTerms()
        self.name.setText(loan.name)
        self.principal.setValue(loan.principal)
        self.start_year.setValue(loan.start_year)
        self.term_years.setValue(loan.term_years)
        self.rate_mode.setCurrentText(loan.rate_mode.value)
        self.rate.setValue(loan.rate * 100.0)
        self.spread.setValue(loan.spread * 100.0)
        self.interest_mode.setCurrentText(loan.interest_mode.value)
        self.amortization.setCurrentText(loan.amortization.value)
        self.use_ltv.setChecked(loan.max_ltv is not None)
        self.max_ltv.setValue((loan.max_ltv or 0.60) * 100.0)
        self.target_ltv.setValue((loan.target_ltv or loan.max_ltv or 0.50) * 100.0)
        self._loading = False
        self._update_enabled_state()

    def _update_enabled_state(self):
        on = self.enabled.isChecked()
        self.box.setEnabled(on)
        fixed = self.rate_mode.currentText() == RateMode.FIXED.value
        self.rate.setEnabled(on and fixed)
        self.spread.setEnabled(on and not fixed)
        self.max_ltv.setEnabled(on and self.use_ltv.isChecked())
        self.target_ltv.setEnabled(on and self.use_ltv.isChecked())

        if on and self.principal.value() <= 0:
            self.warning.setText(
                status_dot(
                    STATUS_WARNING,
                    "Falta el monto del crédito: mientras sea 0 la simulación corre "
                    "como si esta estrategia no tuviera apalancamiento.",
                )
            )
        else:
            self.warning.setText("")

    def _on_toggle(self):
        self._update_enabled_state()
        self._on_change()

    def _on_change(self, *_):
        if self._loading or self.strategy is None:
            return
        self._update_enabled_state()

        if not self.enabled.isChecked():
            self.strategy.loan = None
            self.changed.emit()
            return

        max_ltv = self.max_ltv.value() / 100.0 if self.use_ltv.isChecked() else None
        target_ltv = self.target_ltv.value() / 100.0 if self.use_ltv.isChecked() else None
        if max_ltv is not None and target_ltv is not None and target_ltv > max_ltv:
            target_ltv = max_ltv

        try:
            self.strategy.loan = LoanTerms(
                name=self.name.text().strip() or "Crédito",
                principal=self.principal.value(),
                start_year=self.start_year.value(),
                term_years=self.term_years.value(),
                rate_mode=RateMode(self.rate_mode.currentText()),
                rate=self.rate.value() / 100.0,
                spread=self.spread.value() / 100.0,
                interest_mode=InterestMode(self.interest_mode.currentText()),
                amortization=Amortization(self.amortization.currentText()),
                max_ltv=max_ltv,
                target_ltv=target_ltv,
            )
        except ValueError:
            return
        self.changed.emit()
