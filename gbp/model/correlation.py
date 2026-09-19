"""Matriz de correlación entre clases de activo.

La matriz **no es un input de la interfaz**: se toma de las *Assumption Matrices*
(sección III) del LTCMA 2026 de J.P. Morgan (tabla de supuestos en USD, 59 clases
de activo) y queda embebida como recurso de la app en `gbp/data/correlations.json`,
generado por `tools/import_ltcma.py`. La UI solo la muestra en modo lectura.

La matriz publicada viene redondeada a dos decimales y estimada sobre ventanas
distintas, así que no es exactamente semidefinida positiva (su autovalor mínimo
es del orden de -0.016). El JSON conserva los valores tal como los publica J.P.
Morgan, y `CorrelationMatrix.load` proyecta la matriz a la PSD más cercana antes
de entregarla al motor.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DATA_FILENAME = "correlations.json"


def data_dir() -> Path:
    """Directorio de recursos embebidos, también dentro del .exe de PyInstaller."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "gbp" / "data"
    return Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class CorrelationMatrix:
    """Matriz de correlación con nombres de clases de activo.

    `matrix` es simétrica, con unos en la diagonal y semidefinida positiva.
    """

    names: list[str]
    matrix: np.ndarray
    source: str = ""
    provisional: bool = False
    psd_adjustment: float = 0.0
    """Máxima corrección absoluta aplicada al proyectar la matriz a la PSD."""

    def __post_init__(self) -> None:
        n = len(self.names)
        if self.matrix.shape != (n, n):
            raise ValueError(
                f"La matriz es {self.matrix.shape} pero hay {n} clases de activo."
            )
        if not np.allclose(self.matrix, self.matrix.T, atol=1e-9):
            raise ValueError("La matriz de correlación no es simétrica.")
        if not np.allclose(np.diag(self.matrix), 1.0, atol=1e-9):
            raise ValueError("La diagonal de la matriz de correlación debe ser 1.")

    def subset(self, names: list[str]) -> np.ndarray:
        """Submatriz para las clases indicadas, en ese orden."""
        missing = [n for n in names if n not in self.names]
        if missing:
            raise KeyError(
                "La matriz de correlación embebida no cubre estas clases de activo: "
                + ", ".join(missing)
            )
        idx = [self.names.index(n) for n in names]
        return self.matrix[np.ix_(idx, idx)]

    @classmethod
    def load(cls, path: Path | None = None) -> "CorrelationMatrix":
        path = path or (data_dir() / DATA_FILENAME)
        if not path.exists():
            raise FileNotFoundError(
                f"No se encontró la matriz de correlación embebida en {path}."
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        published = np.asarray(payload["matrix"], dtype=float)
        repaired = nearest_psd(published)
        return cls(
            names=list(payload["assets"]),
            matrix=repaired,
            source=payload.get("source", ""),
            provisional=bool(payload.get("provisional", False)),
            psd_adjustment=float(np.abs(repaired - published).max()),
        )


def nearest_psd(matrix: np.ndarray, epsilon: float = 1e-10) -> np.ndarray:
    """Proyecta una matriz de correlación a la semidefinida positiva más cercana.

    Trunca los autovalores negativos (que aparecen cuando la matriz proviene de
    estimaciones sobre ventanas distintas) y renormaliza para que la diagonal
    vuelva a ser exactamente 1.
    """
    sym = (matrix + matrix.T) / 2.0
    eigvals, eigvecs = np.linalg.eigh(sym)
    if eigvals.min() >= epsilon:
        return sym
    eigvals = np.clip(eigvals, epsilon, None)
    repaired = eigvecs @ np.diag(eigvals) @ eigvecs.T
    scale = np.sqrt(np.diag(repaired))
    repaired = repaired / np.outer(scale, scale)
    np.fill_diagonal(repaired, 1.0)
    return repaired


def is_psd(matrix: np.ndarray, tol: float = 1e-10) -> bool:
    return bool(np.linalg.eigvalsh((matrix + matrix.T) / 2.0).min() >= -tol)


def covariance(sigmas: np.ndarray, corr: np.ndarray) -> np.ndarray:
    """Covarianza a partir de volatilidades y correlaciones."""
    return np.outer(sigmas, sigmas) * corr


def cholesky_factor(cov: np.ndarray) -> np.ndarray:
    """Factor de Cholesky de una matriz de covarianza.

    Tolera dos casos que aparecen con datos reales y que harían fallar a
    `np.linalg.cholesky` directo:

    * Clases de activo con volatilidad cero (por ejemplo, un activo modelado
      como determinístico). Se excluyen del factor y su fila queda en cero, de
      modo que no reciben ningún shock en vez de un ruido numérico espurio.
    * Matrices que no son definidas positivas por el redondeo de la fuente. Se
      proyectan a la PSD más cercana antes de factorizar.
    """
    n = len(cov)
    zero_variance = np.isclose(np.diag(cov), 0.0, atol=1e-18)
    if zero_variance.all():
        return np.zeros_like(cov)

    idx = np.flatnonzero(~zero_variance)
    sub = cov[np.ix_(idx, idx)]

    try:
        factor_sub = np.linalg.cholesky(sub)
    except np.linalg.LinAlgError:
        sigmas = np.sqrt(np.diag(sub))
        corr = sub / np.outer(sigmas, sigmas)
        np.fill_diagonal(corr, 1.0)
        repaired = covariance(sigmas, nearest_psd(corr))
        # Un último empujón en la diagonal para vencer el error de redondeo.
        repaired += np.eye(len(sub)) * np.trace(repaired) * 1e-12
        factor_sub = np.linalg.cholesky(repaired)

    factor = np.zeros((n, n), dtype=float)
    factor[np.ix_(idx, idx)] = factor_sub
    return factor
