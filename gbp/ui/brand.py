"""Acceso a los recursos de marca Ikalon.

Los archivos viven en `gbp/data/brand/` y viajan dentro del ejecutable, así que
la ruta se resuelve con el mismo helper que usa la matriz de correlación
(`gbp.model.correlation.data_dir`), que ya contempla PyInstaller.

Si un recurso falta, las funciones devuelven `None` en vez de reventar: la app
debe abrir igual aunque alguien borre un PNG.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap

from ..model.correlation import data_dir

BRAND_DIRNAME = "brand"


def brand_dir() -> Path:
    return data_dir() / BRAND_DIRNAME


def _path(filename: str) -> Path | None:
    path = brand_dir() / filename
    return path if path.exists() else None


def app_icon() -> QIcon | None:
    """Ícono de la aplicación, multi-resolución.

    Lleva el wordmark en los tamaños grandes y el símbolo en los pequeños, que
    es lo único legible a 16 píxeles.
    """
    path = _path("gbp.ico")
    return QIcon(str(path)) if path else None


def wordmark_pixmap(height: int = 26) -> QPixmap | None:
    """Wordmark Ikalon escalado a una altura dada, sin deformar."""
    return _scaled("wordmark.png", height)


def symbol_pixmap(height: int = 26) -> QPixmap | None:
    """Símbolo (roseta) Ikalon en navy, para fondo blanco."""
    return _scaled("simbolo.png", height)


def _scaled(filename: str, height: int) -> QPixmap | None:
    from PySide6.QtCore import Qt

    path = _path(filename)
    if not path:
        return None
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None
    return pixmap.scaledToHeight(
        height,
        Qt.TransformationMode.SmoothTransformation,
    )
