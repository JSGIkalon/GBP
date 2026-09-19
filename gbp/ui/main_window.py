"""Ventana principal de GBP."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..engine.stress import default_scenarios
from ..io import library
from ..io.caseio import EXTENSION, CaseFormatError, load_case, save_case
from ..io.report import build_report
from ..model.correlation import CorrelationMatrix
from .brand import app_icon, symbol_pixmap, wordmark_pixmap
from .export_dialog import ExportDialog
from .panels.assets_panel import AssetsPanel
from .panels.correlation_panel import CorrelationPanel
from .panels.results_panel import ResultsPanel
from .panels.scenario_panel import ScenarioPanel
from .panels.settings_panel import SettingsPanel
from .panels.strategies_panel import StrategiesPanel
from .sample_case import build_sample_case, empty_case
from .theme import INK, NAVY, STYLESHEET
from .worker import start_simulation

FILE_FILTER = f"Casos de GBP (*{EXTENSION});;Todos los archivos (*)"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GBP — Proyección patrimonial")
        self.resize(1440, 900)
        self.setStyleSheet(STYLESHEET)

        icon = app_icon()
        if icon is not None:
            self.setWindowIcon(icon)

        self.cmas = library.load_cmas()
        self.settings = library.load_settings()
        self.correlations = CorrelationMatrix.load()
        self.stress_scenarios = default_scenarios()
        self.scenario = build_sample_case()
        self.current_path: Path | None = None
        self._thread = None
        self._worker = None

        self._build_ui()
        self._build_menu()
        self._refresh_dependent_views()

    # ------------------------------------------------------------------
    @property
    def available_assets(self) -> list[str]:
        """Clases que se pueden usar: están en la librería y en la matriz del LTCMA."""
        known = set(self.correlations.names)
        return [name for name in self.cmas.names if name in known]

    def _build_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setSpacing(12)

        layout.addLayout(self._build_brand_bar())

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Entradas ---------------------------------------------------
        # Los flujos y el crédito ya no son pestañas propias: viven dentro de
        # cada estrategia, porque son suyos y no del escenario.
        self.inputs = QTabWidget()
        self.scenario_panel = ScenarioPanel(self.scenario)
        self.strategies_panel = StrategiesPanel(
            self.scenario, self.cmas, self.available_assets
        )
        self.assets_panel = AssetsPanel(self.cmas)
        self.correlation_panel = CorrelationPanel(self.correlations)
        self.settings_panel = SettingsPanel(self.settings)

        # Etiquetas cortas: con los nombres largos las cinco pestañas no caben
        # y Qt las esconde tras flechas de desplazamiento.
        self.inputs.addTab(self.scenario_panel, "Escenario")
        self.inputs.addTab(self.strategies_panel, "Estrategias")
        self.inputs.addTab(self.assets_panel, "Activos")
        self.inputs.addTab(self.correlation_panel, "Correlaciones")
        self.inputs.addTab(self.settings_panel, "Ajustes")
        self.inputs.setTabToolTip(2, "Supuestos de mercado (CMAs): retorno, volatilidad y yield")
        self.inputs.setTabToolTip(4, "Configuración general de la aplicación")

        self.scenario_panel.changed.connect(self._on_scenario_changed)
        self.strategies_panel.changed.connect(self._on_scenario_changed)
        self.assets_panel.changed.connect(self._on_assets_changed)
        self.settings_panel.changed.connect(self._on_settings_changed)

        splitter.addWidget(self.inputs)

        # --- Resultados -------------------------------------------------
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        run_bar = QHBoxLayout()
        run_bar.setSpacing(16)
        self.run_button = QPushButton("Correr simulación")
        self.run_button.setObjectName("runButton")  # el estilo vive en la hoja Ikalon
        self.run_button.setMinimumHeight(42)
        self.run_button.clicked.connect(self.run_simulation)
        run_bar.addWidget(self.run_button)

        # La barra muestra el porcentaje: una corrida de 200.000 caminos tarda
        # lo suficiente como para que "está corriendo" no baste.
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(True)
        self.progress.setFormat("%p%")
        self.progress.setMinimumHeight(20)
        self.progress.setMaximumHeight(20)
        run_bar.addWidget(self.progress, 1)

        # La acción se crea aquí porque el botón y la entrada de menú comparten
        # el mismo estado habilitado: sin resultado no hay nada que exportar.
        self.export_action = QAction("&Exportar informe PDF…", self)
        self.export_action.setEnabled(False)
        self.export_action.triggered.connect(self.export_report)

        self.export_button = QPushButton("Exportar PDF")
        self.export_button.setMinimumHeight(42)
        self.export_button.setEnabled(False)
        self.export_button.setToolTip(
            "Genera el informe de la última corrida. Se habilita al simular."
        )
        self.export_button.clicked.connect(self.export_report)
        self.export_action.changed.connect(
            lambda: self.export_button.setEnabled(self.export_action.isEnabled())
        )
        run_bar.insertWidget(1, self.export_button)  # junto a «Correr», antes de la barra

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {INK};")
        run_bar.addWidget(self.status, 2)
        right_layout.addLayout(run_bar)

        self.results = ResultsPanel()
        right_layout.addWidget(self.results, 1)

        splitter.addWidget(right)
        # Los resultados son el foco de la pantalla; las entradas se consultan y
        # se dejan quietas. Los factores de estiramiento no bastan: hay que fijar
        # los tamaños iniciales o Qt reparte según el ancho que pide cada panel,
        # y las tablas de entrada piden mucho.
        # Las tablas de entrada (pesos, flujos con siete columnas) necesitan
        # ancho real: con 500 px salían recortadas.
        self.inputs.setMinimumWidth(560)
        right.setMinimumWidth(620)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([700, 800])
        layout.addWidget(splitter)

        self.setCentralWidget(central)
        self.statusBar().showMessage(
            f"Librería de supuestos: {library.library_path()}"
        )

    def _build_brand_bar(self) -> QHBoxLayout:
        """Símbolo a la izquierda y wordmark a la derecha, como manda el manual.

        Sin franja de color de fondo y sin marco: es solo la marca sobre blanco.
        """
        bar = QHBoxLayout()
        bar.setContentsMargins(4, 2, 4, 0)

        symbol = symbol_pixmap(28)
        if symbol is not None:
            symbol_label = QLabel()
            symbol_label.setPixmap(symbol)
            bar.addWidget(symbol_label)

        title = QLabel("Proyección patrimonial")
        title.setStyleSheet(f"color: {NAVY}; font-size: 15px; font-weight: 600;")
        bar.addWidget(title)

        bar.addStretch(1)

        wordmark = wordmark_pixmap(22)
        if wordmark is not None:
            wordmark_label = QLabel()
            wordmark_label.setPixmap(wordmark)
            bar.addWidget(wordmark_label)

        return bar

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("&Archivo")

        new_action = QAction("&Nuevo caso", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self.new_case)
        file_menu.addAction(new_action)

        sample_action = QAction("Cargar caso de &ejemplo", self)
        sample_action.triggered.connect(self.load_sample)
        file_menu.addAction(sample_action)

        file_menu.addSeparator()

        open_action = QAction("&Abrir caso…", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_case)
        file_menu.addAction(open_action)

        save_action = QAction("&Guardar caso", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.save_case_as_current)
        file_menu.addAction(save_action)

        save_as_action = QAction("Guardar caso &como…", self)
        save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        save_as_action.triggered.connect(self.save_case_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()
        quit_action = QAction("&Salir", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        run_menu = self.menuBar().addMenu("&Análisis")
        run_action = QAction("&Correr simulación", self)
        run_action.setShortcut("F5")
        run_action.triggered.connect(self.run_simulation)
        run_menu.addAction(run_action)

        run_menu.addSeparator()
        # Se deja la acción también en el menú, pero el botón vive junto a los
        # resultados: es ahí donde se decide exportar, no en Archivo.
        self.export_action.setShortcut("Ctrl+E")
        run_menu.addAction(self.export_action)

        help_menu = self.menuBar().addMenu("A&yuda")
        about_action = QAction("&Acerca de GBP", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    # ------------------------------------------------------------------
    def _on_scenario_changed(self):
        self._refresh_dependent_views()

    def _on_assets_changed(self):
        self.strategies_panel.reload(self.scenario, self.cmas, self.available_assets)
        self._refresh_dependent_views()

    def _on_settings_changed(self):
        if self.results.result is not None:
            self.results.show_result(
                self.results.result, self.settings, self.scenario.horizon
            )

    def _refresh_dependent_views(self):
        self.correlation_panel.set_used_assets(self.scenario.asset_names)
        self.results.show_stress(self.scenario, self.stress_scenarios)
        title = self.scenario.name
        if self.current_path:
            title = f"{title} — {self.current_path.name}"
        self.setWindowTitle(f"GBP — {title}")

    def _reload_all(self):
        self.scenario_panel.reload(self.scenario)
        self.strategies_panel.reload(self.scenario, self.cmas, self.available_assets)
        self.results.clear()
        self.export_action.setEnabled(False)  # el informe siempre describe una corrida
        self._refresh_dependent_views()

    # ------------------------------------------------------------------
    def new_case(self):
        self.scenario = empty_case()
        self.current_path = None
        self._reload_all()
        self.status.setText("Caso nuevo. Los supuestos de la librería se conservan.")

    def load_sample(self):
        self.scenario = build_sample_case()
        self.current_path = None
        self._reload_all()
        self.status.setText("Caso de ejemplo cargado.")

    def open_case(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir caso", "", FILE_FILTER)
        if not path:
            return
        try:
            self.scenario = load_case(path)
        except (CaseFormatError, OSError) as exc:
            QMessageBox.critical(self, "No se pudo abrir el caso", str(exc))
            return
        self.current_path = Path(path)
        self._reload_all()
        self.status.setText(f"Caso abierto: {self.current_path.name}")

    def save_case_as_current(self):
        if self.current_path is None:
            self.save_case_as()
            return
        self._write_case(self.current_path)

    def save_case_as(self):
        suggested = f"{self.scenario.name}{EXTENSION}".replace("/", "-")
        path, _ = QFileDialog.getSaveFileName(self, "Guardar caso", suggested, FILE_FILTER)
        if not path:
            return
        if not path.endswith(EXTENSION) and not path.endswith(".json"):
            path += EXTENSION
        self._write_case(Path(path))

    def _write_case(self, path: Path):
        try:
            save_case(self.scenario, path)
        except OSError as exc:
            QMessageBox.critical(self, "No se pudo guardar", str(exc))
            return
        self.current_path = path
        self.status.setText(f"Caso guardado en {path.name}")
        self._refresh_dependent_views()

    # ------------------------------------------------------------------
    def run_simulation(self):
        if self._thread is not None and self._thread.isRunning():
            return

        try:
            self.scenario.validate(self.cmas)
        except ValueError as exc:
            QMessageBox.warning(self, "Revisa el caso", str(exc))
            return

        self.run_button.setEnabled(False)
        self.export_action.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)  # indeterminado hasta el primer aviso
        self.status.setText(f"Corriendo {self.settings.n_paths:,} simulaciones…")

        self._thread, self._worker = start_simulation(
            self,
            self.scenario,
            self.cmas,
            self.correlations,
            self.settings,
            self._on_progress,
            self._on_finished,
            self._on_failed,
        )

    def _on_progress(self, done: int, total: int, label: str):
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        self.status.setText(label)

    def _on_finished(self, result):
        self.results.show_result(result, self.settings, self.scenario.horizon)
        self.run_button.setEnabled(True)
        self.export_action.setEnabled(True)
        self.progress.setVisible(False)
        best = max(result.strategies, key=lambda s: s.success_probability)
        self.status.setText(
            f"{result.n_paths:,} simulaciones · mejor probabilidad de éxito: "
            f"{best.success_probability:.1%} ({best.name})"
        )
        self._thread = None

    def _on_failed(self, message: str):
        self.run_button.setEnabled(True)
        self.export_action.setEnabled(self.results.result is not None)
        self.progress.setVisible(False)
        self.status.setText("La simulación no se completó.")
        QMessageBox.warning(self, "No se pudo simular", message)
        self._thread = None

    # ------------------------------------------------------------------
    def export_report(self):
        """Informe PDF de la última corrida, para el archivo y para el cliente."""
        result = self.results.result
        if result is None:
            QMessageBox.information(
                self,
                "Nada que exportar",
                "Corre la simulación antes de exportar: el informe documenta una "
                "corrida concreta, con su semilla y su número de caminos.",
            )
            return

        has_debt = any(s.debt.max() > 0 for s in result.strategies)
        dialog = ExportDialog(self.scenario.name, has_debt, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        options = dialog.options()
        suggested = f"{options.title} — {self.scenario.name}.pdf".replace("/", "-")
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar informe", suggested, "Documentos PDF (*.pdf)"
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"

        dialog.remember()
        try:
            written = build_report(
                path, options, self.scenario, result, self.settings, self.stress_scenarios
            )
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "No se pudo exportar", str(exc))
            return

        self.status.setText(f"Informe exportado a {written.name}")
        if QMessageBox.question(
            self,
            "Informe listo",
            f"El informe se guardó en:\n{written}\n\n¿Abrirlo?",
        ) == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(written)))

    # ------------------------------------------------------------------
    def show_about(self):
        QMessageBox.information(
            self,
            "Acerca de GBP",
            "<b>GBP — Proyección patrimonial</b><br><br>"
            "Simulación Monte Carlo de patrimonio sobre un portafolio multiactivo, "
            "con flujos, apalancamiento y comparación de estrategias.<br><br>"
            f"<b>Correlaciones:</b> {self.correlations.source or 'LTCMA'}<br>"
            f"<b>Clases de activo:</b> {len(self.correlations.names)}<br>"
            f"<b>Librería de supuestos:</b> {library.library_path()}<br><br>"
            "<span style='color:#5C6770'>Las proyecciones son hipotéticas, no reflejan "
            "resultados reales y no garantizan rendimientos futuros.</span>",
        )

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)
        library.save_cmas(self.cmas)
        library.save_settings(self.settings)
        super().closeEvent(event)
