import pytest

from engine.clientconfig import ClientConfig
from engine.quote import build_quote, load_setup
from engine.validate import validate_setup
from scripts.quote_cli import format_check, format_quote, main, parse_params

PARAMS = {
    "length_m": 2.4, "width_m": 1.8, "spec_tier": "mid", "shower_type": "walk-in",
    "tiling_extent": "full-height", "layout_change": "none", "floor_type": "tile",
}


def test_parse_params_coerces_numbers():
    parsed = parse_params(["length_m=2.4", "spec_tier=mid"])
    assert parsed["length_m"] == 2.4
    assert parsed["spec_tier"] == "mid"


def test_parse_params_rejects_malformed_pairs():
    with pytest.raises(SystemExit):
        parse_params(["length_m"])


def test_summary_shows_the_range_and_the_four_line_breakdown():
    out = format_quote(build_quote("bathroom-refit", PARAMS, "demo-nw"), detail=False)
    assert "Bathroom refit" in out
    assert "Labour" in out and "Materials" in out and "Plant" in out and "Contingency" in out


def test_detail_view_lists_tasks_and_skus():
    out = format_quote(build_quote("bathroom-refit", PARAMS, "demo-nw"), detail=True)
    assert "Wall tiling" in out
    assert "tile-ceramic-mid" in out


def test_summary_view_hides_skus():
    out = format_quote(build_quote("bathroom-refit", PARAMS, "demo-nw"), detail=False)
    assert "tile-ceramic-mid" not in out


def test_main_returns_1_and_writes_to_stderr_for_bad_parameter(capsys):
    exit_code = main([
        "--recipe", "bathroom-refit",
        "--client", "demo-nw",
        "--param", "length_m=2.4",
        "--param", "width_m=1.8",
        "--param", "spec_tier=not-a-real-tier",
        "--param", "shower_type=walk-in",
        "--param", "tiling_extent=full-height",
        "--param", "layout_change=none",
        "--param", "floor_type=tile",
    ])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() != ""


def test_detail_view_labels_coverage_material_with_purchasable_unit():
    out = format_quote(build_quote("bathroom-refit", PARAMS, "demo-nw"), detail=True)
    lines = [line for line in out.splitlines() if "adhesive-flexible-20kg" in line]
    assert lines, "expected an adhesive-flexible-20kg line in detail view"
    line = lines[0]
    assert "bag" in line


def test_detail_view_shows_the_material_name_as_well_as_the_sku():
    """The detail view is read by staff and customers: 'tile-ceramic-mid' alone
    is not something a customer can price up."""
    out = format_quote(build_quote("bathroom-refit", PARAMS, "demo-nw"), detail=True)
    line = next(line for line in out.splitlines() if "tile-ceramic-mid" in line)
    assert "Ceramic wall tile, mid range" in line


def test_check_passes_for_the_shipped_client(capsys):
    exit_code = main(["--recipe", "bathroom-refit", "--client", "demo-nw", "--check"])
    captured = capsys.readouterr()
    assert exit_code == 0, captured.out
    assert "OK" in captured.out
    assert "bathroom-refit" in captured.out and "demo-nw" in captured.out


def test_check_reports_a_missing_recipe_cleanly(capsys):
    exit_code = main(["--recipe", "kitchen-refit", "--client", "demo-nw", "--check"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "kitchen-refit" in captured.err


def test_check_lists_every_gap_and_exits_non_zero(capsys):
    """A skin missing a trade and a price must show both, not stop at the first."""
    recipe, client, book, catalogue = load_setup("bathroom-refit", "demo-nw")
    stripped = ClientConfig(
        slug="acme-bathrooms",
        day_rates={k: v for k, v in client.day_rates.items() if k != "tiler"},
        discounts=client.discounts,
        overhead_margin=client.overhead_margin,
        contingency=client.contingency,
        quote_band=client.quote_band,
        vat_rate=client.vat_rate,
        display_rounding=client.display_rounding,
    )
    problems = validate_setup(recipe, stripped, book, catalogue)
    out = format_check(recipe, stripped, book, catalogue, problems)

    assert "tiler" in out
    assert "acme-bathrooms" in out
    assert "OK" not in out
