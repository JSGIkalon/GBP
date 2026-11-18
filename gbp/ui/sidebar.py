"""Barra lateral de navegación (azul petróleo).

Es la única navegación de los parámetros: cada entrada selecciona una página
de `inputs` (un QTabWidget sin barra de pestañas visible) y la página, al
cambiar, marca la entrada. No guarda estado propio.

Las entradas se agrupan en secciones: Proyección (escenario y estrategias),
Activos (supuestos del LTCMA y correlaciones) y Configuración (ajustes).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QButtonGroup, QFrame, QLabel, QToolButton, QVBoxLayout

from .brand import wordmark_pixmap

SIDEBAR_WIDTH = 168

# (título de sección, [(entrada, índice de la página en `inputs`)])
SECTIONS = [
    ("PROYECCIÓN", [("Escenario", 0), ("Estrategias", 1)]),
    ("ACTIVOS", [("Supuestos LTCMA", 2), ("Correlaciones", 3)]),
    ("CONFIGURACIÓN", [("Ajustes", 4)]),
]


def section_of(index: int) -> tuple[str, str]:
    """Sección y entrada de una página, para el título del panel."""
    for section, items in SECTIONS:
        for name, i in items:
            if i == index:
                return section.capitalize(), name
    return "", ""


def _white(pixmap: QPixmap) -> QPixmap:
    """La misma marca en blanco, para el fondo azul petróleo."""
    out = QPixmap(pixmap.size())
    out.setDevicePixelRatio(pixmap.devicePixelRatio())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), QColor("white"))
    painter.end()
    return out


class Sidebar(QFrame):
    section_selected = Signal(int)
    about_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(SIDEBAR_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 26, 0, 18)
        layout.setSpacing(2)

        mark = wordmark_pixmap(22)
        if mark is not None:
            logo = QLabel()
            logo.setPixmap(_white(mark))
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(logo)
        layout.addSpacing(22)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[int, QToolButton] = {}
        for section, items in SECTIONS:
            layout.addSpacing(14)
            caption = QLabel(section)
            caption.setObjectName("sidebarCaption")
            layout.addWidget(caption)
            layout.addSpacing(4)
            for name, index in items:
                button = QToolButton()
                button.setText(name)
                button.setCheckable(True)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setMinimumWidth(SIDEBAR_WIDTH)
                self.group.addButton(button, index)
                self.buttons[index] = button
                layout.addWidget(button)
        self.group.idClicked.connect(self.section_selected.emit)

        layout.addStretch(1)

        about = QToolButton()
        about.setText("Acerca de")
        about.setCursor(Qt.CursorShape.PointingHandCursor)
        about.setMinimumWidth(SIDEBAR_WIDTH)
        about.clicked.connect(self.about_requested.emit)
        layout.addWidget(about)

    def set_current(self, index: int) -> None:
        if index in self.buttons:
            self.buttons[index].setChecked(True)
