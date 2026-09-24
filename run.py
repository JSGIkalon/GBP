"""Punto de entrada de la app GBP."""

from __future__ import annotations

import sys
from pathlib import Path

# Permite correr `python run.py` desde el repositorio sin instalar el paquete.
if __package__ is None and not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))


def smoke_test(out_dir: str) -> int:
    """Abre la ventana, simula el caso de ejemplo, escribe un PDF y sale.

    Existe para probar el **ejecutable empaquetado**, no el código: el build
    recorta del paquete DLLs de Qt que la app no usa, y si alguna resultara
    necesaria el .exe fallaría en la máquina del usuario y no aquí. El script de
    build lo corre al terminar. Un .exe `--windowed` no tiene consola, así que
    el resultado va a un archivo y al código de salida.

    Usa una carpeta de datos propia para no tocar la sesión ni la librería del
    usuario que construye.
    """
    import os
    import traceback

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    os.environ["GBP_DATA_DIR"] = str(out / "datos")
    log = out / "smoke.log"
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication

        from gbp.engine.montecarlo import simulate
        from gbp.io.report import ReportOptions, build_report
        from gbp.model.scenario import SimulationSettings
        from gbp.ui.main_window import MainWindow

        app = QApplication(sys.argv[:1])
        window = MainWindow()
        window.show()
        QTimer.singleShot(1500, app.quit)
        app.exec()

        settings = SimulationSettings(n_paths=2000)
        result = simulate(window.scenario, window.cmas, window.correlations, settings)
        pdf = build_report(out / "smoke.pdf", ReportOptions(), window.scenario, result, settings)
        window.close()
        log.write_text(
            f"ok\nestrategias={len(result)}\npdf={pdf.stat().st_size}\n", encoding="utf-8"
        )
        return 0
    except Exception:  # noqa: BLE001
        log.write_text("error\n" + traceback.format_exc(), encoding="utf-8")
        return 1


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--smoke-test":
        return smoke_test(sys.argv[2])

    from PySide6.QtWidgets import QApplication

    from gbp.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("GBP")
    app.setOrganizationName("Ikalon")

    window = MainWindow()
    window.show()
    # Windows pasa la ruta del caso cuando se abre con «Abrir con → GBP». Se
    # carga después de mostrar la ventana para que un error salga sobre ella.
    if len(sys.argv) > 1:
        window.open_case_path(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
