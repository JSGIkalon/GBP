"""Tests de los activos propios: la derivacion de correlaciones.

Es la parte del proyecto donde una equivocacion no se ve. Un activo propio mal
correlacionado no rompe nada: simula igual y da numeros plausibles y falsos. Por
eso aqui se verifica la propiedad matematica (que la matriz extendida sea la
correlacion de un vector realizable) y no solo que el codigo corra.
"""

from __future__ import annotations

import numpy as np
import pytest

from gbp.model.assets import ORIGIN_CUSTOM, AssetClass, CMASet
from gbp.model.correlation import CorrelationMatrix, is_psd
from gbp.model.custom_assets import (
    CORRELATION_CAP,
    class_loading,
    custom_pairs,
    extend_correlations,
    resolver_for,
)
from gbp.model.groups import ALTERNATIVES, CASH, EQUITY, FIXED_INCOME, ltcma_members


@pytest.fixture
def base() -> CorrelationMatrix:
    """La matriz real del LTCMA: es donde viven los casos degenerados."""
    return CorrelationMatrix.load()


def _propio(nombre: str, clase: str) -> AssetClass:
    return AssetClass(nombre, 0.10, 0.02, origin=ORIGIN_CUSTOM, asset_class=clase)


# --------------------------------------------------------------------------
# La propiedad que lo sostiene todo
# --------------------------------------------------------------------------


@pytest.mark.parametrize("clase", [EQUITY, FIXED_INCOME, ALTERNATIVES, CASH])
def test_la_matriz_extendida_es_psd_para_toda_clase(base, clase):
    ext = extend_correlations(base, [("Propio", clase)])
    assert is_psd(ext.matrix)


def test_la_matriz_extendida_es_definida_positiva(base):
    """El caso que rompia el diseno: la clase Caja tiene un solo miembro.

    Con lambda = 1 el activo propio saldria con correlacion 1.00 contra
    'U.S. Cash' —un clon sin riesgo propio— y la matriz quedaria exactamente
    singular. El tope de correlacion es lo que lo evita.
    """
    assert len(ltcma_members(base.names)[CASH]) == 1, "Caja dejo de ser degenerada"

    ext = extend_correlations(base, [("Caja COP", CASH), ("Caja MXN", CASH)])
    eigmin = float(np.linalg.eigvalsh((ext.matrix + ext.matrix.T) / 2).min())

    base_eigmin = float(np.linalg.eigvalsh(base.matrix).min())
    assert eigmin >= base_eigmin - 1e-9, "la extension añadio singularidad propia"

    i, j = ext.names.index("Caja COP"), ext.names.index("U.S. Cash")
    assert ext.matrix[i, j] < 1.0
    assert ext.matrix[i, j] == pytest.approx(np.sqrt(CORRELATION_CAP), abs=1e-6)


def test_cholesky_funciona_con_dos_activos_propios_de_caja(base):
    from gbp.model.correlation import cholesky_factor, covariance

    ext = extend_correlations(base, [("Caja COP", CASH), ("Caja MXN", CASH)])
    sigmas = np.full(len(ext.names), 0.05)
    factor = cholesky_factor(covariance(sigmas, ext.matrix))
    assert np.all(np.isfinite(factor))


# --------------------------------------------------------------------------
# Que los numeros derivados sean los que se prometen
# --------------------------------------------------------------------------


def test_la_correlacion_derivada_es_el_promedio_de_la_clase(base):
    ext = extend_correlations(base, [("Renta Fija Colombiana", FIXED_INCOME)])
    miembros = ltcma_members(base.names)[FIXED_INCOME]
    idx = [base.names.index(n) for n in miembros]
    esperado = base.matrix[idx, :].mean(axis=0)  # lambda = 1 en esta clase

    fila = ext.matrix[ext.names.index("Renta Fija Colombiana"), : len(base.names)]
    np.testing.assert_allclose(fila, esperado, atol=1e-12)


def test_el_promedio_de_clase_incluye_los_terminos_diagonales(base):
    """Excluir la diagonal romperia la garantia de PSD en silencio.

    El promedio del bloque tiene que valer var(p) del portafolio equiponderado;
    eso solo se cumple si los terminos g == h (que valen 1) estan dentro.
    """
    miembros = ltcma_members(base.names)[ALTERNATIVES]
    idx = [base.names.index(n) for n in miembros]
    bloque = base.matrix[np.ix_(idx, idx)]

    k = len(idx)
    con_diagonal = float(bloque.mean())
    sin_diagonal = float((bloque.sum() - k) / (k * k - k))
    assert con_diagonal > sin_diagonal

    # var(p) calculada directamente sobre pesos iguales
    w = np.full(k, 1.0 / k)
    var_p = float(w @ bloque @ w)
    assert con_diagonal == pytest.approx(var_p)


def test_dos_activos_propios_de_la_misma_clase_no_son_clones(base):
    ext = extend_correlations(
        base, [("Colombia A", FIXED_INCOME), ("Colombia B", FIXED_INCOME)]
    )
    i, j = ext.names.index("Colombia A"), ext.names.index("Colombia B")
    corr = ext.matrix[i, j]
    assert 0.0 < corr < 1.0

    # Es var(p): se parecen mucho, pero cada uno conserva su riesgo propio.
    miembros = ltcma_members(base.names)[FIXED_INCOME]
    idx = [base.names.index(n) for n in miembros]
    assert corr == pytest.approx(float(base.matrix[np.ix_(idx, idx)].mean()))


def test_la_correlacion_entre_clases_distintas_es_el_promedio_cruzado(base):
    ext = extend_correlations(
        base, [("Acciones Col", EQUITY), ("Bonos Col", FIXED_INCOME)]
    )
    ia = [base.names.index(n) for n in ltcma_members(base.names)[EQUITY]]
    ib = [base.names.index(n) for n in ltcma_members(base.names)[FIXED_INCOME]]
    esperado = float(base.matrix[np.ix_(ia, ib)].mean())

    i, j = ext.names.index("Acciones Col"), ext.names.index("Bonos Col")
    assert ext.matrix[i, j] == pytest.approx(esperado)


def test_el_tope_no_afecta_a_las_clases_pobladas(base):
    for clase in (EQUITY, FIXED_INCOME, ALTERNATIVES):
        _, lam = class_loading(base, clase)
        assert lam == 1.0, f"{clase} no deberia necesitar tope"
    _, lam_caja = class_loading(base, CASH)
    assert lam_caja < 1.0


# --------------------------------------------------------------------------
# Forma, orden y bordes
# --------------------------------------------------------------------------


def test_la_matriz_extendida_conserva_intacto_el_bloque_del_ltcma(base):
    ext = extend_correlations(base, [("Propio", EQUITY)])
    n = len(base.names)
    np.testing.assert_array_equal(ext.matrix[:n, :n], base.matrix)
    assert ext.names[:n] == base.names
    assert ext.source == base.source


def test_la_diagonal_es_uno_y_la_matriz_es_simetrica(base):
    ext = extend_correlations(base, [("A", EQUITY), ("B", CASH)])
    np.testing.assert_allclose(np.diag(ext.matrix), 1.0)
    np.testing.assert_allclose(ext.matrix, ext.matrix.T, atol=1e-12)


def test_extender_sin_activos_propios_devuelve_la_matriz_base(base):
    assert extend_correlations(base, []) is base


def test_los_activos_propios_van_al_final_en_el_orden_dado(base):
    ext = extend_correlations(base, [("Z", EQUITY), ("A", FIXED_INCOME)])
    assert ext.names[-2:] == ["Z", "A"]


def test_una_clase_sin_miembros_levanta_error(base):
    with pytest.raises(ValueError, match="no tiene ninguna clase del LTCMA"):
        extend_correlations(base, [("Raro", "Clase inventada")])


def test_un_activo_propio_no_puede_llamarse_como_uno_del_ltcma(base):
    with pytest.raises(ValueError, match="chocan con clases del LTCMA"):
        extend_correlations(base, [("U.S. Large Cap", EQUITY)])


def test_no_se_admiten_activos_propios_duplicados(base):
    with pytest.raises(ValueError, match="duplicados"):
        extend_correlations(base, [("A", EQUITY), ("A", FIXED_INCOME)])


# --------------------------------------------------------------------------
# Puente con la librería
# --------------------------------------------------------------------------


def test_custom_pairs_solo_devuelve_los_propios():
    cmas = CMASet(
        [
            AssetClass("U.S. Large Cap", 0.07, 0.16),
            _propio("Renta Fija Colombiana", FIXED_INCOME),
        ]
    )
    assert custom_pairs(cmas) == [("Renta Fija Colombiana", FIXED_INCOME, None)]


def test_el_resolvedor_conoce_la_clase_declarada(base):
    cmas = CMASet([_propio("Renta Fija Colombiana", FIXED_INCOME)])
    resolver = resolver_for(cmas, base)

    assert resolver.group_of("Renta Fija Colombiana") == FIXED_INCOME
    assert resolver.group_of("U.S. Large Cap") == EQUITY  # sigue el fallback
    assert resolver.is_custom("Renta Fija Colombiana")
    assert not resolver.is_custom("U.S. Large Cap")
    assert "U.S. Aggregate Bonds" in resolver.members_of("Renta Fija Colombiana")
    assert resolver.members_of("U.S. Large Cap") == ()


# --------------------------------------------------------------------------
# Validación del modelo
# --------------------------------------------------------------------------


def test_un_activo_propio_exige_clase_declarada():
    with pytest.raises(ValueError, match="debe declarar su clase"):
        AssetClass("Colombia", 0.10, 0.02, origin=ORIGIN_CUSTOM)


def test_otros_no_sirve_como_clase_declarada():
    from gbp.model.groups import OTHER

    with pytest.raises(ValueError, match="no sirve como clase declarada"):
        AssetClass("Colombia", 0.10, 0.02, origin=ORIGIN_CUSTOM, asset_class=OTHER)


def test_una_clase_del_ltcma_no_guarda_clase_declarada():
    a = AssetClass("U.S. Large Cap", 0.07, 0.16, asset_class=EQUITY)
    assert a.asset_class is None
    assert not a.is_custom


def test_una_clase_del_ltcma_no_guarda_fuente_de_correlacion():
    a = AssetClass(
        "U.S. Large Cap", 0.07, 0.16, asset_class=EQUITY,
        correlation_source="U.S. Cash",
    )
    assert a.correlation_source is None


# --------------------------------------------------------------------------
# Anclar a un solo activo de la librería, en vez del promedio de la clase
# --------------------------------------------------------------------------


def test_anclar_a_un_activo_reproduce_su_fila_con_tope(base):
    row, lam = class_loading(base, FIXED_INCOME, "U.S. Cash")
    assert lam == pytest.approx(np.sqrt(CORRELATION_CAP))
    esperado = base.matrix[base.names.index("U.S. Cash"), :] * lam
    np.testing.assert_allclose(row, esperado)


def test_la_matriz_extendida_con_fuente_puntual_es_psd(base):
    ext = extend_correlations(
        base, [("Renta Fija Colombiana", FIXED_INCOME, "U.S. Cash")]
    )
    assert is_psd(ext.matrix)
    i, j = ext.names.index("Renta Fija Colombiana"), ext.names.index("U.S. Cash")
    assert ext.matrix[i, j] == pytest.approx(np.sqrt(CORRELATION_CAP), abs=1e-6)


def test_la_fuente_puntual_no_es_el_promedio_de_la_clase(base):
    row_clase, _ = class_loading(base, FIXED_INCOME)
    row_fuente, _ = class_loading(base, FIXED_INCOME, "U.S. Cash")
    assert not np.allclose(row_clase, row_fuente)


def test_una_fuente_de_correlacion_inexistente_levanta_error(base):
    with pytest.raises(ValueError, match="no está en la matriz de correlación base"):
        extend_correlations(
            base, [("Renta Fija Colombiana", FIXED_INCOME, "Activo que no existe")]
        )


def test_custom_pairs_incluye_la_fuente_de_correlacion():
    cmas = CMASet(
        [AssetClass(
            "Renta Fija Colombiana", 0.10, 0.02, origin=ORIGIN_CUSTOM,
            asset_class=FIXED_INCOME, correlation_source="U.S. Cash",
        )]
    )
    assert custom_pairs(cmas) == [
        ("Renta Fija Colombiana", FIXED_INCOME, "U.S. Cash")
    ]
