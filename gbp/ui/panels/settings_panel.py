"""Panel de configuración general de la app (no del caso)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
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
from ..theme import INK, INK_SOFT, use_thousands_dot


class SettingsPanel(QWidget):
    """Número de simulaciones y años hito.

    La unidad de los resultados ya no se configura aquí: nominal y moneda de hoy
    son dos pestañas de resultados, no una opción. La semilla del sorteo
    tampoco: queda fija en `SimulationSettings.seed` para que toda corrida sea
    reproducible sin que nadie tenga que saber que existe.
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
        intro.setStyleSheet(f"color: {INK};")
        layout.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(10)

        self.n_paths = QSpinBox()
        self.n_paths.setRange(100, 1_000_000)
        self.n_paths.setSingleStep(1_000)
        use_thousands_dot(self.n_paths)
        # Al terminar de editar y no en cada tecla: escribir 200000 eran seis
        # guardados a disco y seis avisos a la ventana por cifras intermedias.
        self.n_paths.editingFinished.connect(self._on_change)
        form.addRow("Número de simulaciones", self.n_paths)

        self.milestones = QLineEdit()
        self.milestones.setPlaceholderText("5, 10, 15, 20, 25, 30")
        self.milestones.editingFinished.connect(self._on_change)
        form.addRow("Años hito a graficar", self.milestones)

        layout.addLayout(form)

        note = QLabel(
            "10.000 simulaciones es el estándar y corre en menos de un segundo. Subirlo "
            "estabiliza las colas de la distribución; bajarlo solo acelera casos de prueba."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {INK_SOFT};")
        layout.addWidget(note)

        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        self.path_label.setStyleSheet(f"color: {INK_SOFT};")
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

    def commit(self):
        """Aplica lo que esté escrito aunque el campo no haya perdido el foco.

        La ventana lo llama antes de simular, para no correr con el número de
        simulaciones anterior si se pulsó F5 con el cursor todavía en el campo.
        """
        self._on_change()

    def _on_change(self, *_):
        if self._loading:
            return
        n_paths = self.n_paths.value()
        milestones = self._parse_milestones()
        if (n_paths, milestones) == (self.settings.n_paths, self.settings.milestone_years):
            return
        self.settings.n_paths = n_paths
        self.settings.milestone_years = milestones
        try:
            library.save_settings(self.settings)
        except OSError:
            pass  # la configuración en memoria sigue valiendo para esta sesión
        self.changed.emit()

    def _reset(self):
        defaults = SimulationSettings()
        self.settings.n_paths = defaults.n_paths
        self.settings.milestone_years = list(defaults.milestone_years)
        library.save_settings(self.settings)
        self.reload(self.settings)
        self.changed.emit()
