"""Ventana principal de GBP."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
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

from ..io import library
from ..io.caseio import (
    EXTENSION,
    CaseFormatError,
    custom_assets_from_dict,
    from_dict,
    read_case,
    save_case,
)
from ..io.report import build_report
from ..model.correlation import CorrelationMatrix
from ..model.custom_assets import custom_pairs, extend_correlations, resolver_for
from .brand import app_icon, symbol_pixmap, wordmark_pixmap
from .custom_asset_dialog import merge_custom_assets
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
        # `base_correlations` son las 59 publicadas y no cambian nunca;
        # `correlations` es la extendida con los activos propios, y es la que ve
        # todo el resto de la app —incluido el motor, que por eso no se entera.
        self.base_correlations = CorrelationMatrix.load()
        self.correlations = self.base_correlations
        self.resolver = None
        self._rebuild_market_model()
        # Se restaura el caso de la sesión anterior. El caso de ejemplo solo
        # aparece la primera vez: volver a ver los mismos supuestos de fábrica
        # después de haber cargado un caso real es perder trabajo.
        restored, restored_path = library.load_session()
        self.scenario = restored if restored is not None else build_sample_case()
        self._restored_session = restored is not None
        self.current_path: Path | None = restored_path
        self._thread = None
        self._worker = None

        self._session_timer = QTimer(self)
        self._session_timer.setSingleShot(True)
        self._session_timer.timeout.connect(self._save_session_now)

        self._build_ui()
        self._build_menu()
        self._refresh_dependent_views()
        if self._restored_session:
            nombre = self.current_path.name if self.current_path else self.scenario.name
            self.status.setText(f"Se restauró la sesión anterior: {nombre}")

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
            self.scenario, self.cmas, self.available_assets, self.resolver
        )
        self.assets_panel = AssetsPanel(self.cmas, self.base_correlations)
        self.correlation_panel = CorrelationPanel(self.correlations, self.resolver)
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
        self.scenario_panel.reset_requested.connect(self.reset_case)
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
        self._schedule_session_save()

    def _schedule_session_save(self):
        """Guarda la sesión poco después del último cambio.

        No basta con guardar al cerrar: un cierre inesperado —o matar el proceso—
        se lleva todo lo cargado. Se hace con retardo porque `changed` se emite
        en cada tecla de cada campo, y escribir el JSON en cada pulsación sería
        una escritura a disco por letra.
        """
        self._session_timer.start(1500)

    def _save_session_now(self):
        try:
            library.save_session(self.scenario, self.current_path)
        except OSError:
            pass  # que no se pueda guardar la red no debe romper la app

    def _rebuild_market_model(self):
        """Recalcula lo que depende de los activos propios de la librería.

        Un único sitio para que la matriz extendida y el resolvedor de clases no
        puedan quedar desacompasados entre sí. Es barato —un producto de 59×k—
        así que se llama sin miramientos.
        """
        self.correlations = extend_correlations(
            self.base_correlations, custom_pairs(self.cmas)
        )
        self.resolver = resolver_for(self.cmas, self.base_correlations)

    def _on_assets_changed(self):
        self._rebuild_market_model()
        self.strategies_panel.reload(
            self.scenario, self.cmas, self.available_assets, self.resolver
        )
        self.correlation_panel.set_correlations(self.correlations, self.resolver)
        self._refresh_dependent_views()

    def _on_settings_changed(self):
        if self.results.result is not None:
            self.results.show_result(
                self.results.result, self.settings, self.scenario.horizon
            )

    def _refresh_dependent_views(self):
        self.correlation_panel.set_used_assets(self.scenario.asset_names)
        self.results.show_allocation(self.scenario, self.resolver)
        title = self.scenario.name
        if self.current_path:
            title = f"{title} — {self.current_path.name}"
        self.setWindowTitle(f"GBP — {title}")

    def _reload_all(self):
        self.scenario_panel.reload(self.scenario)
        # La librería puede haber cambiado por fuera del panel: abrir un caso
        # fusiona sus activos propios. Sin esto, la tabla se queda mostrando la
        # librería de antes.
        self.assets_panel.reload(self.cmas)
        self.correlation_panel.set_correlations(self.correlations, self.resolver)
        self.strategies_panel.reload(
            self.scenario, self.cmas, self.available_assets, self.resolver
        )
        self.results.clear()
        self.export_action.setEnabled(False)  # el informe siempre describe una corrida
        self._refresh_dependent_views()
        self._schedule_session_save()

    # ------------------------------------------------------------------
    def new_case(self):
        self.scenario = empty_case()
        self.current_path = None
        # Se olvida la sesión guardada además de vaciar el caso: si no, un cierre
        # inesperado antes del siguiente guardado resucitaría lo que se acaba de
        # borrar.
        library.clear_session()
        self._reload_all()
        self.status.setText("Caso nuevo. Los supuestos de la librería se conservan.")

    def reset_case(self):
        """«Empezar de cero» desde el panel de Escenario, con confirmación.

        Es destructivo y no se puede deshacer, así que pregunta aunque ya haya
        un «Nuevo caso» en el menú que no lo hace: el botón está a un clic y a
        la vista, el menú no.
        """
        if QMessageBox.question(
            self,
            "Empezar de cero",
            "¿Vaciar el caso por completo?\n\n"
            "Se borran el capital, el horizonte, la inflación y todas las "
            "estrategias con sus pesos, flujos y créditos, y se olvida la sesión "
            "guardada.\n\n"
            "Los supuestos de mercado y la configuración de la app no se tocan. "
            "Esto no se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.new_case()
        self.status.setText("Caso vacío. Empieza cargando el escenario y una estrategia.")

    def load_sample(self):
        self.scenario = build_sample_case()
        self.current_path = None
        self._reload_all()
        self.status.setText("Caso de ejemplo cargado.")

    def open_case(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir caso", "", FILE_FILTER)
        if not path:
            return
        self.open_case_path(path)

    def open_case_path(self, path: str | Path):
        """Abre un caso desde una ruta: el menú, o Windows con «Abrir con → GBP»."""
        try:
            payload = read_case(path)
            scenario = from_dict(payload)
            propios = custom_assets_from_dict(payload)
        except (CaseFormatError, OSError) as exc:
            QMessageBox.critical(self, "No se pudo abrir el caso", str(exc))
            return

        # La fusión va **antes** de adoptar el caso: si el usuario cancelara a
        # mitad, es preferible quedarse con el caso anterior intacto que con uno
        # cargado a medias y sin sus supuestos.
        avisos = merge_custom_assets(self, self.cmas, propios)

        self.scenario = scenario
        self.current_path = Path(path)
        self._rebuild_market_model()
        self._reload_all()

        mensaje = f"Caso abierto: {self.current_path.name}"
        if avisos:
            mensaje += " · " + " · ".join(avisos)
        self.status.setText(mensaje)

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
            # Con la librería, para que los activos propios que el caso usa
            # viajen dentro y se pueda abrir en otro computador.
            save_case(self.scenario, path, self.cmas)
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
                "corrida concreta, con su número de caminos.",
            )
            return

        has_debt = any(s.debt.max() > 0 for s in result.strategies)
        dialog = ExportDialog(self.scenario.name, has_debt, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        options = dialog.options()
        options.resolver = self.resolver
        options.cmas = self.cmas
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
                path, options, self.scenario, result, self.settings
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
        # El caso en curso se guarda siempre, se haya guardado a archivo o no.
        # No reemplaza a «Guardar caso»: es la red para no perder lo cargado si
        # la app se cierra antes. Se cancela el guardado con retardo pendiente y
        # se escribe ya, para no depender de un temporizador que quizá no llegue
        # a dispararse.
        self._session_timer.stop()
        self._save_session_now()
        super().closeEvent(event)
