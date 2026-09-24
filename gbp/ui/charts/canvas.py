"""Lienzo de matplotlib embebido en Qt, con capa de hover.

Todos los gráficos de la app comparten este lienzo. La capa de hover es parte
del contrato: un gráfico en pantalla es interactivo, así que cada marca publica
su propio detalle al pasar el mouse por encima.
"""

from __future__ import annotations

from collections.abc import Callable

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QTimer
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
        # Foto del gráfico sin tooltip, tomada en cada dibujo completo. Mover el
        # mouse repinta solo el tooltip encima de esta foto (blitting) en vez de
        # redibujar cajas, ejes y etiquetas en cada evento de movimiento.
        self._background = None
        self.mpl_connect("draw_event", self._on_draw)
        self.mpl_connect("motion_notify_event", self._on_motion)

        # Un gráfico que decide su maquetación midiendo sus etiquetas —el box
        # plot elige la escala en que caben horizontales— tiene que volver a
        # decidir si la ventana cambia de tamaño: con otro ancho, otra escala.
        self._redraw = None
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._on_resized)

    def set_redraw(self, fn):
        """Cómo volver a dibujar este gráfico desde cero, o `None`."""
        self._redraw = fn

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._redraw is not None:
            self._resize_timer.start(150)

    def _on_resized(self):
        if self._redraw is not None:
            self._redraw()

    def _on_draw(self, _event):
        self._background = self.copy_from_bbox(self.figure.bbox)
        if self._annotation is not None and self._annotation.get_visible():
            self.figure.draw_artist(self._annotation)

    def _blit(self):
        """Repinta solo el tooltip; si aún no hay foto, un dibujo completo."""
        if self._background is None:
            self.draw_idle()
            return
        self.restore_region(self._background)
        if self._annotation is not None and self._annotation.get_visible():
            self.figure.draw_artist(self._annotation)
        self.blit(self.figure.bbox)

    def clear(self):
        """Limpia la figura y devuelve un eje nuevo."""
        self.figure.clear()
        self._annotation = None
        self._background = None
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
        self._background = None
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
                # Fuera del dibujo normal: lo pinta `_blit` sobre la foto.
                animated=True,
            )
            self._annotation.set_visible(False)
        return self._annotation

    def _on_motion(self, event):
        if self._hover_probe is None or event.inaxes is None:
            if self._annotation is not None and self._annotation.get_visible():
                self._annotation.set_visible(False)
                self._blit()
            return

        text = self._hover_probe(event.xdata, event.ydata, event.inaxes)
        annotation = self._ensure_annotation(event.inaxes)
        if not text:
            if annotation.get_visible():
                annotation.set_visible(False)
                self._blit()
            return

        annotation.xy = (event.xdata, event.ydata)
        if annotation.get_text() != text:
            annotation.set_text(text)
        annotation.set_visible(True)
        self._blit()

    def layout_now(self):
        """Ajusta márgenes ya, para que un gráfico mida sus etiquetas con el
        ancho real del eje y no con el de antes del ajuste."""
        try:
            self.figure.tight_layout()
        except Exception:
            pass

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
        self._background = None
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
