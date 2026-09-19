"""Ejecución de la simulación en un hilo aparte, para no congelar la interfaz."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from ..engine.montecarlo import simulate
from ..model.assets import CMASet
from ..model.correlation import CorrelationMatrix
from ..model.results import SimulationResult
from ..model.scenario import Scenario, SimulationSettings


class SimulationWorker(QObject):
    """Corre la simulación y publica progreso, resultado o error."""

    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        scenario: Scenario,
        cmas: CMASet,
        correlations: CorrelationMatrix,
        settings: SimulationSettings,
    ):
        super().__init__()
        self.scenario = scenario
        self.cmas = cmas
        self.correlations = correlations
        self.settings = settings

    def run(self):
        try:
            result: SimulationResult = simulate(
                self.scenario,
                self.cmas,
                self.correlations,
                self.settings,
                progress=lambda done, total, label: self.progress.emit(done, total, label),
            )
        except ValueError as exc:
            # Errores de validación del escenario: son del usuario, no del programa.
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"La simulación falló: {exc}")
        else:
            self.finished.emit(result)


def start_simulation(
    parent,
    scenario: Scenario,
    cmas: CMASet,
    correlations: CorrelationMatrix,
    settings: SimulationSettings,
    on_progress,
    on_finished,
    on_failed,
) -> tuple[QThread, SimulationWorker]:
    """Arranca la simulación en un hilo y conecta las devoluciones."""
    thread = QThread(parent)
    worker = SimulationWorker(scenario, cmas, correlations, settings)
    worker.moveToThread(thread)

    thread.started.connect(worker.run)
    worker.progress.connect(on_progress)
    worker.finished.connect(on_finished)
    worker.failed.connect(on_failed)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)

    thread.start()
    return thread, worker
