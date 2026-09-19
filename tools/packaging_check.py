"""Verifica que el empaquetado a .exe funcione, antes de que exista la interfaz.

Congelar la app tiene dos riesgos que no se ven corriendo desde el codigo fuente:

1. Que los recursos embebidos (`gbp/data/*.json`, el LTCMA) no viajen dentro del
   ejecutable. `gbp.model.correlation.data_dir()` los resuelve via `sys._MEIPASS`,
   y eso solo se puede probar congelando.
2. Que la libreria de CMAs se escriba dentro del ejecutable en vez de en
   `%APPDATA%`, donde se perderia con cada nueva version.

Este script corre dentro del .exe y falla ruidosamente si algo de eso no se
cumple. Se usa asi:

    pyinstaller --onefile --name gbp_packaging_check ^
        --add-data "gbp/data;gbp/data" tools/packaging_check.py
    dist\\gbp_packaging_check.exe
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def main() -> int:
    # El chequeo escribe en la libreria, asi que se aisla en una carpeta temporal
    # para no tocar los supuestos que el usuario tenga cargados a mano.
    sandbox = tempfile.mkdtemp(prefix="gbp_packaging_check_")
    os.environ["GBP_DATA_DIR"] = sandbox
    print(f"Libreria aislada en : {sandbox}")

    frozen = getattr(sys, "frozen", False)
    print(f"Ejecutable congelado: {frozen}")
    print(f"Ruta del ejecutable : {Path(sys.executable).resolve()}")

    from gbp.io.library import app_data_dir, load_cmas, library_path, save_cmas
    from gbp.model.correlation import CorrelationMatrix, data_dir, is_psd

    print(f"\nRecursos embebidos  : {data_dir()}")
    matrix = CorrelationMatrix.load()
    print(f"  clases de activo  : {len(matrix.names)}")
    print(f"  PSD tras reparar  : {is_psd(matrix.matrix)}")
    assert len(matrix.names) > 50, "La matriz embebida no viajo dentro del ejecutable."

    # Los recursos de marca tambien deben viajar dentro del ejecutable.
    from gbp.ui.brand import brand_dir

    print(f"\nRecursos de marca   : {brand_dir()}")
    for name in ("simbolo.png", "wordmark.png", "gbp.ico"):
        asset = brand_dir() / name
        assert asset.exists(), f"Falta el recurso de marca {name} dentro del .exe."
        print(f"  {name:<14} {asset.stat().st_size / 1024:6.1f} KB")

    cmas = load_cmas()
    print(f"\nLibreria de CMAs    : {library_path()}")
    print(f"  clases cargadas   : {len(cmas)}")
    assert len(cmas) > 50, "La libreria no se sembro desde el LTCMA embebido."

    # La escritura debe ir a %APPDATA%, nunca junto al ejecutable.
    cmas.by_name("U.S. Large Cap").yield_ = 0.017
    save_cmas(cmas)
    assert library_path().exists(), "No se pudo escribir la libreria."
    assert load_cmas().by_name("U.S. Large Cap").yield_ == 0.017, "La edicion no persistio."

    # La ruta por defecto (sin el aislamiento de este chequeo) debe caer en
    # %APPDATA% y nunca junto al ejecutable, donde se perderia al actualizar.
    del os.environ["GBP_DATA_DIR"]
    exe_dir = Path(sys.executable).resolve().parent
    default_dir = app_data_dir().resolve()
    print(f"Ruta por defecto    : {default_dir}")
    assert exe_dir not in default_dir.parents and default_dir != exe_dir, (
        f"La libreria se guardaria junto al ejecutable ({default_dir}); "
        "deberia ir a %APPDATA%."
    )
    os.environ["GBP_DATA_DIR"] = sandbox

    # Y el motor debe correr igual que desde el codigo fuente.
    from gbp.engine.montecarlo import simulate
    from gbp.model.allocation import Allocation
    from gbp.model.scenario import Scenario, SimulationSettings
    from gbp.model.strategy import Strategy

    scenario = Scenario(
        name="Humo",
        initial_value=1_000_000.0,
        horizon=10,
        strategies=[
            Strategy(
                allocation=Allocation(
                    "60/40", {"U.S. Large Cap": 0.6, "U.S. Aggregate Bonds": 0.4}
                )
            )
        ],
    )
    result = simulate(scenario, cmas, matrix, SimulationSettings(n_paths=10_000, seed=42))
    mediana = result.strategies[0].percentiles([10])[50][0]
    print(f"\n10.000 simulaciones corridas. Mediana a 10 anos: {mediana:,.0f}")

    # La interfaz completa: se construye, corre el caso de ejemplo y dibuja.
    # Esto es lo que el .exe --windowed hace al abrirse, pero con salida legible.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from gbp.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    print(f"\nInterfaz construida. Caso de ejemplo: {window.scenario.name}")
    print(f"  estrategias       : {len(window.scenario.strategies)}")
    print(f"  clases utilizables: {len(window.available_assets)}")

    ui_result = simulate(
        window.scenario, window.cmas, window.correlations, window.settings
    )
    window.results.show_result(ui_result, window.settings, window.scenario.horizon)
    app.processEvents()

    assert window.results.range_table.rowCount() > 0, "La tabla de proyeccion quedo vacia."
    for name, canvas in (
        ("distribucion", window.results.box_canvas),
        ("stress", window.results.stress_canvas),
        ("deuda", window.results.debt_canvas),
    ):
        assert canvas.figure.get_axes(), f"El grafico de {name} no se dibujo."
    best = max(ui_result.strategies, key=lambda s: s.success_probability)
    print(f"  mejor prob. exito : {best.success_probability:.1%} ({best.name})")

    # El informe PDF usa el backend `backend_pdf` de matplotlib, que no se
    # importa en ningun otro camino de la app: si PyInstaller no lo recogiera,
    # exportar fallaria solo en el .exe y solo al pulsar el boton. Se prueba
    # aqui, que es el unico sitio donde se corre congelado.
    from gbp.io.report import ReportOptions, build_report
    from gbp.ui.export_dialog import ExportDialog

    pdf_path = Path(sandbox) / "informe_de_humo.pdf"
    build_report(
        pdf_path,
        ReportOptions(title="Chequeo de empaquetado", client="Humo", author="CI"),
        window.scenario, ui_result, window.settings, window.stress_scenarios,
    )
    assert pdf_path.exists() and pdf_path.read_bytes().startswith(b"%PDF"), (
        "El informe PDF no se genero dentro del ejecutable."
    )
    print(f"\nInforme PDF         : {pdf_path.stat().st_size / 1024:.0f} KB")

    dialog = ExportDialog(window.scenario.name, has_debt=False)
    assert dialog.options().title, "La ventana de exportacion no se pudo construir."
    dialog.close()

    # Activos propios: la matriz extendida se construye en runtime, asi que
    # conviene verificar congelado que numpy y el resto responden igual.
    from gbp.model.assets import ORIGIN_CUSTOM, AssetClass
    from gbp.model.groups import FIXED_INCOME

    window.cmas.add(
        AssetClass("Renta Fija Colombiana", 0.058, 0.12,
                   origin=ORIGIN_CUSTOM, asset_class=FIXED_INCOME)
    )
    window._on_assets_changed()
    assert "Renta Fija Colombiana" in window.available_assets, (
        "El activo propio no entro en la matriz extendida."
    )
    propio = Allocation("Mixta", {"U.S. Large Cap": 0.6, "Renta Fija Colombiana": 0.4})
    mixto = Scenario(
        name="Mixto", initial_value=1_000_000.0, horizon=10,
        strategies=[Strategy(allocation=propio)],
    )
    mezcla = simulate(mixto, window.cmas, window.correlations,
                      SimulationSettings(n_paths=2_000, seed=7))
    print(f"\nActivo propio        : simula, {len(window.correlations.names)} clases")
    print(f"  prob. exito        : {mezcla.strategies[0].success_probability:.1%}")

    window.close()

    print("\nOK: recursos embebidos, persistencia en APPDATA, motor, interfaz e informe PDF.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
