"""Regenerate expected totals in tests/golden/*.json.

This is a maintenance tool, not a test. It records what the engine currently
does — it does NOT verify that what the engine does is correct. If a regenerated
number looks wrong, the fault is in the recipe or the price book, and that is
what you fix; never paper over it by re-recording the golden file.

Run this ONLY after deliberately changing a formula, a price or a client
setting, and always read the diff before committing.
"""

import json
from pathlib import Path

from engine.quote import build_quote

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "tests" / "golden"


def main() -> int:
    for path in sorted(GOLDEN_DIR.glob("*.json")):
        case = json.loads(path.read_text())
        totals = build_quote(case["recipe"], case["parameters"], case["client"]).totals
        case["expected"] = {
            "low": str(totals.low),
            "high": str(totals.high),
            "labour_cost": str(totals.labour_cost),
            "material_cost": str(totals.material_cost),
            "plant_cost": str(totals.plant_cost),
            "gross": str(totals.gross),
        }
        path.write_text(json.dumps(case, indent=2) + "\n")
        print(f"{path.stem}: £{totals.low} – £{totals.high}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
