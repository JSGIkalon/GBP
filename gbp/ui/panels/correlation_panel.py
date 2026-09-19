"""Panel de correlaciones: vista de solo lectura de la matriz del LTCMA.

Las correlaciones no son un input de la app. Vienen de las Assumption Matrices
del LTCMA y se actualizan reimportando el PDF, no editando celdas.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...model.correlation import CorrelationMatrix


def _mix(start: QColor, end: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(start.red() + t * (end.red() - start.red())),
        int(start.green() + t * (end.green() - start.green())),
        int(start.blue() + t * (end.blue() - start.blue())),
    )


def _cell_color(value: float) -> QColor:
    """Rampa de la gama Ikalon: neutro en cero, navy en +1, cyan en -1.

    La correlación es una polaridad, así que idealmente la rampa sería divergente
    con dos tonos opuestos. La paleta de datos del manual está cerrada a la gama
    azul, así que los dos polos se distinguen por **intensidad y familia dentro
    del azul** —navy profundo para la correlación positiva, cyan claro para la
    negativa— con el gris neutro en el medio. El signo siempre está escrito en
    la celda, así que la lectura no depende del color.
    """
    neutral = QColor("#E3E8EC")
    if value >= 0:
        return _mix(neutral, QColor("#002e45"), value)
    return _mix(neutral, QColor("#27b4ff"), -value)


class HeatmapDelegate(QStyledItemDelegate):
    """Pinta el fondo de cada celda desde el modelo.

    Hace falta porque la hoja de estilo de la app declara `QTableWidget::item`,
    y en cuanto hay una regla de estilo para el ítem Qt pasa a usar el estilo de
    la hoja e **ignora el color de fondo que puso el modelo**. Sin esto la matriz
    sale toda blanca —la rampa desaparece— y el 1.00 de la diagonal queda en
    blanco sobre blanco, es decir invisible.
    """

    def paint(self, painter, option, index):
        background = index.data(Qt.ItemDataRole.BackgroundRole)
        if background is not None:
            painter.save()
            painter.fillRect(option.rect, background)
            painter.restore()
        super().paint(painter, option, index)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        # El fondo ya lo pintamos nosotros; que el estilo no lo repinte encima.
        option.backgroundBrush = QBrush(Qt.BrushStyle.NoBrush)


class CorrelationPanel(QWidget):
    """Matriz de correlación embebida, solo lectura."""

    def __init__(self, correlations: CorrelationMatrix, resolver=None, parent=None):
        super().__init__(parent)
        self.correlations = correlations
        self.resolver = resolver
        self._used_names: list[str] = []

        layout = QVBoxLayout(self)

        source = QLabel(
            f"Fuente: {correlations.source or 'LTCMA'}\n"
            "Las correlaciones no se editan desde la app: se actualizan reimportando el "
            "LTCMA con tools/import_ltcma.py."
        )
        source.setWordWrap(True)
        source.setStyleSheet("color: #1F2A30;")
        layout.addWidget(source)

        if correlations.psd_adjustment > 0:
            note = QLabel(
                f"La matriz publicada viene redondeada a dos decimales, así que no es "
                f"exactamente semidefinida positiva. Se proyecta a la más cercana que sí "
                f"lo es; el ajuste máximo aplicado es de {correlations.psd_adjustment:.4f}."
            )
            note.setWordWrap(True)
            note.setStyleSheet("color: #5C6770;")
            layout.addWidget(note)

        controls = QHBoxLayout()
        self.only_used = QCheckBox("Mostrar solo las clases usadas en las estrategias")
        self.only_used.setChecked(True)
        self.only_used.stateChanged.connect(self._render)
        controls.addWidget(self.only_used)
        controls.addStretch(1)
        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText("Filtrar…")
        self.filter_box.setMaximumWidth(240)
        self.filter_box.textChanged.connect(self._render)
        controls.addWidget(self.filter_box)
        layout.addLayout(controls)

        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.setItemDelegate(HeatmapDelegate(self.table))
        layout.addWidget(self.table, 1)

        self.derived_note = QLabel("")
        self.derived_note.setWordWrap(True)
        self.derived_note.setStyleSheet("color: #5C6770;")
        self.derived_note.setVisible(False)
        layout.addWidget(self.derived_note)

        self._render()

    def set_correlations(self, correlations: CorrelationMatrix, resolver=None):
        """Cambia la matriz mostrada: la extendida, cuando hay activos propios.

        Ocultar las filas derivadas sería peor que mostrarlas: el analista tiene
        derecho a ver con qué está simulando en realidad.
        """
        self.correlations = correlations
        self.resolver = resolver
        self._render()

    def set_used_assets(self, names: list[str]):
        """Clases que las estrategias están usando; sirve para acotar la vista."""
        self._used_names = list(names)
        self._render()

    def _visible_names(self) -> list[str]:
        names = self.correlations.names
        if self.only_used.isChecked() and self._used_names:
            names = [n for n in names if n in self._used_names]
        needle = self.filter_box.text().strip().lower()
        if needle:
            names = [n for n in names if needle in n.lower()]
        return names

    def _render(self):
        names = self._visible_names()
        self.table.clear()
        self.table.setRowCount(len(names))
        self.table.setColumnCount(len(names))
        self.table.setHorizontalHeaderLabels(names)
        self.table.setVerticalHeaderLabels(names)

        if not names:
            return

        sub = self.correlations.subset(names)
        for i in range(len(names)):
            for j in range(len(names)):
                value = float(sub[i, j])
                item = QTableWidgetItem(f"{value:.2f}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setBackground(QBrush(_cell_color(value)))
                # Blanco solo sobre el navy profundo; el cyan es claro y pide Ink.
                if value > 0.6:
                    item.setForeground(QBrush(QColor("#FFFFFF")))
                else:
                    item.setForeground(QBrush(QColor("#1F2A30")))
                propio = self.resolver is not None and (
                    self.resolver.is_custom(names[i])
                    or self.resolver.is_custom(names[j])
                )
                origen = (
                    "\nDerivada del promedio de su clase, no publicada."
                    if propio else ""
                )
                item.setToolTip(
                    f"{names[i]}\n{names[j]}\nCorrelación {value:.2f}{origen}"
                )
                self.table.setItem(i, j, item)

        self.table.resizeColumnsToContents()
        self._update_derived_note(names)

    def _update_derived_note(self, names: list[str]):
        propios = [
            n for n in names
            if self.resolver is not None and self.resolver.is_custom(n)
        ]
        if propios:
            self.derived_note.setText(
                f"{len(propios)} fila(s) son de activos propios: "
                f"{', '.join(propios)}. Sus correlaciones no están publicadas — se "
                "derivan del promedio de la clase de activo que declaraste."
            )
            self.derived_note.setVisible(True)
        else:
            self.derived_note.setVisible(False)
