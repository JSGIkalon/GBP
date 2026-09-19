"""Extrae los logos Ikalon de la plantilla de presentaciones.

Los logos no viven en un archivo suelto: están embebidos en
`plantilla-ikalon-2026.pptx`, que es un zip. Este script los saca, los
identifica y deja en `gbp/data/brand/` lo que la app necesita:

* `simbolo.png`  — el isotipo, casi cuadrado
* `wordmark.png` — la marca denominativa, apaisada
* `gbp.ico`      — ícono multi-resolución de Windows

**Por qué el .ico mezcla las dos piezas.** Un wordmark es ancho; reducido a los
16×16 de la barra de tareas queda como una mancha ilegible. Un `.ico` admite
varias resoluciones con arte distinto, así que lleva el wordmark en los tamaños
grandes —donde se lee y es la marca que corresponde— y el símbolo en los
pequeños, donde es lo único que sobrevive. Windows elige según el contexto.

Uso:
    python tools/extract_brand.py [ruta a plantilla-ikalon-2026.pptx]
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "gbp" / "data" / "brand"

DEFAULT_TEMPLATE = (
    Path.home()
    / ".claude/skills/synced"
    / "805e2d19-7aa7-4111-9dd5-8eb6afd24997_29348f8a-c00e-4e91-98c4-ad77512e71e3"
    / "estilo-ikalon-decks"
    / "plantilla-ikalon-2026.pptx"
)

# Tamaños del .ico. Por debajo de 48 px el wordmark es ilegible, así que ahí
# entra el símbolo.
SYMBOL_SIZES = (16, 24, 32)
WORDMARK_SIZES = (48, 64, 128, 256)


def candidates(pptx: Path, work: Path) -> list[Path]:
    """Extrae los PNG de la plantilla a una carpeta de trabajo."""
    work.mkdir(parents=True, exist_ok=True)
    paths = []
    with zipfile.ZipFile(pptx) as z:
        for info in z.infolist():
            if "/media/" not in info.filename or not info.filename.lower().endswith(".png"):
                continue
            target = work / Path(info.filename).name
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            paths.append(target)
    return paths


def describe(paths: list[Path]) -> list[dict]:
    """Mide cada PNG: tamaño, proporción y densidad de píxeles opacos."""
    from PIL import Image

    rows = []
    for path in paths:
        try:
            with Image.open(path) as im:
                im = im.convert("RGBA")
                w, h = im.size
                alpha = im.getchannel("A")
                opaque = sum(1 for v in alpha.getdata() if v > 16)
                rows.append(
                    {
                        "path": path,
                        "w": w,
                        "h": h,
                        "ratio": w / h if h else 0.0,
                        "fill": opaque / (w * h) if w * h else 0.0,
                    }
                )
        except Exception:  # noqa: BLE001 — un media corrupto no debe romper el script
            continue
    return rows


def build_ico(symbol: Path, wordmark: Path, out: Path) -> None:
    """Ícono multi-resolución: símbolo en chico, wordmark en grande.

    El `.ico` se arma a mano y no con `Image.save(format="ICO")`: ese camino
    ignora `append_images` y escribe un solo frame, así que el ícono salía de
    16×16 y nada más. El formato es simple —una cabecera, una entrada por
    tamaño y los PNG concatenados, que Windows acepta desde Vista— y armarlo
    directo permite meter arte distinto en cada resolución.
    """
    import io
    import struct

    from PIL import Image

    frames = []
    with Image.open(symbol) as sym, Image.open(wordmark) as word:
        sym, word = sym.convert("RGBA"), word.convert("RGBA")
        frames += [_fit(sym, size) for size in SYMBOL_SIZES]
        frames += [_fit(word, size) for size in WORDMARK_SIZES]

    blobs = []
    for frame in frames:
        buffer = io.BytesIO()
        frame.save(buffer, format="PNG")
        blobs.append(buffer.getvalue())

    header = struct.pack("<HHH", 0, 1, len(frames))  # reservado, tipo ícono, cantidad
    offset = len(header) + 16 * len(frames)
    entries = b""
    for frame, blob in zip(frames, blobs):
        entries += struct.pack(
            "<BBBBHHII",
            frame.width if frame.width < 256 else 0,   # 0 significa 256
            frame.height if frame.height < 256 else 0,
            0,      # paleta
            0,      # reservado
            1,      # planos
            32,     # bits por pixel
            len(blob),
            offset,
        )
        offset += len(blob)

    out.write_bytes(header + entries + b"".join(blobs))


def _fit(image, size: int):
    """Encaja la imagen en un lienzo cuadrado transparente, sin deformarla."""
    from PIL import Image

    source = image.copy()
    source.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    canvas.paste(source, ((size - source.width) // 2, (size - source.height) // 2), source)
    return canvas


def main() -> int:
    pptx = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TEMPLATE
    if not pptx.exists():
        raise SystemExit(f"No se encontró la plantilla: {pptx}")

    work = ROOT / "build" / "brand_candidates"
    rows = describe(candidates(pptx, work))
    if not rows:
        raise SystemExit("No se extrajo ningún PNG de la plantilla.")

    print(f"{len(rows)} imágenes extraídas en {work}")
    print("\nCandidatos a wordmark (apaisados, proporción > 2.5):")
    wide = sorted([r for r in rows if r["ratio"] > 2.5], key=lambda r: -r["w"])
    for r in wide[:12]:
        print(f"  {r['path'].name:<16} {r['w']:>5}x{r['h']:<5} ratio {r['ratio']:>5.2f}  relleno {r['fill']:.0%}")

    print("\nCandidatos a símbolo (casi cuadrados, 0.7 < proporción < 1.4):")
    square = sorted([r for r in rows if 0.7 < r["ratio"] < 1.4], key=lambda r: -r["w"])
    for r in square[:12]:
        print(f"  {r['path'].name:<16} {r['w']:>5}x{r['h']:<5} ratio {r['ratio']:>5.2f}  relleno {r['fill']:.0%}")

    print(
        "\nRevisa las imágenes y copia las elegidas como "
        f"{OUT / 'simbolo.png'} y {OUT / 'wordmark.png'}, "
        "luego vuelve a correr con --build-ico"
    )
    return 0


def build_only() -> int:
    symbol, wordmark = OUT / "simbolo.png", OUT / "wordmark.png"
    for path in (symbol, wordmark):
        if not path.exists():
            raise SystemExit(f"Falta {path}")
    build_ico(symbol, wordmark, OUT / "gbp.ico")
    print(f"Ícono escrito en {OUT / 'gbp.ico'}")
    return 0


if __name__ == "__main__":
    if "--build-ico" in sys.argv:
        sys.exit(build_only())
    sys.exit(main())
