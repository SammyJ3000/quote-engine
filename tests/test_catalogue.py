from decimal import Decimal

import pytest

from engine.catalogue import load_catalogue
from engine.errors import RecipeError

FIXTURE = """
- id: tile-ceramic-mid
  name: Ceramic wall tile, mid range
  unit: m2
  category: finishes
  tiers:
    budget: tile-ceramic-budget
    premium: tile-porcelain-premium

- id: tile-ceramic-budget
  name: Ceramic wall tile, budget
  unit: m2
  category: finishes

- id: tile-porcelain-premium
  name: Porcelain wall tile, premium
  unit: m2
  category: finishes

- id: adhesive-flexible-20kg
  name: Flexible tile adhesive 20kg
  unit: bag
  category: finishes
  discrete: true
  coverage:
    unit: m2
    per_unit: 4.5
"""


@pytest.fixture
def catalogue(tmp_path):
    path = tmp_path / "materials.yaml"
    path.write_text(FIXTURE)
    return load_catalogue(path)


def test_loads_a_sku(catalogue):
    sku = catalogue.get("tile-ceramic-mid")
    assert sku.name == "Ceramic wall tile, mid range"
    assert sku.category == "finishes"
    assert sku.unit == "m2"


def test_coverage_is_decimal(catalogue):
    assert catalogue.get("adhesive-flexible-20kg").coverage_per_unit == Decimal("4.5")


def test_discrete_defaults_to_false(catalogue):
    assert catalogue.get("tile-ceramic-mid").discrete is False
    assert catalogue.get("adhesive-flexible-20kg").discrete is True


def test_resolve_tier_swaps_the_sku(catalogue):
    assert catalogue.resolve_tier("tile-ceramic-mid", "premium").id == "tile-porcelain-premium"


def test_resolve_tier_falls_back_to_base_when_tier_absent(catalogue):
    assert catalogue.resolve_tier("tile-ceramic-mid", "mid").id == "tile-ceramic-mid"


def test_ids_lists_every_sku_sorted(catalogue):
    assert catalogue.ids() == [
        "adhesive-flexible-20kg",
        "tile-ceramic-budget",
        "tile-ceramic-mid",
        "tile-porcelain-premium",
    ]


def test_unknown_sku_raises(catalogue):
    with pytest.raises(RecipeError) as exc:
        catalogue.get("does-not-exist")
    assert "does-not-exist" in str(exc.value)


def test_tier_pointing_at_a_missing_sku_fails_at_load(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "- id: a\n  name: A\n  unit: m2\n  category: finishes\n  tiers:\n    premium: nope\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_catalogue(path)
    assert "nope" in str(exc.value)


def _catalogue_text(extra: str) -> str:
    return "- id: a\n  name: A\n  unit: m2\n  category: finishes\n" + extra


def test_quoted_false_discrete_raises_rather_than_reading_as_true(tmp_path):
    """bool("false") is True, which would silently start rounding a SKU to whole units."""
    path = tmp_path / "bad.yaml"
    path.write_text(_catalogue_text('  discrete: "false"\n'))
    with pytest.raises(RecipeError) as exc:
        load_catalogue(path)
    assert "discrete" in str(exc.value) and "'a'" in str(exc.value)


def test_non_boolean_discrete_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(_catalogue_text("  discrete: 1\n"))
    with pytest.raises(RecipeError):
        load_catalogue(path)


def test_a_catalogue_that_is_not_a_list_raises_and_names_the_file(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("tile-ceramic-mid:\n  name: Tile\n")
    with pytest.raises(RecipeError) as exc:
        load_catalogue(path)
    assert "bad.yaml" in str(exc.value)


def test_a_catalogue_entry_that_is_not_a_mapping_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("- tile-ceramic-mid\n")
    with pytest.raises(RecipeError) as exc:
        load_catalogue(path)
    assert "bad.yaml" in str(exc.value)


def test_coverage_without_per_unit_raises_and_names_the_sku(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(_catalogue_text("  coverage:\n    unit: m2\n"))
    with pytest.raises(RecipeError) as exc:
        load_catalogue(path)
    assert "per_unit" in str(exc.value) and "'a'" in str(exc.value)


def test_a_non_numeric_coverage_raises_and_names_the_sku(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(_catalogue_text("  coverage:\n    unit: m2\n    per_unit: about four\n"))
    with pytest.raises(RecipeError) as exc:
        load_catalogue(path)
    assert "'a'" in str(exc.value)
