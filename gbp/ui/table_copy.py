"""Copiar una tabla de resultados al portapapeles, lista para pegar en Excel.

El texto va separado por tabuladores, una fila por línea y con los rótulos de
columna arriba: es el formato que Excel reparte en celdas al pegar.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QTableWidget


def table_text(table: QTableWidget, only_selected: bool = False) -> str:
    """La tabla como texto tabulado, con encabezados.

    Con `only_selected` van solo las filas que tienen alguna celda
    seleccionada, completas: media fila pegada en una hoja no dice de qué es.
    """
    columns = range(table.columnCount())
    rows = range(table.rowCount())
    if only_selected:
        chosen = {index.row() for index in table.selectedIndexes()}
        rows = [r for r in rows if r in chosen]

    def cell(r, c):
        item = table.item(r, c)
        return item.text() if item is not None else ""

    def header(c):
        item = table.horizontalHeaderItem(c)
        return item.text() if item is not None else ""

    lines = ["\t".join(header(c) for c in columns)]
    lines += ["\t".join(cell(r, c) for c in columns) for r in rows]
    return "\n".join(lines)


def enable_copy(table: QTableWidget) -> None:
    """Ctrl+C y menú contextual: «Copiar selección» y «Copiar tabla»."""

    def copy(only_selected: bool):
        selected = only_selected and bool(table.selectedIndexes())
        QApplication.clipboard().setText(table_text(table, only_selected=selected))

    selection = QAction("Copiar selección", table)
    selection.setShortcut(QKeySequence.StandardKey.Copy)
    selection.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
    selection.triggered.connect(lambda: copy(True))

    whole = QAction("Copiar tabla", table)
    whole.triggered.connect(lambda: copy(False))

    table.addActions([selection, whole])
    table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
