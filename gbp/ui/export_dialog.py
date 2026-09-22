"""Ventana de exportación del informe PDF.

Lo que se exporta no es una captura de pantalla: es un documento que queda como
registro de la corrida y que puede salir hacia el cliente. Por eso la ventana
pide los datos de la portada —título, cliente, fecha, quién lo preparó— y deja
elegir qué secciones entran, en vez de exportar siempre lo mismo.

El autor, el cliente y el título se recuerdan entre corridas: quien prepara los
informes no cambia de un caso a otro y volver a escribirlo cada vez es fricción
sin motivo.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..io import library
from ..io.report import ReportOptions
from .theme import INK_SOFT


class ExportDialog(QDialog):
    """Datos de portada y secciones del informe."""

    def __init__(self, scenario_name: str, has_debt: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Exportar informe PDF")
        self.setMinimumWidth(560)

        defaults = library.load_report_defaults()

        layout = QVBoxLayout(self)

        intro = QLabel(
            "El PDF deja el registro de esta corrida —fecha, semilla y número de "
            "caminos— y es lo que se entrega al cliente."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(10)

        self.title = QLineEdit(defaults.get("title") or "Proyección patrimonial")
        form.addRow("Título del informe", self.title)

        self.client = QLineEdit(defaults.get("client", ""))
        self.client.setPlaceholderText("Nombre del cliente o de la familia")
        form.addRow("Cliente", self.client)

        self.author = QLineEdit(defaults.get("author", ""))
        self.author.setPlaceholderText("Quién prepara el informe")
        form.addRow("Preparado por", self.author)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        form.addRow("Fecha", self.date_edit)

        self.case_label = QLabel(scenario_name)
        self.case_label.setStyleSheet(f"color: {INK_SOFT};")
        form.addRow("Caso", self.case_label)

        layout.addLayout(form)

        self.notes = QPlainTextEdit(defaults.get("notes", ""))
        self.notes.setPlaceholderText(
            "Notas que van en la portada: contexto de la reunión, qué se comparó, "
            "qué queda pendiente…"
        )
        self.notes.setMaximumHeight(90)
        layout.addWidget(QLabel("Notas de portada"))
        layout.addWidget(self.notes)

        sections = QGroupBox("Secciones")
        sections_layout = QVBoxLayout(sections)
        self.inputs = QCheckBox("Supuestos del caso (pesos, flujos y crédito)")
        self.allocation = QCheckBox("Asignación de activos")
        self.distribution = QCheckBox("Distribución del patrimonio")
        self.summary = QCheckBox("Supuestos resumen por estrategia")
        self.debt = QCheckBox("Deuda y llamadas a margen")
        self.flows = QCheckBox("Ingresos y retiros año por año (anexo)")
        self.flows.setToolTip(
            "La serie realizada de aportes y retiros. Es la forma de comprobar que "
            "un flujo indexado crece como se esperaba y que uno porcentual se "
            "recalcula sobre el patrimonio vigente."
        )
        self.disclaimer = QCheckBox("Aviso legal en la portada")
        for box in (self.inputs, self.allocation, self.distribution, self.summary,
                    self.flows, self.disclaimer):
            box.setChecked(True)
            sections_layout.addWidget(box)
        # Sin apalancamiento la sección de deuda no tiene nada que mostrar.
        self.debt.setChecked(has_debt)
        self.debt.setEnabled(has_debt)
        if not has_debt:
            self.debt.setText("Deuda y llamadas a margen (el caso no tiene crédito)")
        # Justo antes del aviso legal, que es el orden en que salen en el PDF.
        sections_layout.insertWidget(4, self.debt)
        annex_note = QLabel(
            "En el cuerpo la única tabla son los supuestos resumen. Las demás salen "
            "al final, en un anexo con una hoja por estrategia que reúne toda su "
            "información y que cada gráfica cita. Se incluyen con su sección."
        )
        annex_note.setWordWrap(True)
        annex_note.setStyleSheet(f"color: {INK_SOFT};")
        sections_layout.addWidget(annex_note)
        layout.addWidget(sections)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Elegir archivo y exportar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    def options(self) -> ReportOptions:
        qdate = self.date_edit.date()
        return ReportOptions(
            title=self.title.text().strip() or "Proyección patrimonial",
            client=self.client.text().strip(),
            author=self.author.text().strip(),
            report_date=date(qdate.year(), qdate.month(), qdate.day()),
            notes=self.notes.toPlainText().strip(),
            include_distribution=self.distribution.isChecked(),
            include_summary=self.summary.isChecked(),
            include_allocation=self.allocation.isChecked(),
            include_debt=self.debt.isChecked(),
            include_inputs=self.inputs.isChecked(),
            include_flows=self.flows.isChecked(),
            include_disclaimer=self.disclaimer.isChecked(),
        )

    def remember(self) -> None:
        """Guarda los datos de portada para la próxima exportación."""
        library.save_report_defaults(
            {
                "title": self.title.text().strip(),
                "client": self.client.text().strip(),
                "author": self.author.text().strip(),
                "notes": self.notes.toPlainText().strip(),
            }
        )
