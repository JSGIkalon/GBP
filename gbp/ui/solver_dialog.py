"""Ventana del solver: qué cifra del plan logra una probabilidad objetivo.

Se abre desde Análisis → Solver y no toca el caso: muestra el valor encontrado
y deja aplicarlo con un botón. Quien no la abre no ve ninguna diferencia en la
app.
"""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ..engine.solver import CAPITAL, FLOW, GOAL, SUCCESS, Metric, Variable, solve
from ..model.cashflows import FlowKind
from .theme import INK, INK_SOFT, format_display
from .worker import start_task


class SolverDialog(QDialog):
    """Pregunta, búsqueda en un hilo y resultado, con «Aplicar al caso»."""

    def __init__(self, main, parent=None):
        super().__init__(parent or main)
        self.main = main
        self.setWindowTitle("Solver")
        self.setMinimumWidth(620)
        self.solve_result = None
        self._thread = None
        self._worker = None
        self._request = None

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Encuentra la cifra del plan que logra una probabilidad objetivo: el retiro "
            "máximo que se sostiene, o el aporte o capital mínimo que hace falta. Usa "
            "los mismos caminos de mercado que la corrida y no cambia el caso hasta que "
            "pulses «Aplicar al caso»."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {INK};")
        layout.addWidget(intro)

        form = QFormLayout()
        self.strategy_box = QComboBox()
        self.strategy_box.addItems([s.name for s in main.scenario.strategies])
        self.strategy_box.currentIndexChanged.connect(self._fill_variables)
        form.addRow("Estrategia", self.strategy_box)

        self.variable_box = QComboBox()
        form.addRow("Cifra a ajustar", self.variable_box)

        self.metric_box = QComboBox()
        self.metric_box.addItem("Probabilidad de éxito", Metric(SUCCESS))
        horizon = main.scenario.horizon
        for i, goal in enumerate(main.scenario.goals):
            if goal.fits(horizon):
                self.metric_box.addItem(f"Meta · {goal.describe(horizon)}", Metric(GOAL, i))
        form.addRow("Probabilidad", self.metric_box)

        self.target_box = QDoubleSpinBox()
        self.target_box.setRange(1.0, 99.0)
        self.target_box.setDecimals(1)
        self.target_box.setSuffix(" %")
        self.target_box.setValue(85.0)
        form.addRow("Objetivo: al menos", self.target_box)
        layout.addLayout(form)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.answer = QLabel("")
        self.answer.setWordWrap(True)
        self.answer.setStyleSheet(f"color: {INK}; font-size: 14px;")
        layout.addWidget(self.answer)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet(f"color: {INK_SOFT};")
        layout.addWidget(self.detail)

        buttons = QHBoxLayout()
        self.run_button = QPushButton("Resolver")
        self.run_button.setObjectName("runButton")
        self.run_button.clicked.connect(self._run)
        self.apply_button = QPushButton("Aplicar al caso")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._apply)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.close)
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.apply_button)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self._fill_variables()

    def _current_strategy(self):
        index = self.strategy_box.currentIndex()
        strategies = self.main.scenario.strategies
        return strategies[index] if 0 <= index < len(strategies) else None

    def _fill_variables(self, *_):
        self.variable_box.clear()
        strategy = self._current_strategy()
        if strategy is None:
            return
        for i, flow in enumerate(strategy.cashflows):
            tipo = "Retiro" if flow.kind is FlowKind.OUTFLOW else "Aporte"
            unidad = "% del patrimonio" if flow.is_percentage else "monto anual"
            self.variable_box.addItem(f"{tipo} · {flow.name} ({unidad})", Variable(FLOW, i))
        self.variable_box.addItem("Capital inicial", Variable(CAPITAL))

    def _money(self, value: float, is_pct: bool) -> str:
        """El valor en la moneda que se está viendo en la app."""
        if is_pct:
            return f"{value:.2%} del patrimonio"
        rate = self.main.results.fx_rate or 1.0
        suffix = " COP" if self.main.results.fx_rate else ""
        return f"{format_display(value * rate)}{suffix}"

    def _run(self):
        strategy = self._current_strategy()
        if strategy is None:
            return
        self.main.settings_panel.commit()
        scenario = deepcopy(self.main.scenario)
        request = dict(
            scenario=scenario,
            strategy_name=strategy.name,
            variable=self.variable_box.currentData(),
            metric=self.metric_box.currentData(),
            target=self.target_box.value() / 100.0,
        )
        self._request = request
        settings = deepcopy(self.main.settings)
        cmas, correlations = self.main.cmas, self.main.correlations

        self.run_button.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.progress.setVisible(True)
        self.answer.setText("Buscando…")
        self.detail.setText("")
        self._thread, self._worker = start_task(
            self,
            lambda: solve(cmas=cmas, correlations=correlations, settings=settings, **request),
            self._on_done,
            self._on_failed,
        )

    def _on_failed(self, message: str):
        self.progress.setVisible(False)
        self.run_button.setEnabled(True)
        self.answer.setText("No se pudo resolver.")
        self.detail.setText(message)

    def _on_done(self, result):
        self.progress.setVisible(False)
        self.run_button.setEnabled(True)
        self.solve_result = result
        # La ventana guarda el resultado con la firma del caso que se resolvió:
        # el informe solo lo incluye si el caso no cambió desde entonces.
        self.main.remember_solve(result, self._request["scenario"])
        pct = result.is_percentage
        actual = (
            f"Hoy: {self._money(result.current_value, pct)} → "
            f"{result.current_probability:.1%}."
        )
        if result.found:
            buscado = "máximo" if result.maximize else "mínimo"
            self.answer.setText(
                f"<b>{result.variable_label}</b>: valor {buscado} con al menos "
                f"{result.target:.1%} de {result.metric_label.lower()} → "
                f"<b>{self._money(result.value, pct)}</b> "
                f"(probabilidad lograda {result.achieved:.1%})."
            )
            self.apply_button.setEnabled(True)
        else:
            self.answer.setText("El objetivo no se puede alcanzar con esta cifra.")
        extra = f" {result.message}" if result.message else ""
        self.detail.setText(
            f"{actual}{extra} Se probaron {result.evaluations} valores sobre "
            f"{result.n_paths:,} caminos.".replace(",", ".")
        )

    def _apply(self):
        """Escribe el valor en el caso vivo, como si se hubiera tecleado."""
        if self.solve_result is None or not self.solve_result.found:
            return
        scenario = self.main.scenario
        strategy = next(
            (s for s in scenario.strategies if s.name == self.solve_result.strategy_name), None
        )
        if strategy is None:
            return
        variable = self._request["variable"]
        if variable.kind == CAPITAL:
            strategy.initial_value = self.solve_result.value
        elif variable.flow_index < len(strategy.cashflows):
            strategy.cashflows[variable.flow_index].amount = self.solve_result.value
        self.main.after_external_edit()
        # El caso ahora es el caso resuelto y aplicado: el informe puede seguir
        # citando el resultado del solver después de volver a correr.
        self.main.remember_solve(self.solve_result, scenario)
        self.apply_button.setEnabled(False)
        self.detail.setText(
            self.detail.text() + " Aplicado al caso: vuelve a correr la simulación para "
            "ver el resultado completo."
        )

    def closeEvent(self, event):
        if self._thread is not None:
            try:
                if self._thread.isRunning():
                    self._thread.wait()
            except RuntimeError:
                pass
        super().closeEvent(event)
