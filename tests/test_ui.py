"""Tests de la interfaz y de la persistencia de casos.

Corren sin ventanas (plataforma offscreen de Qt), asi que sirven en CI y no
interrumpen al usuario.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gbp.io.caseio import (
    SCHEMA_VERSION,
    CaseFormatError,
    from_dict,
    load_case,
    save_case,
    to_dict,
)
from gbp.model.allocation import Allocation
from gbp.model.cashflows import CashFlow, FlowKind
from gbp.model.leverage import Amortization, InterestMode, LoanTerms, RateMode
from gbp.model.scenario import Scenario
from gbp.model.strategy import Strategy


# --------------------------------------------------------------------------
# Guardado y carga de casos
# --------------------------------------------------------------------------


def _loan() -> LoanTerms:
    return LoanTerms(
        name="Linea de credito",
        principal=5_000_000.0,
        start_year=2,
        term_years=8,
        rate_mode=RateMode.SPREAD_OVER_CASH,
        spread=0.018,
        interest_mode=InterestMode.CAPITALIZED,
        amortization=Amortization.FRENCH,
        max_ltv=0.55,
        target_ltv=0.45,
    )


def _rich_scenario() -> Scenario:
    """Caso con dos estrategias realmente distintas entre si."""
    return Scenario(
        name="Caso de prueba",
        initial_value=37_400_000.0,
        horizon=30,
        inflation=0.025,
        strategies=[
            Strategy(
                allocation=Allocation(
                    "Actual", {"U.S. Large Cap": 0.6, "U.S. Aggregate Bonds": 0.4}
                ),
                cashflows=[
                    CashFlow("Gasto", FlowKind.OUTFLOW, 1_100_000.0, 1, 29),
                    CashFlow(
                        "Aporte", FlowKind.INFLOW, 500_000.0, 1, 5, inflation_indexed=False
                    ),
                ],
                loan=_loan(),
            ),
            Strategy(
                allocation=Allocation(
                    "Growth", {"U.S. Large Cap": 0.8, "Private Equity": 0.2}
                ),
                cashflows=[CashFlow("Gasto menor", FlowKind.OUTFLOW, 400_000.0, 1, 30)],
                loan=None,
                initial_value=20_000_000.0,
            ),
        ],
    )


def test_un_caso_sobrevive_la_ida_y_vuelta_completa(tmp_path):
    original = _rich_scenario()
    path = tmp_path / "caso.gbp.json"
    save_case(original, path)
    loaded = load_case(path)

    assert loaded.name == original.name
    assert loaded.initial_value == original.initial_value
    assert loaded.horizon == original.horizon
    assert loaded.inflation == original.inflation

    assert [s.name for s in loaded.strategies] == ["Actual", "Growth"]
    assert loaded.strategies[0].weights == original.strategies[0].weights

    # Cada estrategia conserva sus propios flujos.
    actual, growth = loaded.strategies
    assert len(actual.cashflows) == 2
    assert actual.cashflows[0].kind is FlowKind.OUTFLOW
    assert actual.cashflows[1].inflation_indexed is False
    assert len(growth.cashflows) == 1
    assert growth.cashflows[0].name == "Gasto menor"

    # Y su propio credito.
    assert growth.loan is None
    loan = actual.loan
    assert loan is not None
    assert loan.principal == 5_000_000.0
    assert loan.rate_mode is RateMode.SPREAD_OVER_CASH
    assert loan.interest_mode is InterestMode.CAPITALIZED
    assert loan.amortization is Amortization.FRENCH
    assert loan.max_ltv == pytest.approx(0.55)
    assert loan.target_ltv == pytest.approx(0.45)

    # Y su capital: una hereda, la otra manda el suyo.
    assert actual.initial_value is None
    assert actual.resolved_initial(loaded.initial_value) == 37_400_000.0
    assert growth.initial_value == pytest.approx(20_000_000.0)


def test_un_caso_sin_credito_se_guarda_y_carga(tmp_path):
    scenario = Scenario(
        name="Sin deuda",
        initial_value=1000.0,
        strategies=[Strategy(allocation=Allocation("A", {"U.S. Cash": 1.0}))],
    )
    path = tmp_path / "simple.gbp.json"
    save_case(scenario, path)
    loaded = load_case(path)
    assert loaded.strategies[0].loan is None
    assert loaded.strategies[0].initial_value is None


def test_un_caso_del_esquema_1_se_migra(tmp_path):
    """Los flujos y el credito del escenario aterrizan en cada estrategia."""
    legacy = {
        "schema": 1,
        "scenario": {
            "name": "Caso viejo",
            "initial_value": 25_000_000.0,
            "horizon": 29,
            "inflation": 0.025,
            "allocations": [
                {"name": "Actual", "weights": {"U.S. Large Cap": 1.0}},
                {"name": "Growth", "weights": {"Private Equity": 1.0}},
            ],
            "cashflows": [
                {
                    "name": "Gasto",
                    "kind": FlowKind.OUTFLOW.value,
                    "amount": 1_100_000.0,
                    "start_year": 1,
                    "end_year": 29,
                    "inflation_indexed": True,
                    "growth": 0.0,
                }
            ],
            "loan": {
                "name": "Credito",
                "principal": 3_000_000.0,
                "start_year": 1,
                "term_years": 10,
                "rate_mode": RateMode.FIXED.value,
                "rate": 0.05,
                "spread": 0.015,
                "interest_mode": InterestMode.PAID.value,
                "amortization": Amortization.BULLET.value,
                "max_ltv": None,
                "target_ltv": None,
            },
        },
    }
    scenario = from_dict(legacy)

    assert len(scenario.strategies) == 2
    for strategy in scenario.strategies:
        assert len(strategy.cashflows) == 1
        assert strategy.cashflows[0].amount == 1_100_000.0
        assert strategy.loan is not None
        assert strategy.loan.principal == 3_000_000.0
        assert strategy.initial_value is None

    # Las copias son independientes: tocar una no puede mover la otra.
    scenario.strategies[0].cashflows[0].amount = 1.0
    assert scenario.strategies[1].cashflows[0].amount == 1_100_000.0


def test_el_caso_no_guarda_los_supuestos_de_mercado():
    """Los CMAs viven en la libreria global, no en el archivo del cliente."""
    payload = to_dict(_rich_scenario())
    texto = str(payload)
    assert "compound_return" not in texto
    assert "volatility" not in texto


def test_un_archivo_ajeno_da_un_error_claro(tmp_path):
    path = tmp_path / "otro.json"
    path.write_text('{"algo": 1}', encoding="utf-8")
    with pytest.raises(CaseFormatError):
        load_case(path)


def test_un_json_roto_da_un_error_claro(tmp_path):
    path = tmp_path / "roto.json"
    path.write_text("{no es json", encoding="utf-8")
    with pytest.raises(CaseFormatError):
        load_case(path)


def test_un_esquema_futuro_se_rechaza_con_mensaje():
    with pytest.raises(CaseFormatError, match="más nueva|mas nueva"):
        from_dict({"schema": SCHEMA_VERSION + 1, "scenario": {"name": "x"}})


# --------------------------------------------------------------------------
# Interfaz
# --------------------------------------------------------------------------


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


def test_la_ventana_abre_con_el_caso_de_ejemplo(window):
    assert window.scenario.strategies
    assert window.cmas.names
    assert len(window.correlations.names) > 50
    # Todas las clases del ejemplo deben existir en la libreria y en la matriz.
    for strategy in window.scenario.strategies:
        for name in strategy.asset_names:
            assert name in window.available_assets, name


def test_el_caso_de_ejemplo_pasa_la_validacion(window):
    window.scenario.validate(window.cmas)


def test_la_simulacion_completa_produce_resultados(window):
    """Corre el motor por el mismo camino que el boton, pero sin hilo."""
    from gbp.engine.montecarlo import simulate
    from gbp.model.scenario import SimulationSettings

    settings = SimulationSettings(n_paths=1_000, seed=1)
    result = simulate(window.scenario, window.cmas, window.correlations, settings)
    window.results.show_result(result, settings, window.scenario.horizon)

    assert len(result.strategies) == 3
    assert window.results.range_table.rowCount() > 0
    assert window.results.summary_table.rowCount() > 0
    assert "%" in window.results.headline.text()


def test_el_stress_test_se_muestra_sin_simular(window):
    window.results.show_stress(window.scenario, window.stress_scenarios)
    assert window.results.stress_table.rowCount() == 3 * len(window.stress_scenarios)


def test_caso_nuevo_conserva_la_libreria_de_supuestos(window):
    antes = len(window.cmas)
    window.new_case()
    assert len(window.cmas) == antes
    assert window.scenario.initial_value == 0.0


def test_editar_un_supuesto_lo_persiste(window, tmp_path):
    from gbp.io import library

    window.cmas.by_name("U.S. Large Cap").yield_ = 0.017
    window.assets_panel._persist()
    assert library.load_cmas().by_name("U.S. Large Cap").yield_ == pytest.approx(0.017)


def test_cambiar_la_configuracion_la_persiste(window):
    from gbp.io import library

    window.settings_panel.n_paths.setValue(5_000)
    assert library.load_settings().n_paths == 5_000


def test_una_estrategia_mal_sumada_no_corre(window):
    window.scenario.strategies[0].allocation.weights = {"U.S. Large Cap": 0.5}
    with pytest.raises(ValueError, match="sumar 100%"):
        window.scenario.validate(window.cmas)


def test_los_paneles_reflejan_un_caso_cargado(window, tmp_path):
    path = tmp_path / "otro.gbp.json"
    save_case(_rich_scenario(), path)
    window.scenario = load_case(path)
    window._reload_all()

    panel = window.strategies_panel
    assert window.scenario_panel.name_edit.text() == "Caso de prueba"
    assert window.scenario_panel.horizon.value() == 30
    assert panel.selector.count() == 2

    # La primera estrategia: dos flujos, credito activo, capital heredado.
    panel.selector.setCurrentIndex(0)
    assert panel.cashflow_panel.table.rowCount() == 2
    assert panel.leverage_panel.enabled.isChecked()
    assert panel.leverage_panel.principal.value() == pytest.approx(5_000_000.0)
    assert not panel.capital_panel.use_own.isChecked()

    # La segunda: un flujo, sin credito, con capital propio.
    panel.selector.setCurrentIndex(1)
    assert panel.cashflow_panel.table.rowCount() == 1
    assert not panel.leverage_panel.enabled.isChecked()
    assert panel.capital_panel.use_own.isChecked()
    assert panel.capital_panel.amount.value() == pytest.approx(20_000_000.0)


def test_editar_una_estrategia_no_toca_las_demas(window):
    """Los flujos son por estrategia: agregar uno no debe propagarse."""
    from gbp.model.cashflows import FlowKind as Kind

    panel = window.strategies_panel
    panel.selector.setCurrentIndex(0)
    antes = [len(s.cashflows) for s in window.scenario.strategies]

    panel.cashflow_panel._add(Kind.INFLOW)

    despues = [len(s.cashflows) for s in window.scenario.strategies]
    assert despues[0] == antes[0] + 1
    assert despues[1:] == antes[1:]


def test_duplicar_desde_el_panel_crea_una_copia_independiente(window):
    panel = window.strategies_panel
    panel.selector.setCurrentIndex(0)
    original = panel.current

    copia = original.copy("Duplicada")
    window.scenario.strategies.append(copia)
    copia.allocation.weights[next(iter(copia.weights))] = 0.123

    primera_clase = next(iter(original.weights))
    assert original.weights[primera_clase] != pytest.approx(0.123)


def test_los_graficos_dibujan_sin_error(window):
    from gbp.engine.montecarlo import simulate
    from gbp.model.scenario import SimulationSettings

    settings = SimulationSettings(n_paths=500, seed=3)
    result = simulate(window.scenario, window.cmas, window.correlations, settings)
    window.results.show_result(result, settings, window.scenario.horizon)

    for canvas in (
        window.results.box_canvas,
        window.results.stress_canvas,
        window.results.debt_canvas,
    ):
        assert canvas.figure.get_axes(), "El lienzo quedo sin ejes"


def test_la_vista_real_cambia_los_numeros(window):
    from gbp.engine.montecarlo import simulate
    from gbp.model.scenario import SimulationSettings

    settings = SimulationSettings(n_paths=500, seed=3)
    result = simulate(window.scenario, window.cmas, window.correlations, settings)
    nominal = result.strategies[0].percentiles([10], real=False)[50][0]
    real = result.strategies[0].percentiles([10], real=True)[50][0]
    assert real < nominal


# --------------------------------------------------------------------------
# Edicion de estrategias: el bug del re-render
# --------------------------------------------------------------------------


def _nueva_estrategia(window, nombre: str = "Nueva"):
    """Agrega una estrategia y la selecciona, como hace el boton «Nueva»."""
    window.scenario.strategies.append(Strategy(allocation=Allocation(nombre, {})))
    panel = window.strategies_panel
    panel._refresh_list()
    panel.selector.setCurrentIndex(len(window.scenario.strategies) - 1)
    panel._render_current()
    return panel


def test_se_puede_activar_el_credito_de_una_estrategia_no_primera(window):
    """El caso que estaba roto: la casilla se desmarcaba sola al pulsarla.

    Editar el credito emitia `changed`, el panel reconstruia el selector, eso
    reemitia la seleccion y el editor se recargaba en mitad de la edicion. Solo
    se notaba fuera del indice 0, porque restaurar el indice 0 no emite señal.
    """
    panel = _nueva_estrategia(window)
    assert panel.selector.currentIndex() > 0

    panel.leverage_panel.enabled.setChecked(True)
    assert panel.leverage_panel.enabled.isChecked()

    panel.leverage_panel.principal.setValue(5_000_000)
    assert panel.leverage_panel.principal.value() == pytest.approx(5_000_000)
    assert panel.current.loan.principal == pytest.approx(5_000_000)
    assert panel.current.has_loan


def test_desmarcar_el_credito_lo_quita(window):
    panel = _nueva_estrategia(window)
    panel.leverage_panel.enabled.setChecked(True)
    panel.leverage_panel.principal.setValue(1_000_000)
    panel.leverage_panel.enabled.setChecked(False)
    assert panel.current.loan is None


def test_se_pueden_agregar_flujos_a_una_estrategia_no_primera(window):
    panel = _nueva_estrategia(window)
    panel.cashflow_panel._add(FlowKind.OUTFLOW)
    panel.cashflow_panel._add(FlowKind.INFLOW)

    assert len(panel.current.cashflows) == 2
    assert panel.cashflow_panel.table.rowCount() == 2

    panel.cashflow_panel.table.item(0, 2).setText("1200000")
    assert panel.current.cashflows[0].amount == pytest.approx(1_200_000)
    # La edicion no debe reconstruir la tabla ni cambiar de estrategia.
    assert panel.cashflow_panel.table.rowCount() == 2
    assert panel.selector.currentIndex() == len(window.scenario.strategies) - 1


def test_los_supuestos_de_mercado_son_de_solo_lectura(window):
    from PySide6.QtWidgets import QAbstractItemView

    assert (
        window.assets_panel.table.editTriggers()
        == QAbstractItemView.EditTrigger.NoEditTriggers
    )
    assert (
        window.correlation_panel.table.editTriggers()
        == QAbstractItemView.EditTrigger.NoEditTriggers
    )


def test_el_boton_de_exportar_arranca_deshabilitado_y_se_habilita_al_simular(window):
    from gbp.engine.montecarlo import simulate
    from gbp.model.scenario import SimulationSettings

    assert not window.export_action.isEnabled()
    assert not window.export_button.isEnabled()

    settings = SimulationSettings(n_paths=300, seed=7)
    result = simulate(window.scenario, window.cmas, window.correlations, settings)
    window._on_finished(result)

    assert window.export_action.isEnabled()
    assert window.export_button.isEnabled()

    window.new_case()
    assert not window.export_action.isEnabled()
