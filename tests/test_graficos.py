"""Tipos de gráfico de la distribución, probabilidad de éxito por año y copiado.

Lo visual se revisa mirando capturas; aquí se protege que cada tipo dibuje en
pantalla y en el informe, que las cifras que muestran salgan de la misma caché
que la tabla, y que las preferencias de lectura se recuerden.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from matplotlib.figure import Figure

from gbp.engine.montecarlo import simulate
from gbp.io import library
from gbp.io.report import CHART_RECT, ReportOptions, _FigureCanvas, build_report
from gbp.model.allocation import Allocation
from gbp.model.cashflows import CashFlow, FlowKind
from gbp.model.leverage import LoanTerms
from gbp.model.scenario import PesoAssumptions, Scenario, SimulationSettings
from gbp.model.strategy import Strategy
from gbp.ui.charts.distribution import BOXES, CHART_KINDS, FAN, MEDIANS, draw_distribution
from gbp.ui.charts.fan_chart import _series


def _escenario(n: int) -> Scenario:
    mezclas = [(0.6, 0.4), (0.7, 0.3), (0.4, 0.6), (0.2, 0.8)]
    estrategias = []
    for i, (acciones, bonos) in enumerate(mezclas[:n]):
        estrategias.append(Strategy(
            allocation=Allocation(f"Plan {i + 1}", {"Acciones": acciones, "Bonos": bonos}),
            cashflows=[CashFlow("Gasto", FlowKind.OUTFLOW, 1_400_000.0, 1, 20)],
            loan=LoanTerms(principal=4_000_000.0, term_years=10, max_ltv=0.6)
            if i == 1 else None,
        ))
    return Scenario(name="Gráficos", initial_value=20_000_000.0, horizon=20,
                    inflation=0.025, strategies=estrategias)


@pytest.fixture(scope="module")
def corridas(simple_cmas, simple_corr):
    settings = SimulationSettings(n_paths=400, seed=11, milestone_years=[5, 10, 20])
    return {
        n: (_escenario(n), simulate(_escenario(n), simple_cmas, simple_corr, settings))
        for n in (1, 4)
    }, settings


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("kind", list(CHART_KINDS))
@pytest.mark.parametrize("n", [1, 4])
@pytest.mark.parametrize("real", [False, True])
def test_cada_tipo_dibuja_en_pantalla_y_en_papel(qapp, corridas, kind, n, real):
    from gbp.ui.charts.canvas import ChartCanvas

    casos, settings = corridas
    _, result = casos[n]
    years = settings.milestone_years
    en_cop = result.in_currency(PesoAssumptions(spot=4_000.0, devaluation=0.03), 0.025)

    for vista in (result, en_cop):
        pantalla = ChartCanvas()
        draw_distribution(pantalla, vista, years, real, kind=kind)
        ejes = pantalla.figure.axes
        # El abanico es un panel por estrategia; los otros dos, un solo eje.
        assert len(ejes) == (n if kind == FAN else 1)
        # El tooltip responde sobre un año del gráfico.
        x = 1.0 if kind == BOXES else 10.0
        y = float(_series(vista.strategies[0], real)[50][10])
        if kind != BOXES:
            assert "Año 10" in pantalla._hover_probe(x, y, ejes[0])

        papel = Figure(figsize=(11.69, 8.27))
        draw_distribution(_FigureCanvas(papel, rect=CHART_RECT), vista, years, real, kind=kind)
        assert len(papel.axes) == len(ejes)
        # En el papel ningún eje se sale del rectángulo reservado al gráfico.
        x0, y0, ancho, alto = CHART_RECT
        for ax in papel.axes:
            caja = ax.get_position()
            assert caja.x0 >= x0 - 1e-9 and caja.x1 <= x0 + ancho + 1e-9
            assert caja.y0 >= y0 - 1e-9 and caja.y1 <= y0 + alto + 1e-9


def test_un_tipo_desconocido_cae_a_las_cajas(qapp, corridas):
    from gbp.ui.charts.canvas import ChartCanvas

    casos, settings = corridas
    lienzo = ChartCanvas()
    draw_distribution(lienzo, casos[1][1], settings.milestone_years, kind="de otra versión")
    assert len(lienzo.figure.axes) == 1


def test_el_abanico_usa_las_mismas_cifras_que_la_tabla(corridas):
    casos, settings = corridas
    _, result = casos[4]
    for strategy in result.strategies:
        for real in (False, True):
            serie = _series(strategy, real)
            # Año 0: el capital inicial, igual en todos los percentiles.
            assert all(serie[p][0] == strategy.initial_value for p in serie)
            hitos = strategy.percentiles(settings.milestone_years, real)
            for p in (10, 25, 50, 75, 90):
                assert [serie[p][y] for y in settings.milestone_years] == pytest.approx(
                    list(hitos[p])
                )


def test_la_probabilidad_de_exito_por_anio_termina_en_la_del_plan(corridas):
    casos, _ = corridas
    for _, result in casos.values():
        for strategy in result.strategies:
            serie = strategy.success_by_year()
            assert len(serie) == strategy.horizon
            assert serie[-1] == pytest.approx(strategy.success_probability)
            # Un camino agotado no vuelve: la serie nunca sube.
            assert (np.diff(serie) <= 0).all()
            # Y coincide con la definición directa, año por año.
            for year in (1, 7, strategy.horizon):
                directo = (strategy.wealth[:, :year] > 0).all(axis=1).mean()
                assert serie[year - 1] == pytest.approx(directo)
    # El caso gasta lo suficiente para que el test no sea trivial.
    assert any(s.success_probability < 1.0 for s in casos[4][1].strategies)


def test_las_bandas_de_deuda_en_cache_son_los_percentiles(corridas):
    casos, _ = corridas
    con_deuda = casos[4][1].strategies[1]
    assert con_deuda.has_debt
    low, median, high = con_deuda.debt_bands()
    esperado = np.percentile(con_deuda.debt, [5, 50, 95], axis=0)
    assert np.array_equal(np.array([low, median, high]), esperado)
    assert con_deuda.debt_bands()[0] is low


def test_el_tipo_de_grafico_y_las_etiquetas_se_recuerdan(tmp_path, monkeypatch):
    monkeypatch.setenv("GBP_DATA_DIR", str(tmp_path))
    assert library.load_settings().chart_kind == BOXES

    library.save_settings(SimulationSettings(chart_kind=FAN, show_percentile_labels=False))
    leido = library.load_settings()
    assert leido.chart_kind == FAN
    assert leido.show_percentile_labels is False


def test_el_panel_escribe_las_preferencias_en_los_ajustes(qapp, corridas):
    from gbp.ui.panels.results_panel import ResultsPanel

    casos, _ = corridas
    settings = SimulationSettings(n_paths=400, milestone_years=[5, 10, 20], chart_kind=MEDIANS)
    panel = ResultsPanel(settings=settings)
    assert panel.chart_kind == MEDIANS
    assert all(s.currentData() == MEDIANS for s in panel._kind_selectors)
    assert all(t.isHidden() for t in panel._percentile_toggles)

    panel.show_result(casos[4][1], settings, 20)
    # Elegir en una pestaña cambia las dos y queda en los ajustes.
    selector = panel._kind_selectors[1]
    selector.setCurrentIndex(selector.findData(FAN))
    assert panel.chart_kind == FAN and settings.chart_kind == FAN
    assert panel._kind_selectors[0].currentData() == FAN
    assert len(panel.box_canvas.figure.axes) == 4
    assert len(panel.real_canvas.figure.axes) == 4

    panel.set_chart_kind(BOXES)
    assert not any(t.isHidden() for t in panel._percentile_toggles)
    panel._percentile_toggles[0].setChecked(False)
    assert settings.show_percentile_labels is False

    # La tabla de flujos trae la probabilidad de éxito de cada año.
    ultima = panel.flows_table.rowCount() - 1
    columna = panel.flow_columns.index("Prob. de éxito hasta el año")
    plan = panel.result.strategies[0]
    assert panel.flows_table.item(ultima, columna).text() == f"{plan.success_probability:.1%}"


def test_copiar_tabla_deja_texto_tabulado_con_encabezados(qapp, corridas):
    from PySide6.QtWidgets import QApplication

    from gbp.ui.panels.results_panel import ResultsPanel
    from gbp.ui.table_copy import table_text

    casos, settings = corridas
    panel = ResultsPanel(settings=settings)
    panel.show_result(casos[1][1], settings, 20)

    lineas = table_text(panel.range_table).split("\n")
    assert lineas[0].split("\t") == panel.range_columns
    assert len(lineas) == 1 + len(settings.milestone_years)
    assert lineas[1].split("\t")[:2] == ["Plan 1", "5"]

    panel.range_table.selectRow(1)
    seleccion = table_text(panel.range_table, only_selected=True).split("\n")
    assert len(seleccion) == 2 and seleccion[1].split("\t")[1] == "10"

    # La acción «Copiar tabla» del menú contextual llega al portapapeles.
    accion = next(a for a in panel.range_table.actions() if a.text() == "Copiar tabla")
    accion.trigger()
    assert QApplication.clipboard().text() == table_text(panel.range_table)


def test_el_grafico_se_exporta_como_png(qapp, corridas):
    from gbp.ui.charts.canvas import ChartCanvas

    casos, settings = corridas
    lienzo = ChartCanvas()
    draw_distribution(lienzo, casos[4][1], settings.milestone_years, kind=FAN)
    assert lienzo._png_bytes().startswith(b"\x89PNG")


@pytest.mark.parametrize("kind", [FAN, MEDIANS])
def test_el_informe_sale_con_el_tipo_de_grafico_elegido(tmp_path, corridas, kind):
    casos, settings = corridas
    escenario, result = casos[4]
    path = tmp_path / f"{kind}.pdf"
    build_report(
        path,
        ReportOptions(chart_kind=kind, include_allocation=False, include_inputs=False),
        escenario, result, settings,
    )
    assert path.read_bytes().startswith(b"%PDF")
