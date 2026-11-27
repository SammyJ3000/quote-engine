from decimal import Decimal

import pytest

from engine.errors import ParameterError, RecipeError
from engine.quote import build_quote

BASE_PARAMS = {
    "length_m": 2.4,
    "width_m": 1.8,
    "spec_tier": "mid",
    "shower_type": "walk-in",
    "tiling_extent": "full-height",
    "layout_change": "none",
    "floor_type": "tile",
}


def test_end_to_end_produces_a_positive_range():
    result = build_quote(
        recipe_id="bathroom-refit",
        parameters=BASE_PARAMS,
        client_slug="demo-nw",
    )
    assert result.totals.low > Decimal("0")
    assert result.totals.high > result.totals.low
    assert result.recipe_label == "Bathroom refit"


def test_result_carries_provenance_for_the_internal_view():
    result = build_quote(
        recipe_id="bathroom-refit",
        parameters=BASE_PARAMS,
        client_slug="demo-nw",
    )
    assert result.price_book_captured
    assert result.client_slug == "demo-nw"
    assert len(result.tasks) > 5
    assert "floor_area_m2" in result.derived


def test_bad_parameters_raise_before_any_pricing():
    with pytest.raises(ParameterError):
        build_quote(recipe_id="bathroom-refit", parameters={}, client_slug="demo-nw")


def test_openings_m2_is_subtracted_from_wall_area():
    """Task 10's review: wall_area_m2 must deduct openings_m2, not just gross wall."""
    gross = 2 * (2.4 + 1.8) * 2.4  # length_m + width_m default height 2.4

    no_openings = build_quote(
        recipe_id="bathroom-refit",
        parameters={**BASE_PARAMS, "openings_m2": 0},
        client_slug="demo-nw",
    )
    assert no_openings.derived["wall_area_m2"] == pytest.approx(gross)

    with_openings = build_quote(
        recipe_id="bathroom-refit",
        parameters={**BASE_PARAMS, "openings_m2": 3.5},
        client_slug="demo-nw",
    )
    assert with_openings.derived["wall_area_m2"] == pytest.approx(gross - 3.5)
    assert with_openings.derived["wall_area_m2"] < no_openings.derived["wall_area_m2"]


def test_unknown_recipe_id_raises_a_clear_error():
    with pytest.raises(RecipeError, match="no-such-recipe"):
        build_quote(
            recipe_id="no-such-recipe",
            parameters=BASE_PARAMS,
            client_slug="demo-nw",
        )


def test_unknown_client_slug_raises_a_clear_error():
    with pytest.raises(RecipeError, match="no-such-client"):
        build_quote(
            recipe_id="bathroom-refit",
            parameters=BASE_PARAMS,
            client_slug="no-such-client",
        )
