"""Filtro de estrategias sobre los resultados.

En la app, lo que se compara en una corrida son **estrategias** (planes
completos); el «escenario» es el caso común a todas. Este filtro elige cuáles
se ven en gráficos, tablas, leyendas e indicadores. Es solo de lectura: no
cambia la corrida, y cada estrategia conserva sus cifras —nada se combina—.

Los botones van en un `FlowLayout` que salta de línea cuando no caben, así que
en una ventana angosta el filtro crece hacia abajo una línea en vez de
desbordarse o encoger los gráficos de lado.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLayout, QSizePolicy, QToolButton, QWidget


class FlowLayout(QLayout):
    """Distribuye los widgets en filas y salta de línea al llenarse el ancho."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, dry=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _layout(self, rect, dry: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + self._spacing, 0
            if not dry:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line = max(line, hint.height())
        return y + line - rect.y()


class StrategyFilter(QWidget):
    """Un botón por estrategia, más «Todas»; emite la lista visible."""

    selection_changed = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons: dict[str, QToolButton] = {}
        self._names: list[str] = []
        self._optimized: dict[str, str] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        caption = QLabel("Ver estrategias:")
        caption.setObjectName("kpiTitle")
        outer.addWidget(caption, 0, Qt.AlignmentFlag.AlignTop)

        self._chips = QWidget()
        self._flow = FlowLayout(self._chips)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self._chips.setSizePolicy(policy)
        outer.addWidget(self._chips, 1)

        self.all_button = QToolButton()
        self.all_button.setText("Todas")
        self.all_button.setObjectName("strategyChip")
        self.all_button.setToolTip("Mostrar todas las estrategias")
        self.all_button.clicked.connect(self.select_all)
        outer.addWidget(self.all_button, 0, Qt.AlignmentFlag.AlignTop)

    # ------------------------------------------------------------------
    @property
    def selected(self) -> list[str]:
        return [n for n in self._names if self._buttons[n].isChecked()]

    @property
    def hidden(self) -> list[str]:
        return [n for n in self._names if not self._buttons[n].isChecked()]

    def set_strategies(self, names: list[str], optimized: dict[str, str] | None = None):
        """Reconstruye los botones conservando la selección de las que siguen.

        Estado inicial razonable: una estrategia nueva aparece seleccionada, y
        si de la selección anterior no queda ninguna, se ven todas.
        """
        previous = set(self.selected) if self._names else None
        known = set(self._names)
        self._optimized = dict(optimized or {})
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._buttons.clear()
        self._names = list(names)
        for name in names:
            button = QToolButton()
            button.setObjectName("strategyChip")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            label = name
            if name in self._optimized:
                label = f"{name} ★"
                button.setToolTip(f"Pesos optimizados: {self._optimized[name]}")
            button.setText(label)
            checked = previous is None or name in previous or name not in known
            button.setChecked(checked)
            button.toggled.connect(self._emit)
            self._flow.addWidget(button)
            self._buttons[name] = button
        if names and not self.selected:
            for button in self._buttons.values():
                button.setChecked(True)
        self._chips.updateGeometry()
        self.setVisible(len(names) > 0)

    def set_selected(self, names: list[str]):
        wanted = set(names)
        for name, button in self._buttons.items():
            button.blockSignals(True)
            button.setChecked(name in wanted)
            button.blockSignals(False)
        self._emit()

    def select_all(self):
        self.set_selected(self._names)

    def _emit(self, *_):
        self.selection_changed.emit(self.selected)
