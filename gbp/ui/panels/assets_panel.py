"""Panel de supuestos de mercado (CMAs): vista de solo lectura.

Retorno, volatilidad y yield **no son input de la app**. Son supuestos
institucionales: vienen del LTCMA y se actualizan reimportando el documento con
`tools/import_ltcma.py`, igual que las correlaciones. Editarlos desde la
interfaz haría que dos personas con el mismo caso obtuvieran proyecciones
distintas sin que nada lo dejara ver, así que la tabla se muestra bloqueada.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...io import library
from ...model.assets import AssetClass, CMASet

COLUMNS = ["Clase de activo", "Retorno compuesto %", "Volatilidad %", "Yield %"]


class AssetsPanel(QWidget):
    """Tabla de supuestos por clase de activo, en modo lectura."""

    changed = Signal()

    def __init__(self, cmas: CMASet, parent=None):
        super().__init__(parent)
        self.cmas = cmas
        self._loading = False

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Los supuestos de mercado son institucionales y no se editan desde la app: "
            "se actualizan reimportando el LTCMA con tools/import_ltcma.py, igual que "
            "las correlaciones. Así dos personas con el mismo caso obtienen la misma "
            "proyección."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #1F2A30;")
        layout.addWidget(intro)

        source = QLabel(self._source_note())
        source.setWordWrap(True)
        source.setStyleSheet("color: #5C6770;")
        layout.addWidget(source)

        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText("Filtrar clases de activo…")
        self.filter_box.textChanged.connect(self._apply_filter)
        layout.addWidget(self.filter_box)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        # Solo lectura, igual que la matriz de correlación.
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(COLUMNS)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #5C6770;")
        layout.addWidget(self.status)

        self.reload(cmas)

    # ------------------------------------------------------------------
    @staticmethod
    def _source_note() -> str:
        """De dónde salieron estos números, dicho en la propia pantalla."""
        import json

        from ...model.correlation import data_dir

        origin = "el LTCMA de J.P. Morgan"
        path = data_dir() / "ltcma_usd.json"
        if path.exists():
            try:
                origin = json.loads(path.read_text(encoding="utf-8")).get("source", origin)
            except (OSError, json.JSONDecodeError):
                pass
        return (
            f"Fuente: {origin}. "
            "El LTCMA no publica yields por clase de activo, así que salen en cero; el "
            "motor proyecta con el retorno total, no con el yield por separado."
        )

    def reload(self, cmas: CMASet):
        self.cmas = cmas
        self._loading = True
        self.table.setRowCount(len(cmas))
        for row, asset in enumerate(cmas):
            self._set_row(row, asset)
        self._loading = False
        self._apply_filter(self.filter_box.text())
        self.status.setText(f"{len(cmas)} clases de activo en la librería.")

    def _set_row(self, row: int, asset: AssetClass):
        name_item = QTableWidgetItem(asset.name)
        self.table.setItem(row, 0, name_item)
        for col, value in enumerate(
            (asset.compound_return, asset.volatility, asset.yield_), start=1
        ):
            item = QTableWidgetItem(f"{value * 100:.2f}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, col, item)

    def _apply_filter(self, text: str):
        needle = text.strip().lower()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            visible = not needle or (item is not None and needle in item.text().lower())
            self.table.setRowHidden(row, not visible)

    # ------------------------------------------------------------------
    def _persist(self):
        """Escribe la librería en disco.

        Ya no hay edición desde la interfaz, pero la librería sigue siendo el
        archivo que lee el motor: esto la mantiene como único punto de escritura
        para quien la cargue por código (el importador del LTCMA, los tests).
        """
        path = library.save_cmas(self.cmas)
        self.status.setText(f"{len(self.cmas)} clases. Guardado en {path}")
        self.changed.emit()
