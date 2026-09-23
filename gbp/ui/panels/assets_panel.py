"""Panel de supuestos de mercado (CMAs).

Hay dos categorías y la pantalla tiene que hacer visible la frontera:

* Las **59 clases del LTCMA** no son input de la app. Son supuestos
  institucionales, se actualizan reimportando el documento con
  `tools/import_ltcma.py`, y editarlas desde la interfaz haría que dos
  analistas con el mismo caso obtuvieran proyecciones distintas sin que nada lo
  dejara ver. Siguen bloqueadas.
* Los **activos propios** los declara el analista para patrimonio que el LTCMA
  no cubre. De esos la fuente es él, así que se crean, se editan y se borran
  desde aquí.

Ni siquiera los propios se editan en la celda: todo pasa por diálogo. Así no
hay dos modos de edición conviviendo y no se puede tocar una fila del LTCMA por
accidente.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...io import library
from ...model.assets import AssetClass, CMASet
from ...model.groups import group_of
from ..theme import NEUTRAL

COLUMNS = [
    "Clase de activo", "Origen", "Clase", "Retorno compuesto %",
    "Volatilidad %", "Yield %",
]


class AssetsPanel(QWidget):
    """Supuestos por clase de activo: LTCMA en lectura, propios administrables."""

    changed = Signal()

    def __init__(self, cmas: CMASet, base_correlations=None, parent=None):
        super().__init__(parent)
        self.cmas = cmas
        self.base_correlations = base_correlations
        self._loading = False
        self._rows: list[AssetClass] = []

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Los supuestos del LTCMA son institucionales y no se editan desde la app: "
            "se actualizan reimportando el documento con tools/import_ltcma.py. Así "
            "dos personas con el mismo caso obtienen la misma proyección."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #3D5560;")
        layout.addWidget(intro)

        propios = QLabel(
            "Los <b>activos propios</b> son distintos: los declaras tú, para patrimonio "
            "que el LTCMA no cubre —renta fija colombiana, finca raíz local—. Se guardan "
            "en tu librería y además viajan dentro del caso, para que se abra igual en "
            "otro computador."
        )
        propios.setWordWrap(True)
        propios.setStyleSheet("color: #3D5560;")
        layout.addWidget(propios)

        source = QLabel(self._source_note())
        source.setWordWrap(True)
        source.setStyleSheet("color: #5B7280;")
        layout.addWidget(source)

        filtros = QHBoxLayout()
        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText("Filtrar clases de activo…")
        self.filter_box.textChanged.connect(self._apply_filter)
        filtros.addWidget(self.filter_box, 1)
        self.only_custom = QCheckBox("Solo activos propios")
        self.only_custom.stateChanged.connect(lambda: self._apply_filter(self.filter_box.text()))
        filtros.addWidget(self.only_custom)
        layout.addLayout(filtros)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        # Nada se edita en la celda, ni siquiera lo propio: todo por diálogo.
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.doubleClicked.connect(self._edit_asset)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(COLUMNS)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        botones = QHBoxLayout()
        self.new_button = QPushButton("Nuevo activo propio…")
        self.new_button.clicked.connect(self._new_asset)
        self.edit_button = QPushButton("Editar…")
        self.edit_button.clicked.connect(self._edit_asset)
        self.delete_button = QPushButton("Eliminar")
        self.delete_button.clicked.connect(self._delete_asset)
        botones.addWidget(self.new_button)
        botones.addWidget(self.edit_button)
        botones.addWidget(self.delete_button)
        botones.addStretch(1)
        layout.addLayout(botones)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #5B7280;")
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
        self._rows = list(cmas)
        self.table.setRowCount(len(self._rows))
        for row, asset in enumerate(self._rows):
            self._set_row(row, asset)
        self._loading = False
        self._apply_filter(self.filter_box.text())
        propios = len(cmas.custom)
        self.status.setText(
            f"{len(cmas)} clases de activo: {len(cmas) - propios} del LTCMA "
            f"y {propios} propias."
        )
        self._update_buttons()

    def _set_row(self, row: int, asset: AssetClass):
        name_item = QTableWidgetItem(asset.name)
        origen = QTableWidgetItem("Propio" if asset.is_custom else "LTCMA")
        # La clase de una del LTCMA se deduce del nombre: se muestra en gris para
        # que se entienda el mecanismo sin confundirla con una declarada.
        clase = QTableWidgetItem(
            asset.asset_class if asset.is_custom else group_of(asset.name)
        )
        if not asset.is_custom:
            clase.setForeground(QBrush(QColor("#9AA4AB")))

        if asset.is_custom:
            negrita = QFont()
            negrita.setBold(True)
            name_item.setFont(negrita)
            fondo = QBrush(QColor(NEUTRAL))
            for item in (name_item, origen, clase):
                item.setBackground(fondo)
            if asset.notes:
                name_item.setToolTip(asset.notes)

        self.table.setItem(row, 0, name_item)
        self.table.setItem(row, 1, origen)
        self.table.setItem(row, 2, clase)

        for col, value in enumerate(
            (asset.compound_return, asset.volatility, asset.yield_), start=3
        ):
            item = QTableWidgetItem(f"{value * 100:.2f}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if asset.is_custom:
                item.setBackground(QBrush(QColor(NEUTRAL)))
            self.table.setItem(row, col, item)

    def _apply_filter(self, text: str):
        needle = text.strip().lower()
        solo_propios = self.only_custom.isChecked()
        for row, asset in enumerate(self._rows):
            visible = not needle or needle in asset.name.lower()
            if solo_propios and not asset.is_custom:
                visible = False
            self.table.setRowHidden(row, not visible)

    # ------------------------------------------------------------------
    @property
    def selected(self) -> AssetClass | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def _update_buttons(self):
        asset = self.selected
        editable = asset is not None and asset.is_custom
        self.edit_button.setEnabled(editable)
        self.delete_button.setEnabled(editable)
        if asset is not None and not asset.is_custom:
            self.edit_button.setToolTip(
                "Las clases del LTCMA no se editan desde la app."
            )
            self.delete_button.setToolTip(
                "Las clases del LTCMA no se borran desde la app."
            )
        else:
            self.edit_button.setToolTip("")
            self.delete_button.setToolTip("")

    def _new_asset(self):
        from ..custom_asset_dialog import CustomAssetDialog

        dialog = CustomAssetDialog(self.base_correlations, self.cmas, parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self.cmas.add(dialog.asset())
        self.reload(self.cmas)
        self._persist()

    def _edit_asset(self):
        asset = self.selected
        if asset is None or not asset.is_custom:
            return
        from ..custom_asset_dialog import CustomAssetDialog

        dialog = CustomAssetDialog(self.base_correlations, self.cmas, asset, parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        actualizado = dialog.asset()
        anterior = asset.name
        asset.name = actualizado.name
        asset.compound_return = actualizado.compound_return
        asset.volatility = actualizado.volatility
        asset.yield_ = actualizado.yield_
        asset.asset_class = actualizado.asset_class
        asset.notes = actualizado.notes

        self.reload(self.cmas)
        self._persist()
        if anterior != asset.name:
            self.status.setText(
                f"'{anterior}' se renombró a '{asset.name}'. Las estrategias que lo "
                "usaban hay que reapuntarlas a mano."
            )

    def _delete_asset(self):
        asset = self.selected
        if asset is None or not asset.is_custom:
            return
        if QMessageBox.question(
            self,
            "Eliminar activo propio",
            f"¿Eliminar '{asset.name}' de tu librería?\n\n"
            "Si algún caso guardado lo usa, al abrirlo se te ofrecerá volver a "
            "añadirlo: los casos llevan dentro sus activos propios.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.cmas.remove(asset.name)
        self.reload(self.cmas)
        self._persist()

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
