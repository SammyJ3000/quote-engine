import pytest

from engine.catalogue import load_catalogue
from engine.errors import RecipeError
from engine.recipes import load_recipe

CATALOGUE = """
- id: tile-ceramic-mid
  name: Tile
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
  - { id: length_m, type: number, min: 1.0, max: 6.0 }
  - { id: spec_tier, type: enum, values: [budget, mid, premium] }
  - { id: height_m, type: number, default: 2.4 }
constants:
  tiling_factor: { budget: 0.5, mid: 1.0, premium: 1.0 }
derived:
  tiled_area_m2: length_m * tiling_factor[spec_tier]
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
    days: tiled_area_m2 / 6
    materials:
      - { sku: tile-ceramic-mid, qty: tiled_area_m2, waste: 0.10, tier: spec_tier }
"""


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


def test_loads_identity(recipe):
    assert recipe.id == "test-job"
    assert recipe.label == "Test job"


def test_parameters_keep_bounds_and_defaults(recipe):
    params = {p.id: p for p in recipe.parameters}
    assert params["length_m"].min == 1.0
    assert params["length_m"].max == 6.0
    assert params["height_m"].default == 2.4
    assert params["spec_tier"].values == ["budget", "mid", "premium"]


def test_tasks_and_materials_parse(recipe):
    tiling = [t for t in recipe.tasks if t.id == "tiling"][0]
    assert tiling.trade == "tiler"
    assert tiling.materials[0].waste == 0.10
    assert tiling.materials[0].tier_from == "spec_tier"


def test_waste_defaults_to_zero(recipe):
    strip = [t for t in recipe.tasks if t.id == "strip_out"][0]
    assert strip.materials[0].waste == 0.0


def test_unknown_sku_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: []\ntasks:\n"
        "  - { id: t, label: T, trade: tiler, days: 1, materials: [{ sku: nope, qty: 1 }] }\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    assert "nope" in str(exc.value)


def test_duplicate_task_id_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "dup.yaml"
    p.write_text(
        "id: dup\nlabel: Dup\nparameters: []\ntasks:\n"
        "  - { id: t, label: T, trade: tiler, days: 1 }\n"
        "  - { id: t, label: T2, trade: tiler, days: 1 }\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    assert "t" in str(exc.value)


def test_task_missing_trade_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "no-trade.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: []\ntasks:\n"
        "  - { id: tiling, label: Tiling, days: 1 }\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    message = str(exc.value)
    assert "tiling" in message
    assert "trade" in message


def test_task_missing_days_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "no-days.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: []\ntasks:\n"
        "  - { id: tiling, label: Tiling, trade: tiler }\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    message = str(exc.value)
    assert "tiling" in message
    assert "days" in message


def test_parameter_missing_type_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "no-type.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters:\n  - { id: length_m }\ntasks:\n"
        "  - { id: t, label: T, trade: tiler, days: 1 }\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    message = str(exc.value)
    assert "parameter" in message
    assert "type" in message


def test_material_missing_sku_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "no-sku.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: []\ntasks:\n"
        "  - { id: t, label: T, trade: tiler, days: 1, materials: "
        "[{ sku: tile-ceramic-mid, qty: 1 }, { qty: 1 }] }\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    message = str(exc.value)
    assert "t" in message
    assert "sku" in message


def test_empty_recipe_file_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    assert str(p) in str(exc.value)


def test_null_parameters_loads_as_empty(tmp_path, catalogue):
    p = tmp_path / "null-params.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters:\ntasks:\n"
        "  - { id: t, label: T, trade: tiler, days: 1 }\n"
    )
    recipe = load_recipe(p, catalogue)
    assert recipe.parameters == ()


def test_null_materials_loads_as_empty(tmp_path, catalogue):
    p = tmp_path / "null-materials.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: []\ntasks:\n"
        "  - { id: t, label: T, trade: tiler, days: 1, materials: }\n"
    )
    recipe = load_recipe(p, catalogue)
    task = [t for t in recipe.tasks if t.id == "t"][0]
    assert task.materials == ()


def test_null_tasks_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "null-tasks.yaml"
    p.write_text("id: bad\nlabel: Bad\nparameters: []\ntasks:\n")
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    assert "tasks" in str(exc.value)


def test_empty_tasks_list_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "empty-tasks.yaml"
    p.write_text("id: bad\nlabel: Bad\nparameters: []\ntasks: []\n")
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    assert "tasks" in str(exc.value)


def test_missing_tasks_key_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "no-tasks.yaml"
    p.write_text("id: bad\nlabel: Bad\nparameters: []\n")
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    assert "tasks" in str(exc.value)


def test_tasks_not_a_list_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "tasks-string.yaml"
    p.write_text('id: bad\nlabel: Bad\nparameters: []\ntasks: "strip out"\n')
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    assert "tasks" in str(exc.value)


def test_non_numeric_waste_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "bad-waste.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: []\ntasks:\n"
        "  - { id: tiling, label: Tiling, trade: tiler, days: 1, materials: "
        "[{ sku: tile-ceramic-mid, qty: 1, waste: ten-percent }] }\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    message = str(exc.value)
    assert "tiling" in message
    assert "material" in message
    assert "waste" in message


def test_numeric_string_waste_parses(tmp_path, catalogue):
    p = tmp_path / "string-waste.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: []\ntasks:\n"
        "  - { id: tiling, label: Tiling, trade: tiler, days: 1, materials: "
        '[{ sku: tile-ceramic-mid, qty: 1, waste: "0.10" }] }\n'
    )
    recipe = load_recipe(p, catalogue)
    task = [t for t in recipe.tasks if t.id == "tiling"][0]
    assert task.materials[0].waste == 0.10


def test_null_id_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "null-id.yaml"
    p.write_text(
        "id:\nlabel: Bad\nparameters: []\ntasks:\n"
        "  - { id: t, label: T, trade: tiler, days: 1 }\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    assert "id" in str(exc.value)


def test_null_label_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "null-label.yaml"
    p.write_text(
        "id: bad\nlabel:\nparameters: []\ntasks:\n"
        "  - { id: t, label: T, trade: tiler, days: 1 }\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    assert "label" in str(exc.value)


def test_parameters_not_a_list_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "parameters-mapping.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: { id: length_m, type: number }\ntasks:\n"
        "  - { id: t, label: T, trade: tiler, days: 1 }\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    assert "parameters" in str(exc.value)


def test_materials_not_a_list_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "materials-mapping.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: []\ntasks:\n"
        "  - { id: t, label: T, trade: tiler, days: 1, materials: "
        "{ sku: tile-ceramic-mid, qty: 1 } }\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    assert "materials" in str(exc.value)


def test_parameters_key_absent_loads_as_empty(tmp_path, catalogue):
    p = tmp_path / "no-parameters-key.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\ntasks:\n"
        "  - { id: t, label: T, trade: tiler, days: 1 }\n"
    )
    recipe = load_recipe(p, catalogue)
    assert recipe.parameters == ()


def test_quoted_by_coverage_false_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "quoted-false.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: []\ntasks:\n"
        "  - { id: tiling, label: Tiling, trade: tiler, days: 1, materials: "
        '[{ sku: tile-ceramic-mid, qty: 1, by_coverage: "false" }] }\n'
    )
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    message = str(exc.value)
    assert "tiling" in message
    assert "material" in message
    assert "by_coverage" in message


def test_quoted_by_coverage_true_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "quoted-true.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: []\ntasks:\n"
        "  - { id: tiling, label: Tiling, trade: tiler, days: 1, materials: "
        '[{ sku: tile-ceramic-mid, qty: 1, by_coverage: "true" }] }\n'
    )
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    message = str(exc.value)
    assert "tiling" in message
    assert "material" in message
    assert "by_coverage" in message


def test_unquoted_by_coverage_false_loads_as_false(tmp_path, catalogue):
    p = tmp_path / "unquoted-false.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: []\ntasks:\n"
        "  - { id: tiling, label: Tiling, trade: tiler, days: 1, materials: "
        "[{ sku: tile-ceramic-mid, qty: 1, by_coverage: false }] }\n"
    )
    recipe = load_recipe(p, catalogue)
    task = [t for t in recipe.tasks if t.id == "tiling"][0]
    assert task.materials[0].by_coverage is False


def test_unquoted_by_coverage_true_loads_as_true(tmp_path, catalogue):
    p = tmp_path / "unquoted-true.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: []\ntasks:\n"
        "  - { id: tiling, label: Tiling, trade: tiler, days: 1, materials: "
        "[{ sku: tile-ceramic-mid, qty: 1, by_coverage: true }] }\n"
    )
    recipe = load_recipe(p, catalogue)
    task = [t for t in recipe.tasks if t.id == "tiling"][0]
    assert task.materials[0].by_coverage is True


def test_by_coverage_absent_loads_as_false(tmp_path, catalogue):
    p = tmp_path / "absent-by-coverage.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: []\ntasks:\n"
        "  - { id: tiling, label: Tiling, trade: tiler, days: 1, materials: "
        "[{ sku: tile-ceramic-mid, qty: 1 }] }\n"
    )
    recipe = load_recipe(p, catalogue)
    task = [t for t in recipe.tasks if t.id == "tiling"][0]
    assert task.materials[0].by_coverage is False


def test_constants_as_list_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "constants-list.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: []\nconstants: [1, 2, 3]\ntasks:\n"
        "  - { id: t, label: T, trade: tiler, days: 1 }\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    assert "constants" in str(exc.value)


def test_derived_as_list_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "derived-list.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: []\nderived: [1, 2, 3]\ntasks:\n"
        "  - { id: t, label: T, trade: tiler, days: 1 }\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    assert "derived" in str(exc.value)


def test_null_constants_loads_as_empty(tmp_path, catalogue):
    p = tmp_path / "null-constants.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: []\nconstants:\ntasks:\n"
        "  - { id: t, label: T, trade: tiler, days: 1 }\n"
    )
    recipe = load_recipe(p, catalogue)
    assert recipe.constants == {}
