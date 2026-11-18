"""Indicadores principales sobre los resultados.

Solo leen: el capital y el horizonte del caso y, tras simular, la mediana del
patrimonio final de la primera estrategia —la misma cifra que la tabla de la
pestaña Distribución en el último año—. No calculan nada que el motor no haya
calculado ya.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from .theme import amount_unit, format_display


class KpiCard(QFrame):
    def __init__(self, title: str, accent: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("kpiCard")
        self.setProperty("accent", "true" if accent else "false")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("kpiTitle")
        self.value = QLabel("—")
        self.value.setObjectName("kpiValue")
        self.unit = QLabel("")
        self.unit.setObjectName("kpiUnit")
        for w in (self.title, self.value, self.unit):
            layout.addWidget(w)

    def set(self, value: str, unit: str = "", tooltip: str = "") -> None:
        self.value.setText(value)
        self.unit.setText(unit)
        self.setToolTip(tooltip)


class KpiRow(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.initial = KpiCard("Patrimonio inicial")
        self.expected = KpiCard("Patrimonio esperado")
        self.horizon = KpiCard("Horizonte", accent=True)
        for card in (self.initial, self.expected, self.horizon):
            layout.addWidget(card, 1)

    def update_from(self, scenario, result, peso) -> None:
        """`result` es el resultado en la moneda de lectura (o None sin simular)."""
        currency = "COP" if peso is not None else "USD"
        unit = amount_unit(currency)
        if result is not None and len(result):
            first = result.strategies[0]
            self.initial.set(format_display(float(first.initial_value)), unit,
                             f"Capital inicial de «{first.name}»")
            final = float(first.distribution_stats([result.horizon])[50][0])
            self.expected.set(format_display(final), f"{unit} · mediana, {first.name}",
                              f"Mediana del patrimonio en el año {result.horizon} "
                              f"de «{first.name}» (nominal)")
            years = result.horizon
        else:
            initial = scenario.initial_value * (peso.spot if peso is not None else 1.0)
            self.initial.set(format_display(initial), unit, "Capital inicial del caso")
            self.expected.set("—", "Corre la simulación", "")
            years = scenario.horizon
        self.horizon.set(f"{years} años", "Proyección")
