"""Activos propios de punta a punta: libreria, caso, interfaz y motor."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gbp.io import library
from gbp.io.caseio import custom_assets_from_dict, from_dict, read_case, save_case, to_dict
from gbp.model.allocation import Allocation
from gbp.model.assets import ORIGIN_CUSTOM, ORIGIN_LTCMA, AssetClass
from gbp.model.groups import FIXED_INCOME
from gbp.model.scenario import Scenario
from gbp.model.strategy import Strategy

COLOMBIA = dict(
    name="Renta Fija Colombiana",
    compound_return=0.058,
    volatility=0.12,
    origin=ORIGIN_CUSTOM,
    asset_class=FIXED_INCOME,
    notes="TES tasa fija, convertido a USD",
)


@pytest.fixture(autouse=True)
def libreria_aislada(tmp_path, monkeypatch):
    monkeypatch.setenv("GBP_DATA_DIR", str(tmp_path))


def _escenario_mixto() -> Scenario:
    return Scenario(
        name="Cliente colombiano",
        initial_value=10_000_000.0,
        horizon=15,
        strategies=[
            Strategy(
                allocation=Allocation(
                    "Mixta",
                    {
                        "U.S. Large Cap": 0.3,
                        "U.S. Aggregate Bonds": 0.3,
                        "Renta Fija Colombiana": 0.4,
                    },
                )
            )
        ],
    )


# --------------------------------------------------------------------------
# Libreria
# --------------------------------------------------------------------------


def test_guardar_y_cargar_conserva_origen_y_clase():
    cmas = library.seed_cmas()
    cmas.add(AssetClass(**COLOMBIA))
    library.save_cmas(cmas)

    recargada = library.load_cmas()
    propio = recargada.by_name("Renta Fija Colombiana")
    assert propio.is_custom
    assert propio.asset_class == FIXED_INCOME
    assert propio.notes == "TES tasa fija, convertido a USD"
    assert not recargada.by_name("U.S. Large Cap").is_custom


def test_una_libreria_de_esquema_2_carga_como_ltcma(tmp_path):
    import json

    library.library_path().parent.mkdir(parents=True, exist_ok=True)
    library.library_path().write_text(
        json.dumps(
            {
                "schema": 2,
                "assets": [
                    {"name": "U.S. Large Cap", "compound_return": 0.07,
                     "volatility": 0.16, "yield_": 0.0}
                ],
            }
        ),
        encoding="utf-8",
    )
    cmas = library.load_cmas()
    assert cmas.by_name("U.S. Large Cap").origin == ORIGIN_LTCMA
    assert not cmas.custom


def test_una_clase_declarada_desconocida_degrada_sin_levantar():
    import json

    library.library_path().parent.mkdir(parents=True, exist_ok=True)
    library.library_path().write_text(
        json.dumps(
            {
                "schema": 3,
                "assets": [
                    {"name": "Raro", "compound_return": 0.05, "volatility": 0.1,
                     "yield_": 0.0, "origin": "custom", "asset_class": "Inventada"}
                ],
            }
        ),
        encoding="utf-8",
    )
    cmas = library.load_cmas()  # no debe levantar
    assert not cmas.by_name("Raro").is_custom


def test_restaurar_el_ltcma_conserva_los_activos_propios():
    cmas = library.seed_cmas()
    cmas.add(AssetClass(**COLOMBIA))
    library.save_cmas(cmas)

    restaurada = library.reset_cmas_to_ltcma()

    assert "Renta Fija Colombiana" in restaurada.names
    assert len(restaurada.custom) == 1
    assert len(restaurada.ltcma) == len(library.seed_cmas())


def test_no_se_puede_borrar_una_clase_del_ltcma():
    cmas = library.seed_cmas()
    with pytest.raises(ValueError, match="no se puede borrar"):
        library.delete_custom_asset(cmas, "U.S. Large Cap")


# --------------------------------------------------------------------------
# Caso
# --------------------------------------------------------------------------


def test_el_caso_lleva_solo_los_activos_propios_que_usa(tmp_path):
    cmas = library.seed_cmas()
    cmas.add(AssetClass(**COLOMBIA))
    cmas.add(AssetClass(**{**COLOMBIA, "name": "Finca raiz Bogota"}))

    payload = to_dict(_escenario_mixto(), cmas)
    nombres = [a["name"] for a in payload["custom_assets"]]
    assert nombres == ["Renta Fija Colombiana"]  # el que no se usa no viaja
    assert all(a["name"] != "U.S. Large Cap" for a in payload["custom_assets"])


def test_ida_y_vuelta_de_un_caso_con_activos_propios(tmp_path):
    cmas = library.seed_cmas()
    cmas.add(AssetClass(**COLOMBIA))
    path = tmp_path / "caso.gbp.json"

    save_case(_escenario_mixto(), path, cmas)
    payload = read_case(path)
    escenario = from_dict(payload)
    propios = custom_assets_from_dict(payload)

    assert escenario.name == "Cliente colombiano"
    assert len(propios) == 1
    assert propios[0].is_custom
    assert propios[0].asset_class == FIXED_INCOME
    assert propios[0].compound_return == pytest.approx(0.058)


def test_un_caso_sin_activos_propios_no_escribe_la_llave(tmp_path):
    cmas = library.seed_cmas()
    escenario = Scenario(
        name="Solo LTCMA", initial_value=1_000_000.0, horizon=10,
        strategies=[Strategy(Allocation("A", {"U.S. Large Cap": 1.0}))],
    )
    assert "custom_assets" not in to_dict(escenario, cmas)


def test_guardar_sin_libreria_sigue_funcionando(tmp_path):
    """Los llamadores viejos de save_case no pasan cmas."""
    path = tmp_path / "viejo.gbp.json"
    save_case(_escenario_mixto(), path)
    assert from_dict(read_case(path)).name == "Cliente colombiano"


# --------------------------------------------------------------------------
# Motor
# --------------------------------------------------------------------------


def test_un_activo_propio_se_puede_simular():
    from gbp.engine.montecarlo import simulate
    from gbp.model.correlation import CorrelationMatrix
    from gbp.model.custom_assets import custom_pairs, extend_correlations
    from gbp.model.scenario import SimulationSettings

    cmas = library.seed_cmas()
    cmas.add(AssetClass(**COLOMBIA))
    base = CorrelationMatrix.load()
    extendida = extend_correlations(base, custom_pairs(cmas))

    resultado = simulate(
        _escenario_mixto(), cmas, extendida, SimulationSettings(n_paths=500, seed=3)
    )
    assert resultado.strategies[0].wealth.shape == (500, 15)
    assert resultado.strategies[0].success_probability > 0


def test_simular_sin_extender_la_matriz_da_un_error_legible():
    from gbp.engine.montecarlo import simulate
    from gbp.model.correlation import CorrelationMatrix
    from gbp.model.scenario import SimulationSettings

    cmas = library.seed_cmas()
    cmas.add(AssetClass(**COLOMBIA))

    with pytest.raises(ValueError, match="no cubre estas clases de activo"):
        simulate(
            _escenario_mixto(), cmas, CorrelationMatrix.load(),
            SimulationSettings(n_paths=200, seed=1),
        )


# --------------------------------------------------------------------------
# Interfaz
# --------------------------------------------------------------------------


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    from gbp.ui.main_window import MainWindow

    win = MainWindow()
    yield win
    win.close()


def test_un_activo_propio_entra_en_available_assets(window):
    window.cmas.add(AssetClass(**COLOMBIA))
    window._on_assets_changed()

    assert "Renta Fija Colombiana" in window.available_assets
    assert "Renta Fija Colombiana" in window.correlations.names
    assert window.resolver.group_of("Renta Fija Colombiana") == FIXED_INCOME


def test_borrar_un_activo_propio_lo_saca_de_available_assets(window):
    window.cmas.add(AssetClass(**COLOMBIA))
    window._on_assets_changed()
    window.cmas.remove("Renta Fija Colombiana")
    window._on_assets_changed()

    assert "Renta Fija Colombiana" not in window.available_assets
    assert "Renta Fija Colombiana" not in window.correlations.names


def test_la_vista_agrupada_usa_la_clase_declarada(window):
    from gbp.model.groups import group_weights

    window.cmas.add(AssetClass(**COLOMBIA))
    window._on_assets_changed()

    agrupado = group_weights(
        {"U.S. Large Cap": 0.6, "Renta Fija Colombiana": 0.4}, window.resolver
    )
    assert agrupado[FIXED_INCOME] == pytest.approx(0.4)


def test_el_shock_de_estres_de_un_activo_propio_no_es_cero(window):
    window.cmas.add(AssetClass(**COLOMBIA))
    window._on_assets_changed()

    escenario = next(s for s in window.stress_scenarios if "financiera" in s.name)
    shock = escenario.shock_for("Renta Fija Colombiana")
    assert shock != 0.0

    miembros = window.resolver.members_of("Renta Fija Colombiana")
    esperado = sum(escenario.shock_for(m) for m in miembros) / len(miembros)
    assert shock == pytest.approx(esperado)


def test_los_botones_de_editar_se_deshabilitan_sobre_una_fila_del_ltcma(window):
    panel = window.assets_panel
    panel.table.setCurrentCell(0, 0)  # la primera es del LTCMA
    assert not panel.selected.is_custom
    assert not panel.edit_button.isEnabled()
    assert not panel.delete_button.isEnabled()

    window.cmas.add(AssetClass(**COLOMBIA))
    panel.reload(window.cmas)
    panel.table.setCurrentCell(len(window.cmas) - 1, 0)
    assert panel.selected.is_custom
    assert panel.edit_button.isEnabled()


def test_abrir_un_caso_con_un_activo_propio_lo_deja_simulable(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    cmas = library.seed_cmas()
    cmas.add(AssetClass(**COLOMBIA))
    path = tmp_path / "otro_pc.gbp.json"
    save_case(_escenario_mixto(), path, cmas)

    # La ventana arranca sin ese activo, como en otro computador.
    assert "Renta Fija Colombiana" not in window.cmas.names

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(
        "gbp.ui.main_window.QFileDialog.getOpenFileName", lambda *a, **k: (str(path), "")
    )
    window.open_case()

    assert "Renta Fija Colombiana" in window.cmas.names
    assert "Renta Fija Colombiana" in window.correlations.names
    # La invariante que importa: el caso quedo simulable.
    window.scenario.validate(window.cmas)
    assert set(window.scenario.asset_names) <= set(window.correlations.names)
