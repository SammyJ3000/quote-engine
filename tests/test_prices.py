import json
from decimal import Decimal

import pytest

from engine.errors import MissingPriceError, RecipeError
from engine.models import Sku
from engine.prices import latest_price_book, load_discounts, load_price_book

BOOK = {
    "captured": "2026-08-20",
    "prices": {
        "tile-ceramic-mid": {"list": 24.99, "unit": "m2", "source": "x", "method": "scraped"},
    },
}

DISCOUNTS = """
default: 0.15
by_category:
  finishes: 0.20
  plant: 0.0
by_sku:
  tile-ceramic-mid: 0.30
"""


@pytest.fixture
def book(tmp_path):
    path = tmp_path / "2026-08-20.json"
    path.write_text(json.dumps(BOOK))
    return load_price_book(path)


@pytest.fixture
def discounts(tmp_path):
    path = tmp_path / "discounts.yaml"
    path.write_text(DISCOUNTS)
    return load_discounts(path)


def test_list_price_is_decimal(book):
    assert book.list_price("tile-ceramic-mid") == Decimal("24.99")


def test_captured_date_is_available(book):
    assert book.captured == "2026-08-20"


def test_missing_price_raises_and_names_the_sku(book):
    with pytest.raises(MissingPriceError) as exc:
        book.list_price("skip-6yd")
    assert "skip-6yd" in str(exc.value)


def _sku(sku_id, category):
    return Sku(id=sku_id, name=sku_id, unit="m2", category=category)


def test_by_sku_wins_over_category(discounts):
    assert discounts.for_sku(_sku("tile-ceramic-mid", "finishes")) == Decimal("0.30")


def test_category_wins_over_default(discounts):
    assert discounts.for_sku(_sku("other-tile", "finishes")) == Decimal("0.20")


def test_falls_back_to_default(discounts):
    assert discounts.for_sku(_sku("timber-c16", "timber")) == Decimal("0.15")


def test_zero_category_discount_is_respected_not_treated_as_absent(discounts):
    assert discounts.for_sku(_sku("skip-6yd", "plant")) == Decimal("0")


def _write_book(directory, captured, sku_id="tile-ceramic-mid", price=1.0):
    path = directory / f"{captured}.json"
    path.write_text(
        json.dumps(
            {
                "captured": captured,
                "prices": {
                    sku_id: {"list": price, "unit": "m2", "source": "x", "method": "scraped"}
                },
            }
        )
    )
    return path


def test_latest_price_book_picks_the_newest_by_filename(tmp_path):
    _write_book(tmp_path, "2026-01-01")
    _write_book(tmp_path, "2026-08-20")
    _write_book(tmp_path, "2026-03-15")

    book = latest_price_book(tmp_path)

    assert book.captured == "2026-08-20"


def test_latest_price_book_raises_on_empty_directory(tmp_path):
    with pytest.raises(MissingPriceError):
        latest_price_book(tmp_path)


def test_latest_price_book_raises_on_missing_directory(tmp_path):
    missing = tmp_path / "does-not-exist"
    with pytest.raises(MissingPriceError):
        latest_price_book(missing)


# --- a malformed price book must explain itself, not traceback --------------

def _price_book(tmp_path, prices):
    path = tmp_path / "2026-08-20.json"
    path.write_text(json.dumps({"captured": "2026-08-20", "prices": prices}))
    return load_price_book(path)


def test_entry_without_a_list_price_names_the_sku(tmp_path):
    book = _price_book(tmp_path, {"skip-6yd": {"unit": "each", "source": "x"}})
    with pytest.raises(MissingPriceError) as exc:
        book.list_price("skip-6yd")
    assert "skip-6yd" in str(exc.value) and "list" in str(exc.value)


@pytest.mark.parametrize("price", ["£24.99", "twenty", None, 0, -5])
def test_a_non_numeric_or_impossible_price_names_the_sku(tmp_path, price):
    book = _price_book(tmp_path, {"tile-ceramic-mid": {"list": price, "unit": "m2"}})
    with pytest.raises(MissingPriceError) as exc:
        book.list_price("tile-ceramic-mid")
    assert "tile-ceramic-mid" in str(exc.value)


def test_price_book_missing_captured_raises_rather_than_keyerror(tmp_path):
    path = tmp_path / "2026-08-20.json"
    path.write_text(json.dumps({"prices": {}}))
    with pytest.raises(MissingPriceError) as exc:
        load_price_book(path)
    assert "captured" in str(exc.value)


def test_latest_price_book_ignores_files_that_are_not_dates(tmp_path):
    """A stray zz-backup.json sorts last lexically and would become 'latest'."""
    _write_book(tmp_path, "2026-08-20")
    _write_book(tmp_path, "zz-backup")

    assert latest_price_book(tmp_path).captured == "2026-08-20"


def test_latest_price_book_ignores_an_undated_older_backup(tmp_path):
    _write_book(tmp_path, "2026-08-20")
    _write_book(tmp_path, "prices")

    assert latest_price_book(tmp_path).captured == "2026-08-20"


def test_latest_price_book_raises_when_nothing_is_dated(tmp_path):
    _write_book(tmp_path, "zz-backup")
    with pytest.raises(MissingPriceError):
        latest_price_book(tmp_path)


# --- discounts --------------------------------------------------------------

def test_missing_default_discount_raises_rather_than_quoting_at_list(tmp_path):
    path = tmp_path / "discounts.yaml"
    path.write_text("by_category:\n  finishes: 0.20\n")
    with pytest.raises(RecipeError) as exc:
        load_discounts(path)
    assert "default" in str(exc.value)


def test_a_discount_of_15_meaning_15_percent_raises(tmp_path):
    """`default: 15` is a plausible skin-setup mistake that used to quote -£78,100."""
    path = tmp_path / "discounts.yaml"
    path.write_text("default: 15\n")
    with pytest.raises(RecipeError) as exc:
        load_discounts(path)
    assert "default" in str(exc.value)


def test_a_non_numeric_discount_names_the_key(tmp_path):
    path = tmp_path / "discounts.yaml"
    path.write_text("default: 0.15\nby_category:\n  finishes: twenty percent\n")
    with pytest.raises(RecipeError) as exc:
        load_discounts(path)
    assert "finishes" in str(exc.value)
