"""Ejecución de la simulación en un hilo aparte, para no congelar la interfaz."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from ..engine.montecarlo import simulate
from ..model.assets import CMASet
from ..model.correlation import CorrelationMatrix
from ..model.results import SimulationResult
from ..model.scenario import Scenario, SimulationSettings


class SimulationCancelled(Exception):
    """La corrida se interrumpió a pedido, típicamente al cerrar la ventana."""


class SimulationWorker(QObject):
    """Corre la simulación y publica progreso, resultado o error.

    El worker recibe **copias** del caso y de la configuración, no los objetos
    vivos de la ventana: si el usuario edita mientras corre, la corrida sigue
    simulando lo que se le pidió y no una mezcla de antes y después.
    """

    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

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
        self._cancel = False
        self._last_reported = (-1, "")

    def cancel(self):
        """Pide que la corrida se detenga en el próximo aviso de progreso.

        Un QThread no se puede matar a mitad de un cálculo sin riesgo, así que
        la cancelación es cooperativa: el motor avisa progreso una vez por año
        simulado y ahí se comprueba la bandera.
        """
        self._cancel = True

    def _on_progress(self, done: int, total: int, label: str):
        if self._cancel:
            raise SimulationCancelled()
        # Un aviso por punto porcentual basta para la barra. Con muchas
        # estrategias y horizontes largos, emitir cada año inunda el hilo de la
        # interfaz de señales que no cambian nada visible.
        step = (100 * done) // total if total else done
        if (step, label) != self._last_reported:
            self._last_reported = (step, label)
            self.progress.emit(done, total, label)

    def run(self):
        try:
            result: SimulationResult = simulate(
                self.scenario,
                self.cmas,
                self.correlations,
                self.settings,
                progress=self._on_progress,
            )
        except SimulationCancelled:
            self.cancelled.emit()
        except ValueError as exc:
            # Errores de validación del escenario: son del usuario, no del programa.
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"La simulación falló: {exc}")
        else:
            self.finished.emit(result)
        finally:
            # El hilo se detiene a sí mismo, directo y no por señal: al cerrar,
            # la ventana espera con `wait()` y tiene bloqueado el hilo principal,
            # así que un `quit` encolado hacia allá no llegaría nunca.
            QThread.currentThread().quit()


class TaskWorker(QObject):
    """Corre una función cualquiera fuera del hilo de la interfaz.

    Para trabajo que no tiene progreso por años —escribir el PDF, correr el
    solver—, con el mismo contrato de señales que la simulación.
    """

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, expected=(OSError, ValueError)):
        super().__init__()
        self.fn = fn
        self.expected = expected

    def run(self):
        try:
            value = self.fn()
        except self.expected as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"Falló: {exc}")
        else:
            self.finished.emit(value)
        finally:
            QThread.currentThread().quit()


def start_task(parent, fn, on_finished, on_failed) -> tuple[QThread, TaskWorker]:
    """Arranca `fn` en un hilo y conecta las devoluciones."""
    thread = QThread(parent)
    worker = TaskWorker(fn)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(on_finished)
    worker.failed.connect(on_failed)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread, worker


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
    thread.finished.connect(worker.deleteLater)
    # Sin esto queda un QThread huérfano, hijo de la ventana, por cada corrida.
    thread.finished.connect(thread.deleteLater)

    thread.start()
    return thread, worker
