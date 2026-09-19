"""Captura cada pantalla de la app para el repaso visual.

**No usa la plataforma `offscreen` de Qt a propósito.** Con esa plataforma Qt
no carga las fuentes del sistema y dibuja todo el texto de los widgets como
cuadros vacíos: las capturas salen inservibles justo para lo que se necesitan,
que es juzgar textos cortados, controles recortados y tipografía. Se usa la
plataforma real de Windows y la ventana se captura con `grab()`, que funciona
aunque la ventana no esté al frente.

Uso:
    python tools/screenshot.py [carpeta de salida]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# La plataforma real es el punto de todo esto: si algo la forzó a offscreen
# (por ejemplo una corrida previa de los tests en la misma consola), se quita.
os.environ.pop("QT_QPA_PLATFORM", None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# (índice de la pestaña de entrada, sub-pestaña de estrategia o None, nombre)
INPUT_SHOTS = [
    (0, None, "escenario"),
    (1, 0, "estrategias-pesos"),
    (1, 1, "estrategias-flujos"),
    (1, 2, "estrategias-credito"),
    (1, 3, "estrategias-capital"),
    (2, None, "activos-cmas"),
    (3, None, "correlaciones"),
    (4, None, "configuracion"),
]

RESULT_SHOTS = ["distribucion", "supuestos", "stress", "deuda"]


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("build/screenshots")
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.png"):
        stale.unlink()

    from PySide6.QtWidgets import QApplication

    from gbp.engine.montecarlo import simulate
    from gbp.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1500, 940)
    window.show()
    app.processEvents()

    result = simulate(window.scenario, window.cmas, window.correlations, window.settings)
    window.results.show_result(result, window.settings, window.scenario.horizon)
    app.processEvents()

    index = 1
    for tab, subtab, label in INPUT_SHOTS:
        window.inputs.setCurrentIndex(tab)
        if subtab is not None:
            window.strategies_panel.tabs.setCurrentIndex(subtab)
        _settle(app)
        path = out_dir / f"{index:02d}_{label}.png"
        window.grab().save(str(path))
        print(f"  {path}")
        index += 1

    # Con las entradas en Estrategias, se recorren las pestañas de resultado.
    window.inputs.setCurrentIndex(1)
    for offset, label in enumerate(RESULT_SHOTS):
        window.results.setCurrentIndex(offset)
        _settle(app)
        path = out_dir / f"{index:02d}_{label}.png"
        window.grab().save(str(path))
        print(f"  {path}")
        index += 1

    window.close()
    print(f"\n{index - 1} capturas en {out_dir.resolve()}")
    return 0


def _settle(app):
    """Deja que Qt y matplotlib terminen de dibujar antes de capturar."""
    for _ in range(3):
        app.processEvents()


if __name__ == "__main__":
    sys.exit(main())
