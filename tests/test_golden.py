import json
from decimal import Decimal
from pathlib import Path

import pytest

from engine.quote import build_quote

GOLDEN_DIR = Path(__file__).parent / "golden"
CASES = sorted(GOLDEN_DIR.glob("*.json"))


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_golden_case(path):
    case = json.loads(path.read_text())
    result = build_quote(case["recipe"], case["parameters"], case["client"])
    expected = case["expected"]

    assert result.totals.low == Decimal(expected["low"]), (
        f"{path.stem}: low moved from {expected['low']} to {result.totals.low}. "
        "If this change is intended, run uv run python -m scripts.update_golden and review the diff."
    )
    assert result.totals.high == Decimal(expected["high"]), (
        f"{path.stem}: high moved from {expected['high']} to {result.totals.high}. "
        "If this change is intended, run uv run python -m scripts.update_golden and review the diff."
    )
    assert result.totals.labour_cost == Decimal(expected["labour_cost"]), (
        f"{path.stem}: labour_cost moved from {expected['labour_cost']} to "
        f"{result.totals.labour_cost}. If this change is intended, run "
        "uv run python -m scripts.update_golden and review the diff."
    )
    assert result.totals.material_cost == Decimal(expected["material_cost"]), (
        f"{path.stem}: material_cost moved from {expected['material_cost']} to "
        f"{result.totals.material_cost}. If this change is intended, run "
        "uv run python -m scripts.update_golden and review the diff."
    )
    assert result.totals.plant_cost == Decimal(expected["plant_cost"]), (
        f"{path.stem}: plant_cost moved from {expected['plant_cost']} to "
        f"{result.totals.plant_cost}. If this change is intended, run "
        "uv run python -m scripts.update_golden and review the diff."
    )
    assert result.totals.gross == Decimal(expected["gross"]), (
        f"{path.stem}: gross moved from {expected['gross']} to "
        f"{result.totals.gross}. If this change is intended, run "
        "uv run python -m scripts.update_golden and review the diff."
    )


def test_at_least_four_golden_cases_exist():
    assert len(CASES) >= 4


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_golden_case_pins_every_parameter(path):
    """A case that leans on a recipe default breaks confusingly when the default moves."""
    case = json.loads(path.read_text())
    result = build_quote(case["recipe"], case["parameters"], case["client"])
    assert set(case["parameters"]) == set(result.parameters), (
        f"{path.stem}: golden cases must state every recipe parameter explicitly; "
        f"missing {sorted(set(result.parameters) - set(case['parameters']))}"
    )
