"""Guardado y carga de casos de cliente en JSON.

El caso guarda **solo el escenario del cliente**: capital, horizonte, inflación y
las estrategias con sus flujos y su crédito. Los supuestos de mercado no van
aquí: viven en la librería global (`gbp.io.library`), para que editarlos no
obligue a tocar cada caso y para que abrir un caso viejo no pise los supuestos
vigentes.

El archivo lleva número de esquema y las versiones antiguas se migran en vez de
rechazarse:

* **Esquema 1** — los flujos y el crédito eran del escenario y los compartían
  todas las estrategias. Al abrirlo se copian a cada estrategia, que es
  exactamente la semántica que tenían.
* **Esquema 2** — cada estrategia lleva los suyos, más un capital inicial propio
  opcional.
* **Esquema 3** — el caso lleva además los **activos propios** que usa.
* **Esquema 4** — cada flujo lleva su `basis`: monto fijo o porcentaje del
  patrimonio. Un caso viejo no trae el campo y se lee como monto fijo, que es lo
  único que existía. El número sube aunque el caso no use flujos porcentuales
  porque una versión anterior de la app ignoraría el campo en silencio y
  simularía un retiro de 4 unidades donde el caso dice 4%; mejor que se niegue a
  abrirlo y pida actualizar.

Por qué los activos propios sí van en el caso
---------------------------------------------
Los supuestos del LTCMA no viajan porque son idénticos en todas las máquinas:
son un recurso embebido y versionado. Los activos propios no tienen esa
garantía —los declara cada analista— así que un caso que los usara sin
llevarlos consigo no se podría abrir en otro computador. Se guardan **solo los
que el caso usa**: copiar la librería entera sería justo el error que este
módulo evita a propósito.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from ..model.allocation import Allocation
from ..model.cashflows import CashFlow, FlowBasis, FlowKind
from ..model.leverage import Amortization, InterestMode, LoanTerms, RateMode
from ..model.scenario import Scenario
from ..model.strategy import Strategy

SCHEMA_VERSION = 4
EXTENSION = ".gbp.json"


class CaseFormatError(ValueError):
    """El archivo no es un caso de GBP o está dañado."""


def _loan_to_dict(loan: LoanTerms) -> dict:
    return {
        "name": loan.name,
        "principal": loan.principal,
        "start_year": loan.start_year,
        "term_years": loan.term_years,
        "rate_mode": loan.rate_mode.value,
        "rate": loan.rate,
        "spread": loan.spread,
        "interest_mode": loan.interest_mode.value,
        "amortization": loan.amortization.value,
        "max_ltv": loan.max_ltv,
        "target_ltv": loan.target_ltv,
    }


def _loan_from_dict(payload: dict) -> LoanTerms:
    return LoanTerms(
        name=payload.get("name", "Crédito"),
        principal=float(payload.get("principal", 0.0)),
        start_year=int(payload.get("start_year", 1)),
        term_years=int(payload.get("term_years", 10)),
        rate_mode=RateMode(payload.get("rate_mode", RateMode.FIXED.value)),
        rate=float(payload.get("rate", 0.05)),
        spread=float(payload.get("spread", 0.015)),
        interest_mode=InterestMode(payload.get("interest_mode", InterestMode.PAID.value)),
        amortization=Amortization(payload.get("amortization", Amortization.BULLET.value)),
        max_ltv=payload.get("max_ltv"),
        target_ltv=payload.get("target_ltv"),
    )


def _flow_to_dict(flow: CashFlow) -> dict:
    return {
        "name": flow.name,
        "kind": flow.kind.value,
        "amount": flow.amount,
        "start_year": flow.start_year,
        "end_year": flow.end_year,
        "inflation_indexed": flow.inflation_indexed,
        "growth": flow.growth,
        "basis": flow.basis.value,
    }


def _flow_from_dict(payload: dict) -> CashFlow:
    return CashFlow(
        name=payload["name"],
        kind=FlowKind(payload["kind"]),
        amount=float(payload["amount"]),
        start_year=int(payload["start_year"]),
        end_year=int(payload["end_year"]),
        inflation_indexed=bool(payload.get("inflation_indexed", True)),
        growth=float(payload.get("growth", 0.0)),
        basis=FlowBasis(payload.get("basis", FlowBasis.AMOUNT.value)),
    )


def to_dict(scenario: Scenario, cmas=None) -> dict:
    """Forma serializada del caso.

    Si se pasa la librería, se embeben los activos propios que el caso usa, para
    que se pueda abrir en otro computador.
    """
    payload: dict = {
        "schema": SCHEMA_VERSION,
    }
    if cmas is not None:
        propios = _used_custom_assets(scenario, cmas)
        if propios:
            payload["custom_assets"] = propios
    payload["scenario"] = _scenario_to_dict(scenario)
    return payload


def _used_custom_assets(scenario: Scenario, cmas) -> list[dict]:
    """Activos propios que alguna estrategia usa, con sus supuestos."""
    from .library import asset_to_dict

    usados = []
    for name in scenario.asset_names:
        try:
            asset = cmas.by_name(name)
        except KeyError:
            continue
        if asset.is_custom:
            # Sin `origin`: aquí todos son propios por definición.
            usados.append(asset_to_dict(asset, with_origin=False))
    return usados


def custom_assets_from_dict(payload: dict) -> list:
    """Activos propios embebidos en un caso.

    Función hermana de `from_dict` en vez de un segundo valor de retorno: hacer
    que `from_dict` devolviera una tupla rompería a todos sus llamadores, entre
    ellos la restauración de sesión.
    """
    from ..model.assets import ORIGIN_CUSTOM
    from .library import asset_from_dict

    return [
        asset_from_dict({**entry, "origin": ORIGIN_CUSTOM})
        for entry in payload.get("custom_assets", [])
    ]


def _scenario_to_dict(scenario: Scenario) -> dict:
    return {
        "name": scenario.name,
        "initial_value": scenario.initial_value,
        "horizon": scenario.horizon,
        "inflation": scenario.inflation,
        "strategies": [
            {
                "name": s.name,
                "weights": dict(s.weights),
                "cashflows": [_flow_to_dict(f) for f in s.cashflows],
                "loan": _loan_to_dict(s.loan) if s.loan else None,
                "initial_value": s.initial_value,
            }
            for s in scenario.strategies
        ],
    }


def from_dict(payload: dict) -> Scenario:
    if "scenario" not in payload:
        raise CaseFormatError("El archivo no tiene la estructura de un caso de GBP.")

    schema = payload.get("schema", 0)
    if schema > SCHEMA_VERSION:
        raise CaseFormatError(
            f"El caso fue guardado con una versión más nueva de la app (esquema {schema}). "
            "Actualiza GBP para abrirlo."
        )

    data = payload["scenario"]
    try:
        if schema <= 1:
            strategies = _strategies_from_schema_1(data)
        else:
            strategies = [
                Strategy(
                    allocation=Allocation(
                        s["name"], {k: float(v) for k, v in s["weights"].items()}
                    ),
                    cashflows=[_flow_from_dict(f) for f in s.get("cashflows", [])],
                    loan=_loan_from_dict(s["loan"]) if s.get("loan") else None,
                    initial_value=(
                        float(s["initial_value"])
                        if s.get("initial_value") is not None
                        else None
                    ),
                )
                for s in data.get("strategies", [])
            ]

        return Scenario(
            name=data.get("name", "Caso sin título"),
            initial_value=float(data.get("initial_value", 0.0)),
            horizon=int(data.get("horizon", 30)),
            inflation=float(data.get("inflation", 0.025)),
            strategies=strategies,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CaseFormatError(f"El caso está dañado o incompleto: {exc}") from exc


def _strategies_from_schema_1(data: dict) -> list[Strategy]:
    """Migra un caso del esquema 1, donde flujos y crédito eran del escenario.

    Los compartían todas las estrategias, así que se copian a cada una —por
    valor, para que editar una no toque a las demás—. El resultado simula
    exactamente igual que el caso original.
    """
    shared_flows = [_flow_from_dict(f) for f in data.get("cashflows", [])]
    shared_loan = data.get("loan")

    return [
        Strategy(
            allocation=Allocation(a["name"], {k: float(v) for k, v in a["weights"].items()}),
            cashflows=[deepcopy(f) for f in shared_flows],
            loan=_loan_from_dict(shared_loan) if shared_loan else None,
            initial_value=None,
        )
        for a in data.get("allocations", [])
    ]


def save_case(scenario: Scenario, path: str | Path, cmas=None) -> Path:
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(to_dict(scenario, cmas), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(path)
    return path


def read_case(path: str | Path) -> dict:
    """El JSON crudo del caso, para quien necesite también los activos propios."""
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CaseFormatError(f"El archivo no es un JSON válido: {exc}") from exc


def load_case(path: str | Path) -> Scenario:
    return from_dict(read_case(path))
