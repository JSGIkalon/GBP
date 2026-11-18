"""Indicadores principales sobre los resultados.

Solo leen: el capital y el horizonte del caso y, tras simular, cifras de la
primera estrategia **visible** (las que se eligen en el filtro de estrategias):
la mediana del patrimonio final —la misma cifra que la tabla de la pestaña
Distribución en el último año— y su probabilidad de éxito. No calculan nada que
el motor no haya calculado ya.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
)

from .help_texts import SUCCESS_HTML, SUCCESS_TITLE, SUCCESS_TOOLTIP
from .theme import amount_unit, format_display


class KpiCard(QFrame):
    def __init__(self, title: str, accent: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("kpiCard")
        self.setProperty("accent", "true" if accent else "false")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(2)
        self.title_row = QHBoxLayout()
        self.title_row.setSpacing(4)
        self.title = QLabel(title)
        self.title.setObjectName("kpiTitle")
        self.title_row.addWidget(self.title)
        self.title_row.addStretch(1)
        self.value = QLabel("—")
        self.value.setObjectName("kpiValue")
        self.unit = QLabel("")
        self.unit.setObjectName("kpiUnit")
        self.unit.setWordWrap(True)
        layout.addLayout(self.title_row)
        layout.addWidget(self.value)
        layout.addWidget(self.unit)

    def set(self, value: str, unit: str = "", tooltip: str = "") -> None:
        self.value.setText(value)
        self.unit.setText(unit)
        self.setToolTip(tooltip)


def show_success_help(parent=None) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(SUCCESS_TITLE)
    box.setTextFormat(Qt.TextFormat.RichText)
    box.setText(SUCCESS_HTML)
    box.setIcon(QMessageBox.Icon.Information)
    box.exec()


class KpiRow(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.initial = KpiCard("Patrimonio inicial")
        self.expected = KpiCard("Patrimonio esperado")
        self.success = KpiCard("Probabilidad de éxito")
        self.help_button = QToolButton()
        self.help_button.setObjectName("helpButton")
        self.help_button.setText("?")
        self.help_button.setToolTip(SUCCESS_TITLE)
        self.help_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.help_button.clicked.connect(lambda: show_success_help(self.window()))
        self.success.title_row.addWidget(self.help_button)
        self.horizon = KpiCard("Horizonte", accent=True)
        for card in (self.initial, self.expected, self.success, self.horizon):
            layout.addWidget(card, 1)

    def update_from(self, scenario, result, peso) -> None:
        """`result` es el resultado visible en la moneda de lectura (o None sin simular)."""
        currency = "COP" if peso is not None else "USD"
        unit = amount_unit(currency) or currency
        if result is not None and len(result):
            first = result.strategies[0]
            self.initial.set(format_display(float(first.initial_value)), unit,
                             f"Capital inicial de «{first.name}», en {unit}")
            final = float(first.distribution_stats([result.horizon])[50][0])
            self.expected.set(format_display(final), f"{unit} · mediana, {first.name}",
                              f"Mediana del patrimonio en el año {result.horizon} "
                              f"de «{first.name}» (nominal)")
            others = ""
            if len(result) > 1:
                others = " · " + " · ".join(
                    f"{s.name} {s.success_probability:.1%}" for s in result.strategies[1:]
                )
            self.success.set(
                f"{first.success_probability:.1%}",
                f"{first.name}{others}",
                SUCCESS_TOOLTIP,
            )
            years = result.horizon
        else:
            try:
                initial = scenario.initial_in_base() * (peso.spot if peso is not None else 1.0)
            except ValueError as exc:  # capital en COP sin tasa: no se inventa una cifra
                self.initial.set("—", "Falta la tasa USD/COP", str(exc))
            else:
                self.initial.set(format_display(initial), unit, "Capital inicial del caso, "
                                 "convertido a la moneda en que se leen los resultados")
            self.expected.set("—", "Corre la simulación", "")
            self.success.set("—", "Corre la simulación", SUCCESS_TOOLTIP)
            years = scenario.horizon
        self.horizon.set(f"{years} años", "Proyección")
