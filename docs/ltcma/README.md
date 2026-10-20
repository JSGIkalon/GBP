# Fuentes originales del LTCMA de J.P. Morgan

Un PDF por edición, tal como lo publica J.P. Morgan Asset Management. Son el sustento
de los supuestos embebidos en `gbp/data/` (generados con `tools/import_ltcma.py`).

| Edición | Archivo | Estimados al | En la app desde |
|---|---|---|---|
| 2027 (31.ª) | `JPM_LTCMA_2027.pdf` (resumido, 78 págs.; tabla USD en págs. 68-69) | 30-sep-2026 | 0.3.1 |
| 2026 | `JPM_LTCMA_2026.pdf` (reporte completo; tabla USD en págs. 82-83) | 30-sep-2025 | 0.1.0 a 0.3.0 |

Convención: `JPM_LTCMA_<año>.pdf`. Cada edición nueva se agrega aquí, nunca se reemplaza.
Uso: `python tools/import_ltcma.py docs/ltcma/JPM_LTCMA_<año>.pdf`