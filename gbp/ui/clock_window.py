"""Reloj analógico independiente."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QTime, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .brand import app_icon
from .theme import BG, BORDER, INK, INK_SOFT, NAVY, PRIMARY, WHITE


class ClockWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(260, 260)
        self._time = QTime.currentTime()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_time)
        self._timer.start(250)

    def _update_time(self) -> None:
        self._time = QTime.currentTime()
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()
        side = min(width, height)
        center = QPointF(width / 2, height / 2)
        radius = side * 0.43

        painter.setPen(QPen(QColor(BORDER), 2))
        painter.setBrush(QColor(WHITE))
        painter.drawEllipse(center, radius, radius)

        painter.setPen(QPen(QColor(INK_SOFT), 1))
        painter.setBrush(QColor(INK_SOFT))
        for minute in range(60):
            angle = math.radians(minute * 6 - 90)
            outer = radius * 0.86
            inner = radius * (0.79 if minute % 5 == 0 else 0.82)
            painter.drawLine(
                QPointF(
                    center.x() + inner * math.cos(angle),
                    center.y() + inner * math.sin(angle),
                ),
                QPointF(
                    center.x() + outer * math.cos(angle),
                    center.y() + outer * math.sin(angle),
                ),
            )

        for number, position in (
            (12, (0, -0.67)),
            (3, (0.67, 0)),
            (6, (0, 0.67)),
            (9, (-0.67, 0)),
        ):
            painter.setPen(QColor(NAVY))
            font = painter.font()
            font.setPointSize(max(10, int(side / 24)))
            font.setBold(True)
            painter.setFont(font)
            text_x = center.x() + position[0] * radius
            text_y = center.y() + position[1] * radius
            painter.drawText(
                int(text_x - 18),
                int(text_y - 10),
                36,
                20,
                Qt.AlignmentFlag.AlignCenter,
                str(number),
            )

        hour = self._time.hour() % 12
        minute = self._time.minute()
        second = self._time.second()

        hands = (
            (hour * 30 + minute * 0.5 - 90, radius * 0.48, 7, NAVY),
            (minute * 6 + second * 0.1 - 90, radius * 0.68, 5, PRIMARY),
            (second * 6 - 90, radius * 0.75, 2, INK),
        )
        for angle_degrees, length, hand_width, color in hands:
            angle = math.radians(angle_degrees)
            end = QPointF(
                center.x() + length * math.cos(angle),
                center.y() + length * math.sin(angle),
            )
            painter.setPen(
                QPen(
                    QColor(color),
                    hand_width,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawLine(center, end)

        painter.setBrush(QColor(PRIMARY))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, 7, 7)
        painter.end()


class ClockWindow(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reloj")
        icon = app_icon()
        if icon is not None:
            self.setWindowIcon(icon)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(360, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 18)
        layout.setSpacing(12)
        layout.addWidget(ClockWidget(), 1)

        self.digital_label = QLabel()
        self.digital_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.digital_label.setStyleSheet(
            f"font-family: Inter, Jost, Calibri, sans-serif;"
            f"font-size: 18px; font-weight: 600; color: {INK};"
            f"background-color: {BG}; padding: 8px;"
        )
        layout.addWidget(self.digital_label)

        self._label_timer = QTimer(self)
        self._label_timer.timeout.connect(self._update_label)
        self._label_timer.start(250)
        self._update_label()

    def _update_label(self) -> None:
        now = QTime.currentTime()
        self.digital_label.setText(now.toString("hh:mm:ss"))
