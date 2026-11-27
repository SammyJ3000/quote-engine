"""validate_setup is the pre-demo smoke test: it must find every gap in a new
client skin at once, not stop at the first one."""

import json

import pytest

from engine.catalogue import load_catalogue
from engine.clientconfig import load_client
from engine.prices import load_price_book
from engine.recipes import load_recipe
from engine.validate import validate_setup

CATALOGUE = """
- id: tile-mid
  name: Tile mid
  unit: m2
  category: finishes
  tiers: { budget: tile-budget, premium: tile-premium }
- id: tile-budget
  name: Tile budget
  unit: m2
  category: finishes
- id: tile-premium
  name: Tile premium
  unit: m2
  category: finishes
- id: skip-6yd
  name: Skip
  unit: each
  category: plant
  discrete: true
"""

RECIPE = """
id: test-job
label: Test job
parameters:
  - { id: area_m2, type: number, min: 1.0, max: 60.0 }
  - { id: spec_tier, type: enum, values: [budget, mid, premium] }
tasks:
  - id: strip_out
    label: Strip out
    trade: labourer
    days: 0.5
    materials:
      - { sku: skip-6yd, qty: 1 }
  - id: tiling
    label: Tiling
    trade: tiler
    days: 1
    materials:
      - { sku: tile-mid, qty: area_m2, tier: spec_tier }
  - id: grouting
    label: Grouting
    trade: tiler
    days: 0.5
"""

ALL_PRICES = {
    "tile-mid": 24.99,
    "tile-budget": 14.99,
    "tile-premium": 44.99,
    "skip-6yd": 240.0,
}


@pytest.fixture
def catalogue(tmp_path):
    path = tmp_path / "materials.yaml"
    path.write_text(CATALOGUE)
    return load_catalogue(path)


@pytest.fixture
def recipe(tmp_path, catalogue):
    path = tmp_path / "test-job.yaml"
    path.write_text(RECIPE)
    return load_recipe(path, catalogue)


def _book(tmp_path, prices=None, name="2026-08-21.json"):
    prices = ALL_PRICES if prices is None else prices
    path = tmp_path / name
    path.write_text(
        json.dumps(
            {
                "captured": "2026-08-21",
                "prices": {
                    sku: (
                        price
                        if isinstance(price, dict)
                        else {"list": price, "unit": "each", "source": "x", "method": "hand"}
                    )
                    for sku, price in prices.items()
                },
            }
        )
    )
    return load_price_book(path)


def _client(tmp_path, labour="labourer: 130\ntiler: 220\n", name="acme-bathrooms"):
    d = tmp_path / name
    d.mkdir()
    (d / "labour.yaml").write_text(labour)
    (d / "discounts.yaml").write_text("default: 0.15\n")
    (d / "commercial.yaml").write_text("overhead_margin: 0.22\n")
    return load_client(d)


def test_a_complete_setup_reports_no_problems(recipe, catalogue, tmp_path):
    assert validate_setup(recipe, _client(tmp_path), _book(tmp_path), catalogue) == []


def test_missing_day_rate_is_reported_with_trade_and_client(recipe, catalogue, tmp_path):
    client = _client(tmp_path, labour="labourer: 130\n")
    problems = validate_setup(recipe, client, _book(tmp_path), catalogue)
    assert len(problems) == 1
    assert "tiler" in problems[0] and "acme-bathrooms" in problems[0]


def test_a_trade_is_reported_once_naming_every_task_that_needs_it(recipe, catalogue, tmp_path):
    client = _client(tmp_path, labour="labourer: 130\n")
    problems = validate_setup(recipe, client, _book(tmp_path), catalogue)
    assert "tiling" in problems[0] and "grouting" in problems[0]


def test_an_unpriced_tier_variant_is_reported(recipe, catalogue, tmp_path):
    prices = {k: v for k, v in ALL_PRICES.items() if k != "tile-premium"}
    problems = validate_setup(recipe, _client(tmp_path), _book(tmp_path, prices), catalogue)
    assert len(problems) == 1
    assert "tile-premium" in problems[0]


def test_a_malformed_price_entry_is_reported_not_raised(recipe, catalogue, tmp_path):
    # An entry that exists but carries no list price used to be a bare KeyError.
    book = _book(tmp_path, dict(ALL_PRICES, **{"skip-6yd": {"unit": "each"}}))
    problems = validate_setup(recipe, _client(tmp_path), book, catalogue)
    assert len(problems) == 1
    assert "skip-6yd" in problems[0]


def test_every_gap_is_reported_not_just_the_first(recipe, catalogue, tmp_path):
    client = _client(tmp_path, labour="labourer: 130\n")
    prices = {k: v for k, v in ALL_PRICES.items() if k not in ("tile-premium", "skip-6yd")}
    problems = validate_setup(recipe, client, _book(tmp_path, prices), catalogue)
    joined = "\n".join(problems)
    assert len(problems) == 3, joined
    assert "tiler" in joined and "tile-premium" in joined and "skip-6yd" in joined
