"""Panel de configuración general de la app (no del caso)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...io import library
from ...model.scenario import SimulationSettings


class SettingsPanel(QWidget):
    """Número de simulaciones, semilla y años hito.

    La unidad de los resultados ya no se configura aquí: nominal y moneda de hoy
    son dos pestañas de resultados, no una opción.
    """

    changed = Signal()

    def __init__(self, settings: SimulationSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._loading = False

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Configuración de la app. Se guarda aparte del caso del cliente y aplica "
            "a todos los análisis."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #1F2A30;")
        layout.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(10)

        self.n_paths = QSpinBox()
        self.n_paths.setRange(100, 1_000_000)
        self.n_paths.setSingleStep(1_000)
        self.n_paths.setGroupSeparatorShown(True)
        self.n_paths.valueChanged.connect(self._on_change)
        form.addRow("Número de simulaciones", self.n_paths)

        self.use_seed = QCheckBox("Usar semilla fija (resultados reproducibles)")
        self.use_seed.setToolTip(
            "Con semilla fija, la misma corrida da exactamente los mismos números "
            "cada vez. Sin ella, cada corrida sortea caminos nuevos."
        )
        self.use_seed.stateChanged.connect(self._on_change)
        form.addRow("", self.use_seed)

        self.seed = QSpinBox()
        self.seed.setRange(0, 2_147_483_647)
        self.seed.setToolTip(
            "Punto de partida del generador de números aleatorios. El número en sí "
            "no significa nada: solo identifica el sorteo. El 42 es una convención."
        )
        self.seed.valueChanged.connect(self._on_change)
        form.addRow("Semilla", self.seed)

        self.milestones = QLineEdit()
        self.milestones.setPlaceholderText("5, 10, 15, 20, 25, 30")
        self.milestones.editingFinished.connect(self._on_change)
        form.addRow("Años hito a graficar", self.milestones)

        layout.addLayout(form)

        note = QLabel(
            "10.000 simulaciones es el estándar y corre en menos de un segundo. Subirlo "
            "estabiliza las colas de la distribución; bajarlo solo acelera casos de prueba.\n\n"
            "La semilla es el punto de partida del generador de números aleatorios. "
            "Con la semilla fija, el mismo caso da exactamente los mismos percentiles "
            "cada vez que se corre: es lo que permite que un informe entregado hace un "
            "mes se pueda reproducir hoy, y que dos personas con el mismo archivo vean "
            "lo mismo. El número en sí no significa nada —el 42 es una convención—; "
            "cambiarlo solo elige otro sorteo, igual de válido. Sin semilla fija, cada "
            "corrida sortea caminos nuevos y los percentiles bailan un poco, que es "
            "útil justamente para ver cuánto de un resultado es ruido del muestreo."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #5C6770;")
        layout.addWidget(note)

        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        self.path_label.setStyleSheet("color: #5C6770;")
        layout.addWidget(self.path_label)

        reset = QPushButton("Restaurar valores por defecto")
        reset.clicked.connect(self._reset)
        layout.addWidget(reset)
        layout.addStretch(1)

        self.reload(settings)

    def reload(self, settings: SimulationSettings):
        self.settings = settings
        self._loading = True
        self.n_paths.setValue(settings.n_paths)
        self.use_seed.setChecked(settings.seed is not None)
        self.seed.setValue(settings.seed if settings.seed is not None else 42)
        self.seed.setEnabled(settings.seed is not None)
        self.milestones.setText(", ".join(str(y) for y in settings.milestone_years))
        self._loading = False
        self.path_label.setText(f"Se guarda en {library.settings_path()}")

    def _parse_milestones(self) -> list[int]:
        raw = self.milestones.text().replace(";", ",").split(",")
        years = []
        for chunk in raw:
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                year = int(float(chunk))
            except ValueError:
                continue
            if year >= 1:
                years.append(year)
        return sorted(set(years)) or [5, 10, 15, 20, 25, 30]

    def _on_change(self, *_):
        if self._loading:
            return
        self.seed.setEnabled(self.use_seed.isChecked())
        self.settings.n_paths = self.n_paths.value()
        self.settings.seed = self.seed.value() if self.use_seed.isChecked() else None
        self.settings.milestone_years = self._parse_milestones()
        library.save_settings(self.settings)
        self.changed.emit()

    def _reset(self):
        defaults = SimulationSettings()
        self.settings.n_paths = defaults.n_paths
        self.settings.seed = defaults.seed
        self.settings.milestone_years = list(defaults.milestone_years)
        library.save_settings(self.settings)
        self.reload(self.settings)
        self.changed.emit()
