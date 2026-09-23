"""Creación y edición de activos propios, y la fusión al abrir un caso.

Los supuestos del LTCMA siguen siendo de solo lectura: de esos la app no es la
fuente. De los activos propios sí lo es el analista, así que estos se
administran desde aquí. La frontera tiene que verse en pantalla, no recordarse.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..model.assets import ORIGIN_CUSTOM, AssetClass, CMASet
from ..model.custom_assets import derived_preview
from ..model.groups import GROUP_ORDER
from .theme import INK_SOFT, NAVY, STATUS_WARNING, status_dot

# Clases contra las que se muestra la correlación derivada en la vista previa.
# Son las tres que un analista reconoce de un vistazo.
PREVIEW_AGAINST = ("U.S. Aggregate Bonds", "U.S. Large Cap", "U.S. Cash")

CURRENCY_WARNING = (
    "Los tres valores van <b>en dólares</b>. Si el activo es en otra moneda, "
    "descuenta tú la devaluación esperada antes de escribirlos y súmale la "
    "volatilidad del tipo de cambio. La app no convierte monedas: un 10% en "
    "pesos con el peso devaluándose 4% al año es un 5.8% en dólares, y su "
    "volatilidad en dólares la domina el tipo de cambio, no el activo."
)


class CustomAssetDialog(QDialog):
    """Alta y edición de una clase de activo declarada por el analista."""

    def __init__(self, base_correlations, cmas: CMASet, asset: AssetClass | None = None,
                 parent=None):
        super().__init__(parent)
        self.base = base_correlations
        self.cmas = cmas
        self.original = asset
        self.setWindowTitle("Editar activo propio" if asset else "Nuevo activo propio")
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)

        # Se crea temprano, sin agregarla al layout todavía: los radios de
        # correlación disparan `_update_preview` en cuanto se marcan (más
        # abajo), y eso pasa antes de llegar al punto del layout donde el
        # texto de vista previa vive visualmente.
        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet(f"color: {INK_SOFT};")

        intro = QLabel(
            "Un activo propio sirve para patrimonio que el LTCMA no cubre. Tú fijas "
            "el retorno y la volatilidad; la app deriva las correlaciones del "
            "promedio de la clase que elijas, o de un solo activo de la librería "
            "si prefieres anclarlo a algo más parecido."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(10)

        self.name = QLineEdit(asset.name if asset else "")
        self.name.setPlaceholderText("Renta Fija Colombiana")
        form.addRow("Nombre", self.name)

        self.asset_class = QComboBox()
        self.asset_class.addItems(GROUP_ORDER)
        if asset and asset.asset_class:
            self.asset_class.setCurrentText(asset.asset_class)
        self.asset_class.currentTextChanged.connect(self._update_preview)
        form.addRow("Clase de activo", self.asset_class)

        layout.addLayout(form)

        correlation_box = QVBoxLayout()
        correlation_box.addWidget(QLabel("Correlación"))

        self.source_average = QRadioButton("Promedio de la clase de activo")
        self.source_single = QRadioButton("Un activo específico de la librería")
        self.source_average.setChecked(True)
        self.source_average.toggled.connect(self._update_preview)
        correlation_box.addWidget(self.source_average)

        single_row = QHBoxLayout()
        single_row.addWidget(self.source_single)
        self.source_asset = QComboBox()
        self.source_asset.addItems(sorted(base_correlations.names))
        self.source_asset.setEnabled(False)
        self.source_asset.currentTextChanged.connect(self._update_preview)
        single_row.addWidget(self.source_asset, 1)
        correlation_box.addLayout(single_row)
        self.source_single.toggled.connect(self.source_asset.setEnabled)
        self.source_single.toggled.connect(self._update_preview)

        if asset and asset.correlation_source:
            self.source_single.setChecked(True)
            self.source_asset.setEnabled(True)
            if asset.correlation_source in base_correlations.names:
                self.source_asset.setCurrentText(asset.correlation_source)

        layout.addLayout(correlation_box)

        warning = QLabel(CURRENCY_WARNING)
        warning.setWordWrap(True)
        warning.setStyleSheet(f"color: {NAVY};")
        layout.addWidget(warning)

        numbers = QFormLayout()
        numbers.setSpacing(10)

        self.compound_return = self._percent(-99.0, 200.0)
        self.compound_return.setValue((asset.compound_return * 100) if asset else 10.0)
        numbers.addRow("Retorno compuesto", self.compound_return)

        self.volatility = self._percent(0.0, 200.0)
        self.volatility.setValue((asset.volatility * 100) if asset else 12.0)
        numbers.addRow("Volatilidad", self.volatility)

        self.yield_ = self._percent(0.0, 100.0)
        self.yield_.setValue((asset.yield_ * 100) if asset else 0.0)
        numbers.addRow("Yield", self.yield_)

        layout.addLayout(numbers)

        self.notes = QPlainTextEdit(asset.notes if asset else "")
        self.notes.setPlaceholderText(
            "De dónde salen estos números y qué supuesto de moneda usaste."
        )
        self.notes.setMaximumHeight(60)
        layout.addWidget(QLabel("Notas"))
        layout.addWidget(self.notes)

        layout.addWidget(self.preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_preview()

    @staticmethod
    def _percent(low: float, high: float) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(low, high)
        box.setDecimals(2)
        box.setSuffix(" %")
        box.setSingleStep(0.25)
        return box

    def _correlation_source(self) -> str | None:
        if self.source_single.isChecked() and self.source_asset.currentText():
            return self.source_asset.currentText()
        return None

    def _update_preview(self, *_):
        """Lo que la app va a derivar, dicho antes de aceptar.

        Sin esto, elegir una clase (o un activo puntual) es una caja negra y el
        analista no puede saber con qué está simulando en realidad.
        """
        try:
            self.preview.setText(
                derived_preview(
                    self.base, self.asset_class.currentText(),
                    self._correlation_source(), PREVIEW_AGAINST,
                )
            )
        except ValueError as exc:
            self.preview.setText(str(exc))

    def _on_accept(self):
        nombre = self.name.text().strip()
        if not nombre:
            QMessageBox.warning(self, "Falta el nombre", "El activo necesita un nombre.")
            return

        chocados = {n.casefold() for n in self.cmas.names}
        if self.original is not None:
            chocados.discard(self.original.name.casefold())
        if nombre.casefold() in chocados:
            QMessageBox.warning(
                self,
                "Nombre repetido",
                f"Ya existe una clase de activo llamada '{nombre}'.",
            )
            return

        if self.volatility.value() == 0 and self.compound_return.value() > 0:
            if QMessageBox.question(
                self,
                "Volatilidad en cero",
                "Un activo con retorno positivo y volatilidad cero es dinero gratis "
                "sin riesgo: dominará cualquier comparación.\n\n¿Seguro?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return

        self.accept()

    def asset(self) -> AssetClass:
        return AssetClass(
            name=self.name.text().strip(),
            compound_return=self.compound_return.value() / 100.0,
            volatility=self.volatility.value() / 100.0,
            yield_=self.yield_.value() / 100.0,
            origin=ORIGIN_CUSTOM,
            asset_class=self.asset_class.currentText(),
            correlation_source=self._correlation_source(),
            notes=self.notes.toPlainText().strip(),
        )


# ----------------------------------------------------------------------
# Fusión al abrir un caso
# ----------------------------------------------------------------------


def _same(a: AssetClass, b: AssetClass) -> bool:
    return (
        abs(a.compound_return - b.compound_return) < 1e-9
        and abs(a.volatility - b.volatility) < 1e-9
        and abs(a.yield_ - b.yield_) < 1e-9
        and a.asset_class == b.asset_class
        and a.correlation_source == b.correlation_source
    )


class ConflictDialog(QDialog):
    """Un activo propio del caso difiere del de la librería.

    No se puede resolver en silencio. Imponer la librería haría que el mismo
    archivo diera proyecciones distintas en dos computadores —exactamente la
    falla que motivó bloquear el panel de Activos—; imponer el caso pisaría
    supuestos que quizá se usan con otros clientes.
    """

    USAR_CASO, ADOPTAR, USAR_LIBRERIA = range(3)

    def __init__(self, conflictos: list[tuple[AssetClass, AssetClass]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Supuestos distintos")
        self.setMinimumWidth(680)
        self.choice = self.USAR_CASO

        layout = QVBoxLayout(self)
        intro = QLabel(
            f"{len(conflictos)} activo(s) propio(s) de este caso tienen supuestos "
            "distintos a los de tu librería."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        table = QTableWidget(len(conflictos), 5)
        table.setHorizontalHeaderLabels(
            ["Activo", "Retorno (caso / librería)", "Volatilidad", "Yield", "Clase"]
        )
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for row, (del_caso, de_libreria) in enumerate(conflictos):
            table.setItem(row, 0, QTableWidgetItem(del_caso.name))
            for col, attr in enumerate(
                ("compound_return", "volatility", "yield_"), start=1
            ):
                a, b = getattr(del_caso, attr), getattr(de_libreria, attr)
                item = QTableWidgetItem(f"{a:.2%}  /  {b:.2%}")
                if abs(a - b) > 1e-9:
                    item.setText("▸ " + item.text())
                table.setItem(row, col, item)
            clase = QTableWidgetItem(
                f"{del_caso.asset_class}  /  {de_libreria.asset_class}"
            )
            if del_caso.asset_class != de_libreria.asset_class:
                clase.setText("▸ " + clase.text())
            table.setItem(row, 4, clase)
        table.resizeColumnsToContents()
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)

        nota = QLabel(
            status_dot(
                STATUS_WARNING,
                "Un cambio de <b>clase</b> pesa más que uno de número: cambia las "
                "correlaciones derivadas.",
            )
        )
        nota.setWordWrap(True)
        layout.addWidget(nota)

        from PySide6.QtWidgets import QRadioButton

        self.opciones = [
            QRadioButton("Usar los valores del caso, solo en esta sesión"),
            QRadioButton("Adoptar los valores del caso en mi librería"),
            QRadioButton("Usar los valores de mi librería"),
        ]
        self.opciones[0].setChecked(True)
        explicacion = QLabel(
            "Por defecto manda el caso: un informe ya entregado a un cliente tiene "
            "que poder reproducirse tal cual."
        )
        explicacion.setWordWrap(True)
        explicacion.setStyleSheet(f"color: {INK_SOFT};")
        for boton in self.opciones:
            layout.addWidget(boton)
        layout.addWidget(explicacion)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._on_accept)
        layout.addWidget(buttons)

    def _on_accept(self):
        for i, boton in enumerate(self.opciones):
            if boton.isChecked():
                self.choice = i
        self.accept()


def merge_custom_assets(parent, cmas: CMASet, del_caso: list[AssetClass]) -> list[str]:
    """Incorpora a la librería en memoria los activos propios de un caso.

    Devuelve las líneas de aviso para la barra de estado. La invariante que
    garantiza es la que importa: **al terminar, todo activo propio del caso está
    en `cmas`**, de modo que la matriz extendida lo cubrirá y nunca se llegará al
    error de cobertura del motor.
    """
    if not del_caso:
        return []

    avisos: list[str] = []
    nuevos: list[AssetClass] = []
    conflictos: list[tuple[AssetClass, AssetClass]] = []

    for asset in del_caso:
        try:
            existente = cmas.by_name(asset.name)
        except KeyError:
            nuevos.append(asset)
            continue
        if not _same(asset, existente):
            conflictos.append((asset, existente))

    if nuevos:
        nombres = ", ".join(a.name for a in nuevos)
        guardar = QMessageBox.question(
            parent,
            "Activos propios del caso",
            f"Este caso usa activos propios que no tienes en tu librería:\n\n{nombres}\n\n"
            "¿Añadirlos a tu librería para reusarlos con otros clientes?\n\n"
            "Si dices que no, se usarán igual en este caso pero no se guardarán.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        ) == QMessageBox.StandardButton.Yes
        for asset in nuevos:
            cmas.add(asset)
        if guardar:
            from ..io import library

            library.save_cmas(cmas)
            avisos.append(f"Añadidos a tu librería: {nombres}")
        else:
            avisos.append(f"{nombres} se usan solo en este caso")

    if conflictos:
        dialog = ConflictDialog(conflictos, parent)
        dialog.exec()
        if dialog.choice == ConflictDialog.USAR_LIBRERIA:
            avisos.append(
                f"{len(conflictos)} activo(s) usan los supuestos de tu librería, "
                "distintos a los del caso"
            )
        else:
            for del_caso_asset, existente in conflictos:
                existente.compound_return = del_caso_asset.compound_return
                existente.volatility = del_caso_asset.volatility
                existente.yield_ = del_caso_asset.yield_
                existente.asset_class = del_caso_asset.asset_class
                existente.correlation_source = del_caso_asset.correlation_source
            if dialog.choice == ConflictDialog.ADOPTAR:
                from ..io import library

                library.save_cmas(cmas)
                avisos.append("Tu librería adoptó los supuestos del caso")
            else:
                avisos.append("Se usan los supuestos del caso en esta sesión")

    return avisos
