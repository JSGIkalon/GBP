"""Punto de entrada de la app GBP."""

from __future__ import annotations

import sys
from pathlib import Path

# Permite correr `python run.py` desde el repositorio sin instalar el paquete.
if __package__ is None and not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from gbp.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("GBP")
    app.setOrganizationName("Ikalon")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
