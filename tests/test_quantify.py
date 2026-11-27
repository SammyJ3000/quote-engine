from decimal import Decimal

import pytest

from engine.catalogue import load_catalogue
from engine.errors import ParameterError, RecipeError
from engine.quantify import build_namespace, quantify, resolve_parameters
from engine.recipes import load_recipe

CATALOGUE = """
- id: tile-mid
  name: Tile mid
  unit: m2
  category: finishes
  tiers: { premium: tile-premium }
- id: tile-premium
  name: Tile premium
  unit: m2
  category: finishes
- id: adhesive-20kg
  name: Adhesive 20kg
  unit: bag
  category: finishes
  discrete: true
  coverage: { unit: m2, per_unit: 4.5 }
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
  - { id: length_m, type: number, min: 1.0, max: 6.0 }
  - { id: width_m, type: number, min: 1.0, max: 6.0 }
  - { id: spec_tier, type: enum, values: [budget, mid, premium] }
  - { id: shower_type, type: enum, values: [over-bath, walk-in] }
  - { id: height_m, type: number, default: 2.4 }
constants:
  wall_factor: { budget: 0.5, mid: 1.0, premium: 1.0 }
derived:
  floor_area_m2: length_m * width_m
  tiled_area_m2: 2 * (length_m + width_m) * height_m * wall_factor[spec_tier]
tasks:
  - id: strip_out
    label: Strip out
    trade: labourer
    days: 0.5
    materials:
      - { sku: skip-6yd, qty: 1 }
  - id: tanking
    label: Tanking
    trade: tiler
    when: shower_type != 'over-bath'
    days: 0.5
  - id: tiling
    label: Tiling
    trade: tiler
    days: tiled_area_m2 / 6
    materials:
      - { sku: tile-mid, qty: tiled_area_m2, waste: 0.10, tier: spec_tier }
      - { sku: adhesive-20kg, qty: tiled_area_m2, by_coverage: true }
"""

BASE = {
    "length_m": 2.4,
    "width_m": 1.8,
    "spec_tier": "mid",
    "shower_type": "walk-in",
}


@pytest.fixture
def catalogue(tmp_path):
    p = tmp_path / "materials.yaml"
    p.write_text(CATALOGUE)
    return load_catalogue(p)


@pytest.fixture
def recipe(tmp_path, catalogue):
    p = tmp_path / "test-job.yaml"
    p.write_text(RECIPE)
    return load_recipe(p, catalogue)


def test_defaults_are_applied(recipe):
    assert resolve_parameters(recipe, BASE)["height_m"] == 2.4


def test_missing_required_parameter_raises(recipe):
    with pytest.raises(ParameterError) as exc:
        resolve_parameters(recipe, {"length_m": 2.4})
    assert "width_m" in str(exc.value)


def test_number_out_of_range_raises(recipe):
    with pytest.raises(ParameterError) as exc:
        resolve_parameters(recipe, BASE | {"length_m": 99})
    assert "length_m" in str(exc.value)


def test_enum_outside_allowed_values_raises(recipe):
    with pytest.raises(ParameterError) as exc:
        resolve_parameters(recipe, BASE | {"spec_tier": "gold"})
    assert "gold" in str(exc.value)


def test_unknown_parameter_raises(recipe):
    with pytest.raises(ParameterError) as exc:
        resolve_parameters(recipe, BASE | {"colour": "blue"})
    assert "colour" in str(exc.value)


def test_derived_values_compute(recipe):
    ns = build_namespace(recipe, resolve_parameters(recipe, BASE))
    assert ns["floor_area_m2"] == pytest.approx(4.32)
    # 2 * (2.4 + 1.8) * 2.4 * 1.0
    assert ns["tiled_area_m2"] == pytest.approx(20.16)


def test_when_false_drops_the_task(recipe, catalogue):
    params = resolve_parameters(recipe, BASE | {"shower_type": "over-bath"})
    tasks = quantify(recipe, params, catalogue)
    assert "tanking" not in {t.id for t in tasks}


def test_when_true_keeps_the_task(recipe, catalogue):
    tasks = quantify(recipe, resolve_parameters(recipe, BASE), catalogue)
    assert "tanking" in {t.id for t in tasks}


def test_days_are_decimal(recipe, catalogue):
    tasks = {t.id: t for t in quantify(recipe, resolve_parameters(recipe, BASE), catalogue)}
    # Decimal("5") == 5.0 is True, so the value alone would not catch a float
    # regression here — and money must never be multiplied by a float.
    assert isinstance(tasks["tiling"].days, Decimal)
    assert isinstance(tasks["strip_out"].days, Decimal)
    assert tasks["tiling"].days == pytest.approx(Decimal("3.36"), abs=Decimal("0.01"))


def test_waste_is_applied(recipe, catalogue):
    tasks = {t.id: t for t in quantify(recipe, resolve_parameters(recipe, BASE), catalogue)}
    tile = tasks["tiling"].materials[0]
    assert isinstance(tile.raw_qty, Decimal) and isinstance(tile.units, Decimal)
    assert tile.raw_qty == pytest.approx(Decimal("20.16"), abs=Decimal("0.01"))
    assert tile.units == pytest.approx(Decimal("22.176"), abs=Decimal("0.01"))


def test_coverage_converts_to_whole_bags(recipe, catalogue):
    tasks = {t.id: t for t in quantify(recipe, resolve_parameters(recipe, BASE), catalogue)}
    adhesive = tasks["tiling"].materials[1]
    # 20.16 m2 / 4.5 m2 per bag = 4.48 -> 5 bags
    assert isinstance(adhesive.units, Decimal)
    assert adhesive.units == Decimal("5")


def test_tier_swaps_the_sku(recipe, catalogue):
    params = resolve_parameters(recipe, BASE | {"spec_tier": "premium"})
    tasks = {t.id: t for t in quantify(recipe, params, catalogue)}
    assert tasks["tiling"].materials[0].sku.id == "tile-premium"


# --- behaviour beyond the brief's twelve -------------------------------------


def _recipe_from(tmp_path, catalogue, text, name="extra"):
    p = tmp_path / f"{name}.yaml"
    p.write_text(text)
    return load_recipe(p, catalogue)


def _one_task_recipe(body: str, parameters: str = "  - { id: area_m2, type: number }") -> str:
    return f"""
id: extra
label: Extra
parameters:
{parameters}
tasks:
  - id: only
    label: Only
    trade: tiler
{body}
"""


def test_task_without_materials_resolves_to_an_empty_tuple(recipe, catalogue):
    tasks = {t.id: t for t in quantify(recipe, resolve_parameters(recipe, BASE), catalogue)}
    assert tasks["tanking"].materials == ()


def test_discrete_sku_rounds_up_to_a_whole_unit(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe(
            """    days: 1
    materials:
      - { sku: skip-6yd, qty: area_m2 }"""
        ),
        name="discrete",
    )
    tasks = quantify(r, resolve_parameters(r, {"area_m2": 0.6}), catalogue)
    assert tasks[0].materials[0].units == Decimal("1")
    assert tasks[0].materials[0].raw_qty == Decimal("0.6")


def test_waste_is_applied_before_the_coverage_division(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe(
            """    days: 1
    materials:
      - { sku: adhesive-20kg, qty: area_m2, waste: 0.10, by_coverage: true }"""
        ),
        name="waste-order",
    )
    # 4.5 * 1.10 = 4.95 -> one bag if waste came after the division, two because it comes first.
    tasks = quantify(r, resolve_parameters(r, {"area_m2": 4.5}), catalogue)
    assert tasks[0].materials[0].units == Decimal("2")


def test_by_coverage_without_coverage_raises(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe(
            """    days: 1
    materials:
      - { sku: tile-mid, qty: area_m2, by_coverage: true }"""
        ),
        name="no-coverage",
    )
    with pytest.raises(RecipeError) as exc:
        quantify(r, resolve_parameters(r, {"area_m2": 5}), catalogue)
    assert "tile-mid" in str(exc.value)


def test_by_coverage_with_zero_coverage_raises(tmp_path):
    cat_path = tmp_path / "zero-coverage.yaml"
    cat_path.write_text(
        """
- id: dust-20kg
  name: Dust
  unit: bag
  category: finishes
  discrete: true
  coverage: { unit: m2, per_unit: 0 }
"""
    )
    zero_catalogue = load_catalogue(cat_path)
    r = _recipe_from(
        tmp_path,
        zero_catalogue,
        _one_task_recipe(
            """    days: 1
    materials:
      - { sku: dust-20kg, qty: area_m2, by_coverage: true }"""
        ),
        name="zero-coverage-recipe",
    )
    with pytest.raises(RecipeError) as exc:
        quantify(r, resolve_parameters(r, {"area_m2": 5}), zero_catalogue)
    assert "dust-20kg" in str(exc.value)


def test_negative_waste_raises(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe(
            """    days: 1
    materials:
      - { sku: tile-mid, qty: area_m2, waste: -0.10 }"""
        ),
        name="negative-waste",
    )
    with pytest.raises(RecipeError) as exc:
        quantify(r, resolve_parameters(r, {"area_m2": 5}), catalogue)
    assert "tile-mid" in str(exc.value)


def test_negative_quantity_raises(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe(
            """    days: 1
    materials:
      - { sku: tile-mid, qty: area_m2 - 10 }"""
        ),
        name="negative-qty",
    )
    with pytest.raises(RecipeError) as exc:
        quantify(r, resolve_parameters(r, {"area_m2": 5}), catalogue)
    assert "tile-mid" in str(exc.value)


def test_non_numeric_quantity_raises(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe(
            """    days: 1
    materials:
      - { sku: tile-mid, qty: "'lots'" }"""
        ),
        name="text-qty",
    )
    with pytest.raises(RecipeError) as exc:
        quantify(r, resolve_parameters(r, {"area_m2": 5}), catalogue)
    assert "tile-mid" in str(exc.value)


def test_negative_days_raises(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe("""    days: area_m2 - 10"""),
        name="negative-days",
    )
    with pytest.raises(RecipeError) as exc:
        quantify(r, resolve_parameters(r, {"area_m2": 5}), catalogue)
    assert "only" in str(exc.value)


def test_non_boolean_when_raises(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe(
            """    when: area_m2
    days: 1"""
        ),
        name="truthy-when",
    )
    with pytest.raises(RecipeError) as exc:
        quantify(r, resolve_parameters(r, {"area_m2": 5}), catalogue)
    assert "only" in str(exc.value)


def test_tier_from_an_undeclared_parameter_raises(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe(
            """    days: 1
    materials:
      - { sku: tile-mid, qty: area_m2, tier: finish_level }"""
        ),
        name="unknown-tier-param",
    )
    with pytest.raises(RecipeError) as exc:
        quantify(r, resolve_parameters(r, {"area_m2": 5}), catalogue)
    assert "finish_level" in str(exc.value)


def test_tier_from_a_non_text_parameter_raises(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe(
            """    days: 1
    materials:
      - { sku: tile-mid, qty: area_m2, tier: area_m2 }"""
        ),
        name="numeric-tier-param",
    )
    with pytest.raises(RecipeError) as exc:
        quantify(r, resolve_parameters(r, {"area_m2": 5}), catalogue)
    assert "area_m2" in str(exc.value)


def test_unmapped_tier_falls_back_to_the_base_sku(recipe, catalogue):
    params = resolve_parameters(recipe, BASE | {"spec_tier": "budget"})
    tasks = {t.id: t for t in quantify(recipe, params, catalogue)}
    assert tasks["tiling"].materials[0].sku.id == "tile-mid"


def test_boolean_parameter_is_accepted(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe(
            """    when: underfloor
    days: 1""",
            parameters="  - { id: underfloor, type: boolean }",
        ),
        name="boolean-param",
    )
    assert resolve_parameters(r, {"underfloor": False})["underfloor"] is False
    assert quantify(r, resolve_parameters(r, {"underfloor": False}), catalogue) == ()
    assert len(quantify(r, resolve_parameters(r, {"underfloor": True}), catalogue)) == 1


def test_quoted_boolean_parameter_raises(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe(
            """    days: 1""",
            parameters="  - { id: underfloor, type: boolean }",
        ),
        name="quoted-boolean",
    )
    with pytest.raises(ParameterError) as exc:
        resolve_parameters(r, {"underfloor": "false"})
    assert "underfloor" in str(exc.value)


def test_numeric_string_is_accepted_for_a_number(recipe):
    assert resolve_parameters(recipe, BASE | {"length_m": "2.4"})["length_m"] == 2.4


def test_boolean_is_rejected_for_a_number(recipe):
    with pytest.raises(ParameterError) as exc:
        resolve_parameters(recipe, BASE | {"length_m": True})
    assert "length_m" in str(exc.value)


def test_non_finite_number_is_rejected(recipe):
    with pytest.raises(ParameterError) as exc:
        resolve_parameters(recipe, BASE | {"height_m": float("nan")})
    assert "height_m" in str(exc.value)


def test_unknown_parameter_type_raises(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe("""    days: 1""", parameters="  - { id: area_m2, type: numbr }"),
        name="bad-type",
    )
    with pytest.raises(RecipeError) as exc:
        resolve_parameters(r, {"area_m2": 5})
    assert "numbr" in str(exc.value)


def test_enum_without_values_raises(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe("""    days: 1""", parameters="  - { id: finish, type: enum }"),
        name="valueless-enum",
    )
    with pytest.raises(RecipeError) as exc:
        resolve_parameters(r, {"finish": "mid"})
    assert "finish" in str(exc.value)


def test_duplicate_parameter_declaration_raises(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe(
            """    days: 1""",
            parameters=(
                "  - { id: area_m2, type: number }\n"
                "  - { id: area_m2, type: number, default: 3 }"
            ),
        ),
        name="duplicate-param",
    )
    with pytest.raises(RecipeError) as exc:
        resolve_parameters(r, {"area_m2": 5})
    assert "area_m2" in str(exc.value)


def test_invalid_default_is_a_recipe_error(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe(
            """    days: 1""",
            parameters="  - { id: finish, type: enum, values: [mid], default: gold }",
        ),
        name="bad-default",
    )
    with pytest.raises(RecipeError) as exc:
        resolve_parameters(r, {})
    assert "finish" in str(exc.value)


def test_derived_values_see_earlier_derived_values(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        """
id: chained
label: Chained
parameters:
  - { id: area_m2, type: number }
derived:
  doubled: area_m2 * 2
  quadrupled: doubled * 2
tasks:
  - id: only
    label: Only
    trade: tiler
    days: 1
""",
        name="chained",
    )
    ns = build_namespace(r, resolve_parameters(r, {"area_m2": 3}))
    assert ns["doubled"] == pytest.approx(6)
    assert ns["quadrupled"] == pytest.approx(12)


def test_derived_value_shadowing_a_parameter_raises(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        """
id: shadow
label: Shadow
parameters:
  - { id: area_m2, type: number }
derived:
  area_m2: area_m2 * 2
tasks:
  - id: only
    label: Only
    trade: tiler
    days: 1
""",
        name="shadow",
    )
    with pytest.raises(RecipeError) as exc:
        build_namespace(r, resolve_parameters(r, {"area_m2": 3}))
    assert "area_m2" in str(exc.value)


def test_parameter_shadowing_a_constant_raises(tmp_path, catalogue):
    r = _recipe_from(
        tmp_path,
        catalogue,
        """
id: shadow-constant
label: Shadow constant
parameters:
  - { id: area_m2, type: number }
constants:
  area_m2: 12
tasks:
  - id: only
    label: Only
    trade: tiler
    days: 1
""",
        name="shadow-constant",
    )
    with pytest.raises(RecipeError) as exc:
        build_namespace(r, resolve_parameters(r, {"area_m2": 3}))
    assert "area_m2" in str(exc.value)


def test_constants_are_visible_to_expressions(recipe):
    ns = build_namespace(recipe, resolve_parameters(recipe, BASE))
    assert ns["wall_factor"] == {"budget": 0.5, "mid": 1.0, "premium": 1.0}


def test_quantify_preserves_task_and_material_order(recipe, catalogue):
    tasks = quantify(recipe, resolve_parameters(recipe, BASE), catalogue)
    assert [t.id for t in tasks] == ["strip_out", "tanking", "tiling"]
    assert [m.sku.id for m in tasks[2].materials] == ["tile-mid", "adhesive-20kg"]


def test_float_noise_does_not_round_a_quantity_up_to_a_whole_extra_unit(tmp_path, catalogue):
    """0.1 + 0.2 is 0.30000000000000004 in float; ceil() would turn a quantity
    that is exactly one coverage unit into two purchased units."""
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe(
            """    days: 1
    materials:
      - { sku: adhesive-20kg, qty: "4.5 * (area_m2 + 0.2) / 0.3", by_coverage: true }"""
        ),
        name="noise",
    )
    # Exactly 4.5 m2 in real arithmetic, 4.500000000000001 in float: one bag, not two.
    tasks = quantify(r, resolve_parameters(r, {"area_m2": 0.1}), catalogue)
    assert tasks[0].materials[0].raw_qty == Decimal("4.5")
    assert tasks[0].materials[0].units == Decimal("1")


def test_a_quantity_that_lands_on_negative_zero_is_not_an_error(tmp_path, catalogue):
    """max(0, ...) style arithmetic can land on -1e-16; that is zero, not a fault."""
    r = _recipe_from(
        tmp_path,
        catalogue,
        _one_task_recipe(
            """    days: 1
    materials:
      - { sku: tile-mid, qty: "area_m2 - (0.1 + 0.2) / 0.3" }"""
        ),
        name="negative-zero",
    )
    # Exactly zero in real arithmetic, -2.2e-16 in float.
    tasks = quantify(r, resolve_parameters(r, {"area_m2": 1.0}), catalogue)
    assert tasks[0].materials[0].raw_qty == Decimal("0")
