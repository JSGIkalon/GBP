"""Tests del informe PDF.

El informe no se compara pagina por pagina: se verifica que se escriba un PDF
valido, que respete las secciones elegidas y que los datos de portada lleguen a
los metadatos. Lo visual se revisa mirando el archivo, no con aserciones.
"""

from __future__ import annotations

import os
from datetime import date

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gbp.engine.montecarlo import simulate
from gbp.io.report import (
    ALLOCATION,
    DEBT,
    DISTRIBUTION,
    DISTRIBUTION_REAL,
    FLOWS,
    SUMMARY,
    ReportOptions,
    _build_annex,
    _cite,
    _flows_table,
    build_report,
)
from gbp.model.allocation import Allocation
from gbp.model.cashflows import CashFlow, FlowKind
from gbp.model.leverage import LoanTerms
from gbp.model.scenario import Scenario, SimulationSettings
from gbp.model.strategy import Strategy


def _escenario() -> Scenario:
    return Scenario(
        name="Caso de informe",
        initial_value=20_000_000.0,
        horizon=20,
        inflation=0.025,
        strategies=[
            Strategy(
                allocation=Allocation("Sin deuda", {"Acciones": 0.6, "Bonos": 0.4}),
                cashflows=[CashFlow("Gasto", FlowKind.OUTFLOW, 800_000.0, 1, 20)],
            ),
            Strategy(
                allocation=Allocation("Con deuda", {"Acciones": 0.7, "Bonos": 0.3}),
                loan=LoanTerms(principal=4_000_000.0, term_years=10, max_ltv=0.6),
            ),
        ],
    )


@pytest.fixture
def escenario() -> Scenario:
    """Copia propia para los tests que cambian estrategias o créditos."""
    return _escenario()


@pytest.fixture(scope="module")
def corrida(simple_cmas, simple_corr):
    """Una sola simulación para todo el módulo: es la parte cara.

    Es de solo lectura. El test que necesite otro escenario usa `escenario`,
    que es de función, y simula aparte.
    """
    escenario = _escenario()
    settings = SimulationSettings(n_paths=400, seed=11, milestone_years=[5, 10, 20])
    result = simulate(escenario, simple_cmas, simple_corr, settings)
    return escenario, result, settings


def _paginas(path) -> int:
    """Cuenta paginas leyendo el propio PDF, sin depender de otra libreria.

    El objeto raiz de paginas del PDF declara `/Count N`. matplotlib no comprime
    ese diccionario, asi que se puede leer del archivo tal cual.
    """
    import re

    encontrado = re.findall(rb"/Count\s*(\d+)", path.read_bytes())
    assert encontrado, "El PDF no declara su numero de paginas"
    return int(encontrado[0])


def test_el_informe_se_escribe_y_la_portada_llega_a_los_metadatos(corrida, tmp_path):
    escenario, result, settings = corrida
    path = build_report(
        tmp_path / "informe.pdf",
        ReportOptions(title="Revision anual", client="Familia X", author="Ikalon",
                      report_date=date(2026, 3, 15)),
        escenario, result, settings,
    )
    assert path.exists()
    raw = path.read_bytes()
    assert raw.startswith(b"%PDF")
    assert path.stat().st_size > 10_000
    assert b"Revision anual" in raw
    assert b"Ikalon" in raw


def test_las_secciones_desmarcadas_no_salen(corrida, tmp_path):
    escenario, result, settings = corrida
    completo = build_report(
        tmp_path / "completo.pdf", ReportOptions(),
        escenario, result, settings,
    )
    minimo = build_report(
        tmp_path / "minimo.pdf",
        ReportOptions(include_distribution=False, include_summary=False,
                      include_allocation=False, include_debt=False,
                      include_inputs=False, include_flows=False),
        escenario, result, settings,
    )
    assert _paginas(minimo) == 1  # solo la portada
    assert _paginas(completo) > _paginas(minimo)


def test_un_caso_sin_deuda_omite_la_seccion_de_deuda(
    corrida, escenario, simple_cmas, simple_corr, tmp_path
):
    con_deuda_escenario, con_deuda_result, settings = corrida
    con_deuda = build_report(
        tmp_path / "con_deuda.pdf", ReportOptions(),
        con_deuda_escenario, con_deuda_result, settings,
    )

    for strategy in escenario.strategies:
        strategy.loan = None
    sin_deuda_result = simulate(escenario, simple_cmas, simple_corr, settings)
    sin_deuda = build_report(
        tmp_path / "sin_deuda.pdf", ReportOptions(),
        escenario, sin_deuda_result, settings,
    )
    assert _paginas(sin_deuda) < _paginas(con_deuda)


def test_el_anexo_trae_una_hoja_por_estrategia_con_todas_sus_tablas(corrida):
    """Una entrada por estrategia, y dentro todas sus tablas.

    No se verifica sobre el PDF: matplotlib escribe el texto de pagina como
    subconjuntos de glifos, asi que buscar la palabra "Anexo" en los bytes no
    la encuentra aunque este impresa. El contrato que importa vive en
    `_build_annex`, que es lo que citan las graficas.
    """
    escenario, result, settings = corrida
    years = settings.milestones_within(escenario.horizon)
    nombres = [s.name for s in escenario.strategies]

    annex = _build_annex(ReportOptions(), escenario, result, years, True)

    assert [a.name for a in annex] == nombres
    assert [a.number for a in annex] == list(range(1, len(annex) + 1))
    for anexo in annex:
        # Distribucion nominal, distribucion real y deuda, todas en la misma
        # hoja. Los supuestos resumen y la asignacion NO estan: van en el
        # cuerpo, cada una junto a la grafica que explican.
        assert [b.kind for b in anexo.blocks] == [
            DISTRIBUTION, DISTRIBUTION_REAL, DEBT
        ]
        assert all(b.rows for b in anexo.blocks), "Una tabla salio vacia"
        assert anexo.block(SUMMARY) is None
        assert anexo.block(ALLOCATION) is None

        # Nominal y moneda de hoy son dos tablas, no una elegida por settings.
        # Con inflacion positiva la serie real es estrictamente menor, asi que
        # las dos tablas no pueden traer las mismas cifras.
        nominal = anexo.block(DISTRIBUTION)
        real = anexo.block(DISTRIBUTION_REAL)
        assert nominal.columns == real.columns
        assert nominal.rows != real.rows


def test_cada_grafica_cita_las_hojas_de_su_tema_y_solo_si_existen(corrida):
    """El anexo va por estrategia, asi que la cita es el rango de hojas.

    Y una seccion excluida no deja su tabla: un anexo con el detalle de una
    grafica ausente no lo entenderia nadie, ni una cita a hojas inexistentes.
    """
    escenario, result, settings = corrida
    years = settings.milestones_within(escenario.horizon)

    annex = _build_annex(ReportOptions(), escenario, result, years, True)
    assert _cite(annex, DISTRIBUTION, "Nota.") == (
        f"Nota. Detalle en el Anexo · Hojas {annex[0].number} a {annex[-1].number}."
    )

    vacio = _build_annex(
        ReportOptions(include_distribution=False, include_summary=False),
        escenario, result, years, False,
    )
    assert vacio == []
    assert _cite(vacio, DISTRIBUTION, "Nota.") == "Nota."


def test_el_anexo_gasta_una_hoja_por_estrategia(
    corrida, escenario, simple_cmas, simple_corr, tmp_path
):
    """Toda la informacion de una estrategia tiene que caber en una hoja.

    Con seis estrategias son seis hojas, no doce: una por estrategia, no por
    tema, con las dos unidades lado a lado dentro de cada hoja.
    """
    dos, result, settings = corrida
    path = build_report(
        tmp_path / "agrupado.pdf",
        ReportOptions(include_debt=False, include_inputs=False,
                      include_flows=False),
        dos, result, settings,
    )
    # Portada, grafica de asignacion, supuestos resumen (cuerpo), las dos
    # laminas de distribucion y UNA hoja de anexo por cada estrategia.
    assert _paginas(path) == 1 + 1 + 1 + 2 + len(dos.strategies)

    base = escenario.strategies[0]
    base.loan = None
    escenario.strategies = [base.copy(f"Estrategia {i}") for i in range(6)]
    settings = SimulationSettings(n_paths=200, seed=3, milestone_years=[5, 10, 20])
    seis = simulate(escenario, simple_cmas, simple_corr, settings)
    path = build_report(
        tmp_path / "seis.pdf",
        ReportOptions(include_allocation=False, include_summary=False,
                      include_debt=False, include_inputs=False,
                      include_flows=False),
        escenario, seis, settings,
    )
    # Portada + dos graficas + una hoja de anexo por estrategia.
    assert _paginas(path) == 1 + 2 + 6


def test_el_retiro_indexado_crece_con_la_inflacion_en_el_anexo(corrida):
    """El retiro de 800k vale 800k el año 1 y 800k·1.025^(y-1) en el año y.

    El anexo de flujos trae esa serie año por año: es la unica forma de que el
    lector compruebe que un flujo indexado crece como se esperaba.
    """
    escenario, result, _ = corrida
    serie = result.by_name("Sin deuda").flow_history()

    for year in (1, 10, 20):
        esperado = 800_000.0 * 1.025 ** (year - 1)
        assert serie["retiros"][year - 1] == pytest.approx(esperado)
    assert not serie["aportes"].any()

    tabla = _flows_table(result)
    assert tabla is not None
    assert tabla.kind == FLOWS
    # Solo la estrategia con flujos: la otra no tiene serie que mostrar.
    assert tabla.strategies == ["Sin deuda"]
    filas = tabla.per_strategy[0][1]
    assert len(filas) == escenario.horizon
    assert [f[0] for f in filas] == [str(y) for y in range(1, escenario.horizon + 1)]


def test_las_cifras_del_grafico_coinciden_con_la_tabla(corrida):
    """La caché del box plot no puede alterar los percentiles."""
    import numpy as np

    from gbp.ui.charts.box_chart import _box_stats

    _, result, settings = corrida
    years = settings.milestone_years
    for strategy in result.strategies:
        for real in (False, True):
            stats = _box_stats(strategy, years, real)
            pct = strategy.percentiles(years, real)
            assert [s["med"] for s in stats] == pytest.approx(list(pct[50]))
            assert [s["whislo"] for s in stats] == pytest.approx(list(pct[10]))
            assert np.isfinite([s["std"] for s in stats]).all()
            # La caché devuelve exactamente lo mismo que calcular de nuevo.
            fresco = strategy.percentiles(years, real, percentiles=[10, 50, 90])
            assert list(strategy.distribution_stats(years, real)[90]) == list(fresco[90])
