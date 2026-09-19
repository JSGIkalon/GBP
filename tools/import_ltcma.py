"""Importa las *Assumption Matrices* (sección III) del LTCMA de J.P. Morgan.

Lee la página de supuestos en USD del reporte completo LTCMA en PDF y genera
dos recursos embebidos de la app:

* `gbp/data/correlations.json` — matriz de correlación completa entre las 60
  clases de activo (la app la usa en modo lectura; no es un input de la UI).
* `gbp/data/ltcma_usd.json` — retorno compuesto, retorno aritmético y
  volatilidad por clase de activo, que sirven de semilla para la librería de
  CMAs. El **yield no viene en el LTCMA** y queda en cero para que se ingrese a
  mano.

Formato de cada fila en el PDF:

    <nombre> <comp2026> <arit2026> <volatilidad> <comp2025> <corr_1> ... <corr_i>

con la matriz en triangular inferior, es decir la fila `i` trae `i+1`
correlaciones y la última siempre es 1.00.

Uso:
    python tools/import_ltcma.py "C:\\ruta\\ltcma-full-report.pdf"
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "gbp" / "data"

# La tabla en USD se repite en dos páginas; basta con la primera que esté completa.
CANDIDATE_PAGES = (81, 82)

NUMBER = re.compile(r"-?\d+\.\d{2}")
# Encabezados y notas que aparecen intercalados entre las filas de la tabla.
SECTION_HEADERS = {
    "fixed income",
    "equities",
    "alternatives",
    "real assets",
    "back to contents",
}


def clean(text: str) -> str:
    """Normaliza el texto extraído del PDF (espacios duros, guiones raros)."""
    text = text.replace("\u00a0", " ").replace("\u00ad", "")
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u2013", "-").replace("\u2019", "'")
    # pypdf a veces deja una "Â" suelta donde había un espacio duro.
    return text.replace("Â", " ")


def parse_rows(page_text: str) -> list[tuple[str, list[float], list[float]]]:
    """Extrae (nombre, [comp, arit, vol, comp2025], correlaciones) de cada fila."""
    rows: list[tuple[str, list[float], list[float]]] = []
    for raw in clean(page_text).splitlines():
        line = raw.strip()
        if not line or line.lower() in SECTION_HEADERS:
            continue
        match = NUMBER.search(line)
        if not match:
            continue
        name = line[: match.start()].strip()
        numbers = [float(v) for v in NUMBER.findall(line[match.start() :])]
        # Una fila válida trae las 4 estadísticas más al menos una correlación,
        # y la última correlación es siempre 1.00 (la diagonal).
        if not name or len(numbers) < 5 or abs(numbers[-1] - 1.0) > 1e-9:
            continue
        # La fila número i (base 0) debe traer i+1 correlaciones.
        expected_corr = len(rows) + 1
        if len(numbers) != 4 + expected_corr:
            raise ValueError(
                f"Fila '{name}': se esperaban {4 + expected_corr} números y "
                f"llegaron {len(numbers)}. La extracción del PDF cambió."
            )
        rows.append((name, numbers[:4], numbers[4:]))
    return rows


def build_matrix(rows) -> np.ndarray:
    n = len(rows)
    corr = np.eye(n)
    for i, (_, _, values) in enumerate(rows):
        for j, value in enumerate(values):
            corr[i, j] = corr[j, i] = value
    return corr


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(f"Uso: python {Path(__file__).name} <ruta al LTCMA en PDF>")
    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        raise SystemExit(f"No se encontró el archivo: {pdf_path}")

    from pypdf import PdfReader  # noqa: PLC0415  (dependencia solo de este importador)

    reader = PdfReader(str(pdf_path))
    rows: list = []
    for page_index in CANDIDATE_PAGES:
        if page_index >= len(reader.pages):
            continue
        candidate = parse_rows(reader.pages[page_index].extract_text() or "")
        if len(candidate) > len(rows):
            rows = candidate
    if len(rows) < 10:
        raise SystemExit(
            "No se pudo leer la tabla de supuestos en USD. Revisa que el PDF sea el "
            "reporte completo del LTCMA y que la sección III siga en las mismas páginas."
        )

    names = [name for name, _, _ in rows]
    if len(set(names)) != len(names):
        raise SystemExit("La tabla trae nombres de clase de activo repetidos.")

    corr = build_matrix(rows)
    eigmin = float(np.linalg.eigvalsh(corr).min())
    # Las matrices publicadas vienen redondeadas a dos decimales y estimadas sobre
    # ventanas distintas, así que un autovalor levemente negativo es normal: el
    # motor la proyecta a la PSD más cercana al cargarla. Un negativo grande sí
    # indicaría que la extracción del PDF se desalineó.
    if eigmin < -0.05:
        raise SystemExit(
            f"La matriz leída está lejos de ser semidefinida positiva "
            f"(lambda min = {eigmin:.6f}); probablemente la extracción se desalineó."
        )

    DATA.mkdir(parents=True, exist_ok=True)
    source = f"J.P. Morgan 2026 Long-Term Capital Market Assumptions (USD) — {pdf_path.name}"

    (DATA / "correlations.json").write_text(
        json.dumps(
            {
                "source": source,
                "provisional": False,
                "assets": names,
                "matrix": [[round(v, 4) for v in row] for row in corr],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    (DATA / "ltcma_usd.json").write_text(
        json.dumps(
            {
                "source": source,
                "note": (
                    "El LTCMA no publica yield por clase de activo; se deja en cero "
                    "para que se ingrese a mano en la librería de CMAs."
                ),
                "assets": [
                    {
                        "name": name,
                        "compound_return": stats[0] / 100.0,
                        "arithmetic_return": stats[1] / 100.0,
                        "volatility": stats[2] / 100.0,
                        "yield": 0.0,
                    }
                    for name, stats, _ in rows
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"{len(names)} clases de activo importadas desde {pdf_path.name}")
    print(f"  matriz de correlación -> {DATA / 'correlations.json'} (lambda min = {eigmin:.6f})")
    print(f"  supuestos por activo  -> {DATA / 'ltcma_usd.json'}")


if __name__ == "__main__":
    main()
