"""Pruebas del reloj independiente."""

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("GBP_DATA_DIR", str(tmp_path))
    from gbp.ui.main_window import MainWindow

    win = MainWindow()
    yield win
    win.close()


def test_clock_window_opens_from_main_window(window):
    window.open_clock()

    assert window._clock_window is not None
    assert window._clock_window.windowTitle() == "Reloj"
    assert window._clock_window.digital_label.text()
    window._clock_window.close()
