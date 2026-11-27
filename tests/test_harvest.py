import json
from datetime import date

import pytest

import scripts.harvest_prices as harvest_prices
from engine.catalogue import load_catalogue
from scripts.harvest_prices import HarvestError, load_manual_prices, main, merge_prices

CATALOGUE = """
- { id: a, name: A, unit: m2, category: finishes }
- { id: b, name: B, unit: each, category: plant, discrete: true }
- { id: c, name: C, unit: bag, category: heavy-side, discrete: true }
"""


@pytest.fixture
def catalogue(tmp_path):
    p = tmp_path / "materials.yaml"
    p.write_text(CATALOGUE)
    return load_catalogue(p)


# --- brief's five tests, verbatim ------------------------------------------


def test_fetched_prices_are_marked_scraped(catalogue):
    book = merge_prices(catalogue, {"a": (12.5, "http://x")}, {}, "2026-08-20")
    assert book["prices"]["a"]["list"] == 12.5
    assert book["prices"]["a"]["method"] == "scraped"


def test_manual_prices_are_marked_hand(catalogue):
    book = merge_prices(catalogue, {}, {"b": 260.0}, "2026-08-20")
    assert book["prices"]["b"]["method"] == "hand"


def test_manual_overrides_fetched(catalogue):
    book = merge_prices(catalogue, {"a": (12.5, "http://x")}, {"a": 99.0}, "2026-08-20")
    assert book["prices"]["a"]["list"] == 99.0
    assert book["prices"]["a"]["method"] == "hand"


def test_unpriced_skus_are_reported_not_silently_dropped(catalogue):
    book = merge_prices(catalogue, {"a": (12.5, "http://x")}, {}, "2026-08-20")
    assert set(book["unpriced"]) == {"b", "c"}


def test_unit_comes_from_the_catalogue(catalogue):
    book = merge_prices(catalogue, {"a": (12.5, "http://x")}, {}, "2026-08-20")
    assert book["prices"]["a"]["unit"] == "m2"


# --- hardening: merge_prices input validation -------------------------------


def test_unknown_sku_in_manual_raises_clear_error(catalogue):
    with pytest.raises(HarvestError) as exc:
        merge_prices(catalogue, {}, {"not-a-real-sku": 10.0}, "2026-08-20")
    assert "not-a-real-sku" in str(exc.value)


def test_unknown_sku_in_fetched_raises_clear_error(catalogue):
    with pytest.raises(HarvestError) as exc:
        merge_prices(catalogue, {"not-a-real-sku": (10.0, "http://x")}, {}, "2026-08-20")
    assert "not-a-real-sku" in str(exc.value)


def test_non_numeric_manual_price_raises_clear_error(catalogue):
    with pytest.raises(HarvestError) as exc:
        merge_prices(catalogue, {}, {"a": "expensive"}, "2026-08-20")
    assert "a" in str(exc.value)


def test_negative_manual_price_raises_clear_error(catalogue):
    with pytest.raises(HarvestError) as exc:
        merge_prices(catalogue, {}, {"a": -5.0}, "2026-08-20")
    assert "a" in str(exc.value)


def test_zero_manual_price_raises_clear_error(catalogue):
    with pytest.raises(HarvestError):
        merge_prices(catalogue, {}, {"a": 0}, "2026-08-20")


def test_boolean_manual_price_is_rejected(catalogue):
    with pytest.raises(HarvestError):
        merge_prices(catalogue, {}, {"a": True}, "2026-08-20")


def test_non_numeric_fetched_price_raises_clear_error(catalogue):
    with pytest.raises(HarvestError) as exc:
        merge_prices(catalogue, {"a": ("free", "http://x")}, {}, "2026-08-20")
    assert "a" in str(exc.value)


# --- hardening: load_manual_prices ------------------------------------------


def test_load_manual_prices_missing_file_returns_empty(tmp_path):
    assert load_manual_prices(tmp_path / "does-not-exist.yaml") == {}


def test_load_manual_prices_empty_file_returns_empty(tmp_path):
    p = tmp_path / "manual.yaml"
    p.write_text("")
    assert load_manual_prices(p) == {}


def test_load_manual_prices_rejects_a_list(tmp_path):
    p = tmp_path / "manual.yaml"
    p.write_text("- a\n- b\n")
    with pytest.raises(SystemExit):
        load_manual_prices(p)


def test_load_manual_prices_rejects_invalid_yaml(tmp_path):
    p = tmp_path / "manual.yaml"
    p.write_text("a: [unclosed\n")
    with pytest.raises(SystemExit):
        load_manual_prices(p)


def test_load_manual_prices_reads_a_valid_mapping(tmp_path):
    p = tmp_path / "manual.yaml"
    p.write_text("tile-ceramic-mid: 24.99\n")
    assert load_manual_prices(p) == {"tile-ceramic-mid": 24.99}


# --- hardening: main() CLI ---------------------------------------------------


def test_main_treats_missing_manual_file_as_no_manual_prices(tmp_path):
    exit_code = main(["--manual", str(tmp_path / "nope.yaml"), "--out", str(tmp_path / "out")])
    assert exit_code == 0


def test_main_creates_a_missing_output_directory(tmp_path):
    out_dir = tmp_path / "nested" / "pricebook"
    exit_code = main(["--out", str(out_dir)])
    assert exit_code == 0
    assert (out_dir / f"{date.today().isoformat()}.json").exists()


def test_main_reports_unpriced_skus_on_stdout(tmp_path, monkeypatch, capsys):
    catalogue_dir = tmp_path / "catalogue"
    catalogue_dir.mkdir()
    (catalogue_dir / "materials.yaml").write_text(CATALOGUE)
    (catalogue_dir / "sources.yaml").write_text("{}\n")
    monkeypatch.setattr(harvest_prices, "PROJECT_ROOT", tmp_path)

    manual = tmp_path / "manual.yaml"
    manual.write_text("a: 12.5\n")  # only "a" priced; "b" and "c" are left out

    exit_code = main(["--manual", str(manual), "--out", str(tmp_path / "out")])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "UNPRICED" in captured.out
    assert "UNPRICED: b" in captured.out
    assert "UNPRICED: c" in captured.out


def test_main_reports_zero_unpriced_when_catalogue_is_fully_priced(tmp_path, monkeypatch, capsys):
    catalogue_dir = tmp_path / "catalogue"
    catalogue_dir.mkdir()
    (catalogue_dir / "materials.yaml").write_text(CATALOGUE)
    (catalogue_dir / "sources.yaml").write_text("{}\n")
    monkeypatch.setattr(harvest_prices, "PROJECT_ROOT", tmp_path)

    manual = tmp_path / "manual.yaml"
    manual.write_text("a: 12.5\nb: 260.0\nc: 4.0\n")  # every SKU priced

    exit_code = main(["--manual", str(manual), "--out", str(tmp_path / "out")])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "0 unpriced" in captured.out
    assert "UNPRICED" not in captured.out


def test_main_exits_with_a_message_when_manual_file_is_a_list(tmp_path):
    manual = tmp_path / "manual.yaml"
    manual.write_text("- a\n- b\n")
    with pytest.raises(SystemExit):
        main(["--manual", str(manual), "--out", str(tmp_path / "out")])


def test_main_exits_with_a_message_for_a_negative_manual_price(tmp_path):
    manual = tmp_path / "manual.yaml"
    manual.write_text("tile-ceramic-mid: -5\n")
    with pytest.raises(SystemExit):
        main(["--manual", str(manual), "--out", str(tmp_path / "out")])


def test_main_exits_with_a_message_for_an_unknown_sku_in_manual(tmp_path):
    manual = tmp_path / "manual.yaml"
    manual.write_text("totally-made-up-sku: 5\n")
    with pytest.raises(SystemExit):
        main(["--manual", str(manual), "--out", str(tmp_path / "out")])


# --- hardening: atomic write of the price book ------------------------------


def test_atomic_write_leaves_no_file_on_a_fresh_run_when_serialisation_fails(tmp_path, monkeypatch):
    """A crash while producing the price book must never leave a partial file
    at the path the engine reads from."""
    out_dir = tmp_path / "out"

    def boom(*_args, **_kwargs):
        raise TypeError("simulated serialisation failure")

    monkeypatch.setattr(harvest_prices.json, "dumps", boom)

    with pytest.raises(SystemExit):
        harvest_prices.main(["--out", str(out_dir)])

    target = out_dir / f"{date.today().isoformat()}.json"
    assert not target.exists()
    # no stray temp file left behind either
    if out_dir.exists():
        assert list(out_dir.iterdir()) == []


def test_atomic_write_preserves_an_existing_good_file_when_serialisation_fails(tmp_path, monkeypatch):
    """Task 15 re-runs this script repeatedly on the same day while hand-entering
    prices. A failed re-run must never destroy an already-good price book."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    target = out_dir / f"{date.today().isoformat()}.json"
    original = json.dumps({"captured": "keep-me", "prices": {}, "unpriced": []}, indent=2) + "\n"
    target.write_text(original)

    def boom(*_args, **_kwargs):
        raise TypeError("simulated serialisation failure")

    monkeypatch.setattr(harvest_prices.json, "dumps", boom)

    with pytest.raises(SystemExit):
        harvest_prices.main(["--out", str(out_dir)])

    assert target.read_text() == original
    parsed = json.loads(target.read_text())
    assert parsed["captured"] == "keep-me"
    # no stray temp file left alongside the preserved original
    assert sorted(p.name for p in out_dir.iterdir()) == [target.name]


def test_atomic_write_leaves_no_temp_file_after_a_successful_run(tmp_path):
    out_dir = tmp_path / "out"
    exit_code = harvest_prices.main(["--out", str(out_dir)])
    assert exit_code == 0
    target = out_dir / f"{date.today().isoformat()}.json"
    assert sorted(p.name for p in out_dir.iterdir()) == [target.name]


# --- hardening: main() exits cleanly for missing project files -------------


def test_main_exits_cleanly_when_materials_catalogue_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(harvest_prices, "PROJECT_ROOT", tmp_path)
    with pytest.raises(SystemExit) as exc:
        harvest_prices.main(["--out", str(tmp_path / "out")])
    assert "materials.yaml" in str(exc.value)


def test_main_exits_cleanly_when_sources_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(harvest_prices, "PROJECT_ROOT", tmp_path)
    (tmp_path / "catalogue").mkdir()
    (tmp_path / "catalogue" / "materials.yaml").write_text(CATALOGUE)
    with pytest.raises(SystemExit) as exc:
        harvest_prices.main(["--out", str(tmp_path / "out")])
    assert "sources.yaml" in str(exc.value)


# --- hardening: a typo'd --manual path is not silent ------------------------


def test_load_manual_prices_missing_file_prints_a_clear_message(tmp_path, capsys):
    missing = tmp_path / "typo-prices.yaml"
    result = load_manual_prices(missing)
    assert result == {}
    out = capsys.readouterr().out
    assert str(missing) in out
    assert "not found" in out.lower()


def test_load_manual_prices_empty_file_prints_a_clear_message(tmp_path, capsys):
    p = tmp_path / "manual.yaml"
    p.write_text("")
    result = load_manual_prices(p)
    assert result == {}
    out = capsys.readouterr().out
    assert str(p) in out


def test_main_prints_a_message_when_manual_path_is_a_typo(tmp_path, capsys):
    typo = tmp_path / "manual-prcies.yaml"
    exit_code = main(["--manual", str(typo), "--out", str(tmp_path / "out")])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert str(typo) in out
    assert "not found" in out.lower()
