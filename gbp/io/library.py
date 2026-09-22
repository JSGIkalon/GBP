"""Librería global de supuestos de mercado y configuración de la app.

Los retornos, volatilidades y yields se ingresan a mano y **no viven dentro del
caso del cliente**: viven aquí, en `%APPDATA%/Ikalon/GBP/`. Así se cargan
siempre al abrir la app y no se pierde lo ingresado al crear un caso nuevo.

La primera vez que se abre la app, la librería se siembra con los supuestos del
LTCMA embebido (`gbp/data/ltcma_usd.json`). El yield no viene en el LTCMA y
queda en cero para que se complete a mano.

Las escrituras son atómicas: se escribe un archivo temporal y se reemplaza, para
no dejar la librería a medias si la app se cierra en mitad del guardado.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from ..model.assets import ORIGIN_CUSTOM, ORIGIN_LTCMA, AssetClass, CMASet
from ..model.correlation import data_dir
from ..model.scenario import SimulationSettings

APP_DIR_NAME = Path("Ikalon") / "GBP"
LIBRARY_FILE = "cma_library.json"
SETTINGS_FILE = "settings.json"
SCHEMA_VERSION = 2
# La librería pasó a 3 al aparecer los activos propios: cada clase declara su
# origen y, si es propia, su clase de activo. Un archivo de esquema 2 se lee sin
# migración porque todo lo que no dice su origen es del LTCMA, que es lo que era.
LIBRARY_SCHEMA_VERSION = 3

# Años hito que traía la versión anterior. Si el archivo guardado tiene
# exactamente estos valores, el usuario nunca los tocó: se migran al nuevo
# valor por defecto, más corto, en vez de dejarlo con la lista vieja para
# siempre. Si los editó, se respetan.
LEGACY_MILESTONES = [5, 10, 15, 20, 25, 30]


def app_data_dir() -> Path:
    """Carpeta de datos del usuario, fuera del ejecutable."""
    base = os.environ.get("GBP_DATA_DIR") or os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_DIR_NAME


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def seed_cmas() -> CMASet:
    """Supuestos iniciales tomados del LTCMA embebido."""
    path = data_dir() / "ltcma_usd.json"
    if not path.exists():
        return CMASet([])
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CMASet(
        [
            AssetClass(
                name=entry["name"],
                compound_return=float(entry["compound_return"]),
                volatility=float(entry["volatility"]),
                yield_=float(entry.get("yield", 0.0)),
            )
            for entry in payload["assets"]
        ]
    )


def library_path() -> Path:
    return app_data_dir() / LIBRARY_FILE


def load_cmas() -> CMASet:
    """Carga la librería del usuario, sembrándola desde el LTCMA la primera vez."""
    path = library_path()
    if not path.exists():
        cmas = seed_cmas()
        save_cmas(cmas)
        return cmas

    payload = json.loads(path.read_text(encoding="utf-8"))
    return CMASet([asset_from_dict(entry) for entry in payload.get("assets", [])])


def asset_from_dict(entry: dict) -> AssetClass:
    """Una clase de activo desde su forma serializada, tolerante con lo viejo.

    Un esquema 2 no trae `origin`, así que todo queda como LTCMA — que es
    exactamente lo que era. Y una clase declarada desconocida **no levanta**:
    degrada a clase del LTCMA y la interfaz la mostrará para que se corrija. Una
    librería rara no puede impedir que la app abra.
    """
    from ..model.groups import GROUP_ORDER

    origin = entry.get("origin", ORIGIN_LTCMA)
    asset_class = entry.get("asset_class")
    if origin == ORIGIN_CUSTOM and asset_class not in GROUP_ORDER:
        origin, asset_class = ORIGIN_LTCMA, None

    return AssetClass(
        name=entry["name"],
        compound_return=float(entry["compound_return"]),
        volatility=float(entry["volatility"]),
        yield_=float(entry.get("yield_", entry.get("yield", 0.0))),
        origin=origin,
        asset_class=asset_class,
        notes=str(entry.get("notes", "")),
    )


def asset_to_dict(asset: AssetClass, with_origin: bool = True) -> dict:
    """Forma serializada de una clase de activo.

    Los campos de activo propio se **omiten** cuando no aplican, en vez de
    escribirse en `null`: así un archivo de una librería sin activos propios es
    byte a byte el de siempre.
    """
    payload = {
        "name": asset.name,
        "compound_return": asset.compound_return,
        "volatility": asset.volatility,
        "yield_": asset.yield_,
    }
    if with_origin:
        payload["origin"] = asset.origin
    if asset.is_custom:
        payload["asset_class"] = asset.asset_class
    if asset.notes:
        payload["notes"] = asset.notes
    return payload


def save_cmas(cmas: CMASet) -> Path:
    """Guarda la librería. Es la única fuente de verdad de los supuestos."""
    path = library_path()
    _write_atomic(
        path,
        {
            "schema": LIBRARY_SCHEMA_VERSION,
            "assets": [asset_to_dict(a) for a in cmas],
        },
    )
    return path


def reset_cmas_to_ltcma(keep_custom: bool = True) -> CMASet:
    """Vuelve a los supuestos del LTCMA.

    **Conserva los activos propios**, que no vienen del LTCMA: reimportarlo no
    puede ser motivo para borrarlos, y hacerlo dejaría casos guardados
    imposibles de abrir. Se borran solo uno a uno, desde su propio botón.

    Si al reimportar el LTCMA apareciera una clase nueva con el mismo nombre que
    un activo propio, gana el LTCMA y el propio se renombra: perder el supuesto
    del analista en silencio sería peor que un nombre feo.
    """
    cmas = seed_cmas()
    if not keep_custom:
        save_cmas(cmas)
        return cmas

    previos = load_cmas().custom if library_path().exists() else []
    for propio in previos:
        if propio.name in cmas.names:
            propio.name = f"{propio.name} (propio)"
        cmas.add(propio)

    save_cmas(cmas)
    return cmas


def delete_custom_asset(cmas: CMASet, name: str) -> Path:
    """Borra un activo propio de la librería. Los del LTCMA no se tocan."""
    asset = cmas.by_name(name)
    if not asset.is_custom:
        raise ValueError(
            f"'{name}' viene del LTCMA y no se puede borrar desde la app."
        )
    cmas.remove(name)
    return save_cmas(cmas)


def settings_path() -> Path:
    return app_data_dir() / SETTINGS_FILE


def load_settings() -> SimulationSettings:
    """Configuración general de la app (número de simulaciones, semilla, vista)."""
    path = settings_path()
    if not path.exists():
        return SimulationSettings()
    payload = json.loads(path.read_text(encoding="utf-8"))
    defaults = SimulationSettings()
    try:
        milestones = list(payload.get("milestone_years", defaults.milestone_years))
        if payload.get("schema", 1) < 2 and milestones == LEGACY_MILESTONES:
            milestones = list(defaults.milestone_years)

        return SimulationSettings(
            n_paths=int(payload.get("n_paths", defaults.n_paths)),
            seed=payload.get("seed", defaults.seed),
            milestone_years=milestones,
        )
    except (TypeError, ValueError):
        # Un archivo corrupto no debería impedir abrir la app.
        return defaults


def save_settings(settings: SimulationSettings) -> Path:
    path = settings_path()
    _write_atomic(path, {"schema": SCHEMA_VERSION, **asdict(settings)})
    return path


# --- Sesión anterior -------------------------------------------------------
# Al cerrar se guarda el caso en curso y al abrir se restaura, con la ruta del
# archivo si el caso venía de uno. No sustituye a guardar el caso: es una red
# para no perder lo cargado si la app se cierra antes de guardar.
SESSION_FILE = "last_session.json"


def session_path() -> Path:
    return app_data_dir() / SESSION_FILE


def save_session(scenario, case_path: Path | None = None) -> Path:
    """Guarda el caso en curso como sesión anterior."""
    from .caseio import to_dict

    path = session_path()
    _write_atomic(
        path,
        {"case_path": str(case_path) if case_path else None, **to_dict(scenario)},
    )
    return path


def load_session() -> tuple[object | None, Path | None]:
    """Devuelve `(escenario, ruta del caso)` de la sesión anterior, o `(None, None)`.

    Nunca levanta: una sesión ilegible es motivo para arrancar con el caso de
    ejemplo, no para impedir que la app abra.
    """
    from .caseio import CaseFormatError, from_dict

    path = session_path()
    if not path.exists():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        scenario = from_dict(payload)
    except (OSError, json.JSONDecodeError, CaseFormatError):
        return None, None

    raw = payload.get("case_path")
    case_path = Path(raw) if raw and Path(raw).exists() else None
    return scenario, case_path


def clear_session() -> None:
    session_path().unlink(missing_ok=True)


# --- Datos de portada del informe -----------------------------------------
# Quién prepara los informes no cambia de un caso a otro, así que se recuerda
# aparte: no es configuración de la simulación y no tiene nada que hacer dentro
# de `SimulationSettings`, ni dentro del caso del cliente.
REPORT_FILE = "report_defaults.json"

REPORT_FIELDS = ("author", "client", "title", "notes")


def report_defaults_path() -> Path:
    return app_data_dir() / REPORT_FILE


def load_report_defaults() -> dict:
    path = report_defaults_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: str(payload.get(k, "")) for k in REPORT_FIELDS if payload.get(k)}


def save_report_defaults(values: dict) -> Path:
    path = report_defaults_path()
    _write_atomic(path, {k: values.get(k, "") for k in REPORT_FIELDS})
    return path
