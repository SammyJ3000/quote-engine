import itertools
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from engine.catalogue import load_catalogue
from engine.clientconfig import load_client
from engine.prices import latest_price_book
from engine.quantify import build_namespace, quantify, resolve_parameters
from engine.recipes import load_recipe
from engine.validate import validate_setup

ROOT = Path(__file__).resolve().parent.parent

# Loaded at import time so the enum sweep below can be parametrised at collection.
_CATALOGUE = load_catalogue(ROOT / "catalogue" / "materials.yaml")
_RECIPE = load_recipe(ROOT / "recipes" / "bathroom-refit.yaml", _CATALOGUE)


@pytest.fixture(scope="module")
def catalogue():
    return _CATALOGUE


@pytest.fixture(scope="module")
def book():
    return latest_price_book(ROOT / "data" / "pricebook")


@pytest.fixture(scope="module")
def recipe():
    return _RECIPE


@pytest.fixture(scope="module")
def client():
    return load_client(ROOT / "clients" / "demo-nw")


def test_recipe_loads(recipe):
    assert recipe.id == "bathroom-refit"
    assert len(recipe.tasks) >= 12


def test_every_catalogue_sku_has_a_price(catalogue, book):
    assert [s for s in catalogue.ids() if s not in book] == []


def test_the_shipped_setup_has_no_gaps(recipe, client, book, catalogue):
    """Every trade has a day rate and every SKU — tier variants included — has a
    price. Same check `--check` runs on a new client skin before a demo."""
    assert validate_setup(recipe, client, book, catalogue) == []


def test_number_parameters_are_bounded(recipe):
    """Every number parameter, defaulted or not. An unbounded field is what a
    mis-transcribed '2.4 metres' drives a 10x quote through."""
    for param in recipe.parameters:
        if param.type == "number":
            assert param.min is not None and param.max is not None, param.id


def test_enum_parameters_declare_values(recipe):
    for param in recipe.parameters:
        if param.type == "enum":
            assert param.values, param.id


# --- Invariants the price and discount lookups depend on -------------------

def test_every_sku_category_is_one_the_discount_matrix_knows(catalogue):
    """A typo'd category silently falls back to the default discount: wrong price, no error."""
    discounts = yaml.safe_load((ROOT / "clients" / "demo-nw" / "discounts.yaml").read_text())
    known = set(discounts["by_category"])
    offenders = [
        (sku_id, catalogue.get(sku_id).category)
        for sku_id in catalogue.ids()
        if catalogue.get(sku_id).category not in known
    ]
    assert offenders == [], f"categories not in {sorted(known)}"


def test_every_by_coverage_material_resolves_to_a_sku_with_coverage(recipe, catalogue):
    """`by_coverage` divides by the SKU's coverage; a SKU without one fails at quantify time."""
    offenders = []
    for task in recipe.tasks:
        for material in task.materials:
            if not material.by_coverage:
                continue
            base = catalogue.get(material.sku)
            for sku_id in [base.id, *base.tiers.values()]:
                coverage = catalogue.get(sku_id).coverage_per_unit
                if coverage is None or coverage <= 0:
                    offenders.append((task.id, sku_id, coverage))
    assert offenders == []


# --- The recipe must not merely load; it must quantify ---------------------

_ENUMS = {p.id: p.values for p in _RECIPE.parameters if p.type == "enum"}
_ENUM_COMBOS = [
    dict(zip(_ENUMS, values, strict=True)) for values in itertools.product(*_ENUMS.values())
]
# The declared bounds, not a comfortable middle: 1.2 and 6.0 are what the
# dropdowns allow. None for openings means "omit it", exercising the default.
_ROOM_SIZES = ((1.2, 1.2), (6.0, 6.0))
_OPENINGS = (None, 6.0)
# 2 * (1.2 + 1.2) * 2.0 - 10 = -0.4 before max(0, ...), so this case is the one
# that reaches the clamp in wall_area_m2.
_CLAMPED = {"length_m": 1.2, "width_m": 1.2, "height_m": 2.0, "openings_m2": 10.0}


@pytest.mark.parametrize(
    "enums",
    _ENUM_COMBOS,
    ids=["-".join(combo.values()) for combo in _ENUM_COMBOS],
)
def test_every_parameter_combination_quantifies(recipe, catalogue, enums):
    """Every enum combination, at several room sizes and opening allowances, must produce
    a costable set of tasks with no negative day or quantity anywhere."""
    cases = []
    for (length_m, width_m), openings_m2 in itertools.product(_ROOM_SIZES, _OPENINGS):
        case = {"length_m": length_m, "width_m": width_m}
        if openings_m2 is not None:
            case["openings_m2"] = openings_m2
        cases.append(case)
    cases.append(dict(_CLAMPED))

    for case in cases:
        supplied = {**case, **enums}

        params = resolve_parameters(recipe, supplied)
        tasks = quantify(recipe, params, catalogue)

        assert tasks, f"no tasks produced for {supplied}"
        for task in tasks:
            assert task.days >= 0, f"{task.id} days {task.days} for {supplied}"
            for material in task.materials:
                assert material.raw_qty >= 0, f"{task.id}/{material.sku.id} for {supplied}"
                assert material.units >= 0, f"{task.id}/{material.sku.id} for {supplied}"


def test_wall_area_is_clamped_at_zero_not_negative(recipe):
    """More openings than wall: max(0, ...) must hold, or every wall quantity
    downstream — board, tiles, plaster, paint — goes negative."""
    params = resolve_parameters(recipe, _CLAMPED | {
        "spec_tier": "mid", "shower_type": "over-bath", "tiling_extent": "half-height",
        "layout_change": "none", "floor_type": "tile",
    })
    namespace = build_namespace(recipe, params)
    assert namespace["wall_area_m2"] == 0


def test_exact_coverage_does_not_buy_an_extra_tin_of_paint(recipe, catalogue):
    """A 2.0 x 1.8 room, 2.5m high, half-height tiled leaves exactly 12.0 m2 to
    paint against a 12.0 m2 tin. Float noise used to make that 12.000000000000002
    and ceil() turned it into a second tin."""
    params = resolve_parameters(recipe, {
        "length_m": 2.0, "width_m": 1.8, "height_m": 2.5,
        "spec_tier": "mid", "shower_type": "over-bath", "tiling_extent": "half-height",
        "layout_change": "none", "floor_type": "lvt",
    })
    tasks = {t.id: t for t in quantify(recipe, params, catalogue)}
    paint = tasks["decorating"].materials[0]

    assert paint.sku.id == "paint-bathroom-2_5l"
    assert paint.raw_qty == Decimal("12")
    assert paint.units == Decimal("1")
