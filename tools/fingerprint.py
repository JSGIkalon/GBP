"""Huella exacta de las cifras del motor, para refactorizar sin mover un número.

Simula tres casos que juntos recorren todo el motor —el caso de ejemplo, uno
apalancado con llamadas a margen y uno con flujos porcentuales— y resume cada
matriz de resultado en un hash SHA-256 de sus bytes. Si una optimización cambia
aunque sea el último bit de un camino, el hash cambia.

    python tools/fingerprint.py           # compara contra tests/data/fingerprint.json
    python tools/fingerprint.py --write   # regenera la referencia

Regenerar la referencia solo es legítimo cuando un cambio **debe** mover las
cifras (una corrección del modelo), y eso se anota en el CHANGELOG.

Las llamadas a margen van en su propio grupo (`margin_calls`): son un conteo,
no un monto, y un arreglo de cómo se cuentan no toca el patrimonio.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gbp.engine.montecarlo import simulate  # noqa: E402
from gbp.io.library import seed_cmas  # noqa: E402
from gbp.model.allocation import Allocation  # noqa: E402
from gbp.model.cashflows import CashFlow, FlowBasis, FlowKind  # noqa: E402
from gbp.model.correlation import CorrelationMatrix  # noqa: E402
from gbp.model.leverage import Amortization, InterestMode, LoanTerms, RateMode  # noqa: E402
from gbp.model.scenario import Scenario, SimulationSettings  # noqa: E402
from gbp.model.strategy import Strategy  # noqa: E402
from gbp.ui.sample_case import BALANCED_30_PI, GROWTH_20_PI, build_sample_case  # noqa: E402

REFERENCE = ROOT / "tests" / "data" / "fingerprint.json"
MM = 1_000_000


def _leveraged_case() -> Scenario:
    loans = [
        LoanTerms(
            principal=12 * MM, start_year=2, term_years=8, rate_mode=RateMode.SPREAD_OVER_CASH,
            spread=0.02, interest_mode=InterestMode.CAPITALIZED,
            amortization=Amortization.FRENCH, max_ltv=0.55, target_ltv=0.45,
        ),
        LoanTerms(
            principal=8 * MM, start_year=1, term_years=10, rate=0.06,
            amortization=Amortization.LINEAR, max_ltv=0.5,
        ),
    ]
    return Scenario(
        name="Apalancado", initial_value=15 * MM, horizon=20, inflation=0.03,
        strategies=[
            Strategy(
                allocation=Allocation(f"Crédito {i + 1}", dict(GROWTH_20_PI)),
                cashflows=[CashFlow("Gasto", FlowKind.OUTFLOW, 0.9 * MM, 1, 20)],
                loan=loan,
            )
            for i, loan in enumerate(loans)
        ],
    )


def _percentage_case() -> Scenario:
    return Scenario(
        name="Porcentual", initial_value=10 * MM, horizon=25, inflation=0.02,
        strategies=[
            Strategy(
                allocation=Allocation("Endowment", dict(BALANCED_30_PI)),
                cashflows=[
                    CashFlow("Regla 4%", FlowKind.OUTFLOW, 0.04, 3, 25,
                             basis=FlowBasis.PORTFOLIO_PCT),
                    CashFlow("Aporte", FlowKind.INFLOW, 0.5 * MM, 1, 5, growth=0.01),
                    CashFlow("Aporte %", FlowKind.INFLOW, 0.01, 1, 10,
                             basis=FlowBasis.PORTFOLIO_PCT),
                ],
                initial_value=12 * MM,
            ),
        ],
    )


CASES = {
    "ejemplo": build_sample_case,
    "apalancado": _leveraged_case,
    "porcentual": _percentage_case,
}


def _digest(array) -> str:
    data = np.ascontiguousarray(np.asarray(array, dtype=float))
    return hashlib.sha256(data.tobytes()).hexdigest()[:20]


def compute(n_paths: int = 3000) -> dict:
    cmas = seed_cmas()
    correlations = CorrelationMatrix.load()
    settings = SimulationSettings(n_paths=n_paths, seed=42)
    out: dict = {"n_paths": n_paths, "cases": {}}
    for case_name, build in CASES.items():
        result = simulate(build(), cmas, correlations, settings)
        strategies = {}
        for s in result.strategies:
            strategies[s.name] = {
                "wealth": _digest(s.wealth),
                "debt": _digest(s.debt),
                "contributions": _digest(np.broadcast_to(s.contributions, s.wealth.shape)),
                "withdrawals": _digest(np.broadcast_to(s.withdrawals, s.wealth.shape)),
                "forced_sales": _digest(s.forced_sales),
                "success": s.success_probability,
                "median_final": float(np.median(s.wealth[:, -1])),
                "margin_calls": _digest(s.margin_calls),
            }
        out["cases"][case_name] = strategies
    return out


def compare(current: dict, reference: dict) -> list[str]:
    """Diferencias legibles entre dos huellas; vacía si coinciden."""
    diffs = []
    for case_name, strategies in reference["cases"].items():
        for name, ref in strategies.items():
            now = current["cases"].get(case_name, {}).get(name)
            if now is None:
                diffs.append(f"{case_name}/{name}: falta")
                continue
            for key, value in ref.items():
                if now.get(key) != value:
                    diffs.append(f"{case_name}/{name}/{key}: {value} -> {now.get(key)}")
    return diffs


def main() -> int:
    current = compute()
    if "--write" in sys.argv:
        REFERENCE.parent.mkdir(parents=True, exist_ok=True)
        REFERENCE.write_text(json.dumps(current, indent=2), encoding="utf-8")
        print(f"Referencia escrita en {REFERENCE}")
        return 0
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    diffs = compare(current, reference)
    if diffs:
        print("Las cifras cambiaron:")
        print("\n".join(f"  {d}" for d in diffs))
        return 1
    print("Cifras idénticas a la referencia.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
