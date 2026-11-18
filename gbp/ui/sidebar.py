"""Barra lateral de navegación (azul petróleo).

Solo es una segunda forma de llegar a las pestañas de parámetros que ya
existen: cada entrada selecciona una pestaña de `inputs` y la pestaña, al
cambiar, marca la entrada. No guarda estado propio.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QButtonGroup, QFrame, QLabel, QToolButton, QVBoxLayout

from .brand import wordmark_pixmap

SIDEBAR_WIDTH = 150


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
    """Entradas: una por pestaña de parámetros, más «Acerca de» al pie."""

    section_selected = Signal(int)
    about_requested = Signal()

    def __init__(self, sections: list[str], parent=None):
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
        layout.addSpacing(30)

        caption = QLabel("PROYECCIÓN\nPATRIMONIAL")
        caption.setObjectName("sidebarCaption")
        layout.addWidget(caption)
        layout.addSpacing(6)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[QToolButton] = []
        for index, name in enumerate(sections):
            button = QToolButton()
            button.setText(name)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setSizePolicy(button.sizePolicy().horizontalPolicy().Expanding,
                                 button.sizePolicy().verticalPolicy())
            button.setMinimumWidth(SIDEBAR_WIDTH)
            self.group.addButton(button, index)
            self.buttons.append(button)
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
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)
