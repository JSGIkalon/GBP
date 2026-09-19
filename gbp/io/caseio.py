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
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from ..model.allocation import Allocation
from ..model.cashflows import CashFlow, FlowKind
from ..model.leverage import Amortization, InterestMode, LoanTerms, RateMode
from ..model.scenario import Scenario
from ..model.strategy import Strategy

SCHEMA_VERSION = 2
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
    )


def to_dict(scenario: Scenario) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "scenario": {
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
        },
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


def save_case(scenario: Scenario, path: str | Path) -> Path:
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(to_dict(scenario), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    tmp.replace(path)
    return path


def load_case(path: str | Path) -> Scenario:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CaseFormatError(f"El archivo no es un JSON válido: {exc}") from exc
    return from_dict(payload)
