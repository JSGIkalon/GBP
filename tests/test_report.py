"""Tests del informe PDF y del progreso granular de la simulacion.

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
    DISTRIBUTION,
    ReportOptions,
    _build_annex,
    _cite,
    build_report,
)
from gbp.model.allocation import Allocation
from gbp.model.cashflows import CashFlow, FlowKind
from gbp.model.leverage import LoanTerms
from gbp.model.scenario import Scenario, SimulationSettings
from gbp.model.strategy import Strategy


@pytest.fixture
def escenario() -> Scenario:
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
def corrida(escenario, simple_cmas, simple_corr):
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


def test_el_informe_se_escribe_y_es_un_pdf(corrida, tmp_path):
    escenario, result, settings = corrida
    path = build_report(
        tmp_path / "informe.pdf",
        ReportOptions(title="Proyeccion", client="Familia X", author="Analista",
                      report_date=date(2026, 3, 15)),
        escenario, result, settings,
    )
    assert path.exists()
    assert path.read_bytes().startswith(b"%PDF")
    assert path.stat().st_size > 10_000


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
                      include_inputs=False),
        escenario, result, settings,
    )
    assert _paginas(minimo) == 1  # solo la portada
    assert _paginas(completo) > _paginas(minimo)


def test_la_portada_llega_a_los_metadatos(corrida, tmp_path):
    escenario, result, settings = corrida
    path = build_report(
        tmp_path / "meta.pdf",
        ReportOptions(title="Revision anual", author="Ikalon"),
        escenario, result, settings,
    )
    raw = path.read_bytes()
    assert b"Revision anual" in raw
    assert b"Ikalon" in raw


def test_un_caso_sin_deuda_omite_la_seccion_de_deuda(
    corrida, escenario, simple_cmas, simple_corr, tmp_path
):
    _, con_deuda_result, settings = corrida
    con_deuda = build_report(
        tmp_path / "con_deuda.pdf", ReportOptions(),
        escenario, con_deuda_result, settings,
    )

    for strategy in escenario.strategies:
        strategy.loan = None
    sin_deuda_result = simulate(escenario, simple_cmas, simple_corr, settings)
    sin_deuda = build_report(
        tmp_path / "sin_deuda.pdf", ReportOptions(),
        escenario, sin_deuda_result, settings,
    )
    assert _paginas(sin_deuda) < _paginas(con_deuda)


def test_el_anexo_trae_una_tabla_por_estrategia_agrupada_por_tipo(corrida):
    """Una tabla por estrategia, y los tipos consecutivos.

    No se verifica sobre el PDF: matplotlib escribe el texto de pagina como
    subconjuntos de glifos, asi que buscar la palabra "Anexo" en los bytes no
    la encuentra aunque este impresa. El contrato que importa vive en
    `_build_annex`, que es lo que citan las graficas.
    """
    escenario, result, settings = corrida
    years = settings.milestones_within(escenario.horizon)
    nombres = [s.name for s in escenario.strategies]

    annex = _build_annex(
        ReportOptions(), escenario, result, years, False, True, "Valores nominales."
    )

    assert [t.number for t in annex] == list(range(1, len(annex) + 1))
    assert all(t.rows for t in annex), "Una tabla del anexo salio vacia"

    # Cuatro tipos por dos estrategias.
    assert len(annex) == 4 * len(nombres)
    # Cada tabla es de UNA estrategia, y cada tipo las recorre todas en orden.
    for i in range(0, len(annex), len(nombres)):
        bloque = annex[i:i + len(nombres)]
        assert len({t.kind for t in bloque}) == 1, "Un tipo quedo partido"
        assert [t.strategy for t in bloque] == nombres


def test_cada_grafica_cita_las_tablas_de_su_tipo(corrida):
    """Una grafica compara estrategias, asi que remite a todas sus tablas."""
    escenario, result, settings = corrida
    years = settings.milestones_within(escenario.horizon)

    annex = _build_annex(
        ReportOptions(), escenario, result, years, False, True, "Valores nominales."
    )
    numeros = [t.number for t in annex if t.kind == DISTRIBUTION]
    assert len(numeros) == 2

    cita = _cite(annex, DISTRIBUTION, "Nota.")
    assert cita == f"Nota. Detalle en el Anexo · Tablas {numeros[0]} y {numeros[1]}."


def test_una_seccion_excluida_no_deja_su_tabla_en_el_anexo(corrida):
    """Un anexo con el detalle de una grafica ausente no lo entenderia nadie."""
    escenario, result, settings = corrida
    years = settings.milestones_within(escenario.horizon)

    annex = _build_annex(
        ReportOptions(include_distribution=False, include_summary=False),
        escenario, result, years, False, False, "Valores nominales.",
    )
    assert {t.kind for t in annex} == {ALLOCATION}
    assert [t.number for t in annex] == [1, 2]  # renumera, no deja huecos
    assert _cite(annex, DISTRIBUTION, "Nota.") == "Nota."  # no cita lo que no existe


# --------------------------------------------------------------------------
# Progreso
# --------------------------------------------------------------------------


def test_el_progreso_avanza_ano_a_ano(escenario, simple_cmas, simple_corr):
    """Con una sola estrategia la barra tiene que pasar por el medio.

    Antes el progreso se contaba por estrategia, asi que un caso de una sola
    estrategia saltaba de 0 a 100 sin ningun paso intermedio.
    """
    escenario.strategies = escenario.strategies[:1]
    avisos = []
    settings = SimulationSettings(n_paths=200, seed=5)
    simulate(escenario, simple_cmas, simple_corr, settings,
             progress=lambda done, total, label: avisos.append((done, total, label)))

    total = avisos[0][1]
    assert total == 1 + escenario.horizon
    assert all(t == total for _, t, _ in avisos)

    valores = [done for done, _, _ in avisos]
    assert valores[0] == 0
    assert valores[-1] == total
    assert valores == sorted(valores)          # nunca retrocede
    assert len({v for v in valores}) > 2       # pasa por el medio, no salta
    assert "Listo" in avisos[-1][2]


def test_el_progreso_es_opcional(escenario, simple_cmas, simple_corr):
    result = simulate(escenario, simple_cmas, simple_corr,
                      SimulationSettings(n_paths=200, seed=5))
    assert len(result.strategies) == 2
