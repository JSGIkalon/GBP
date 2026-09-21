"""Lienzo de matplotlib embebido en Qt, con capa de hover.

Todos los gráficos de la app comparten este lienzo. La capa de hover es parte
del contrato: un gráfico en pantalla es interactivo, así que cada marca publica
su propio detalle al pasar el mouse por encima.
"""

from __future__ import annotations

from collections.abc import Callable

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import QSizePolicy

from ..theme import INK, INK_SOFT, LEADER, SURFACE, apply_matplotlib_style


class ChartCanvas(FigureCanvasQTAgg):
    """Lienzo con figura propia y un tooltip que sigue al cursor."""

    def __init__(self, parent=None, height: float = 4.2):
        apply_matplotlib_style()
        self.figure = Figure(figsize=(8, height), dpi=100)
        super().__init__(self.figure)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(260)

        self._hover_probe: Callable[[float, float, object], str | None] | None = None
        self._annotation = None
        self.mpl_connect("motion_notify_event", self._on_motion)

    def clear(self):
        """Limpia la figura y devuelve un eje nuevo."""
        self.figure.clear()
        self._annotation = None
        ax = self.figure.add_subplot(111)
        return ax

    def panels(self, height_ratios):
        """Varios ejes apilados, con las alturas relativas indicadas.

        Existe para los gráficos que responden dos preguntas a la vez y no
        pueden meterlas en un solo eje. La capa de hover ya trabaja por eje
        —`_on_motion` usa `event.inaxes`— así que no hay nada más que adaptar.
        """
        self.figure.clear()
        self._annotation = None
        return self.figure.subplots(
            len(height_ratios), 1, height_ratios=list(height_ratios)
        )

    def set_hover_probe(self, probe: Callable[[float, float, object], str | None] | None):
        """Función que, dadas las coordenadas de datos, devuelve el texto a mostrar."""
        self._hover_probe = probe

    def _ensure_annotation(self, ax):
        if self._annotation is None or self._annotation.axes is not ax:
            self._annotation = ax.annotate(
                "",
                xy=(0, 0),
                xytext=(14, 14),
                textcoords="offset points",
                fontsize=9,
                color=INK,
                bbox=dict(
                    boxstyle="round,pad=0.45",
                    facecolor=SURFACE,
                    edgecolor=LEADER,
                    linewidth=0.8,
                    alpha=0.97,
                ),
                zorder=1000,
                annotation_clip=False,
            )
            self._annotation.set_visible(False)
        return self._annotation

    def _on_motion(self, event):
        if self._hover_probe is None or event.inaxes is None:
            if self._annotation is not None and self._annotation.get_visible():
                self._annotation.set_visible(False)
                self.draw_idle()
            return

        text = self._hover_probe(event.xdata, event.ydata, event.inaxes)
        annotation = self._ensure_annotation(event.inaxes)
        if not text:
            if annotation.get_visible():
                annotation.set_visible(False)
                self.draw_idle()
            return

        annotation.xy = (event.xdata, event.ydata)
        annotation.set_text(text)
        annotation.set_visible(True)
        self.draw_idle()

    def finish(self):
        """Ajusta márgenes y repinta."""
        try:
            self.figure.tight_layout()
        except Exception:
            # tight_layout puede quejarse con ejes vacíos; no vale romper la UI por eso.
            pass
        self.draw_idle()

    def show_message(self, message: str):
        """Estado vacío: un mensaje centrado en vez de un gráfico en blanco."""
        self.figure.clear()
        self._annotation = None
        ax = self.figure.add_subplot(111)
        ax.axis("off")
        ax.text(
            0.5,
            0.5,
            message,
            ha="center",
            va="center",
            fontsize=10,
            color=INK_SOFT,
            wrap=True,
        )
        self.set_hover_probe(None)
        self.draw_idle()
