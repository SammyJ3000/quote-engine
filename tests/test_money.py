from decimal import Decimal

import pytest

from engine.errors import MissingPriceError, RecipeError
from engine.money import (
    require_decimal,
    require_positive,
    require_rate,
    round_money,
    round_to_nearest,
    to_decimal,
)


def test_to_decimal_from_float_does_not_leak_binary_error():
    assert to_decimal(24.99) == Decimal("24.99")


def test_to_decimal_passes_decimals_through():
    assert to_decimal(Decimal("10.5")) == Decimal("10.5")


def test_round_money_uses_half_up_not_bankers():
    assert round_money(Decimal("2.125")) == Decimal("2.13")
    assert round_money(Decimal("2.135")) == Decimal("2.14")


def test_round_to_nearest_fifty():
    assert round_to_nearest(Decimal("8421.00"), 50) == Decimal("8400")
    assert round_to_nearest(Decimal("8426.00"), 50) == Decimal("8450")


# --- the shared numeric validator -------------------------------------------
# Every one of these used to escape the CLI as a decimal.InvalidOperation
# traceback, which is the worst thing that can happen in front of a customer.

@pytest.mark.parametrize("value", ["£285", "22%", "", "twenty", None, True, [1]])
def test_require_decimal_rejects_non_numbers_naming_file_and_key(value):
    with pytest.raises(RecipeError) as exc:
        require_decimal(value, "plumber", "client 'demo-nw' labour.yaml")
    assert "plumber" in str(exc.value) and "labour.yaml" in str(exc.value)


def test_require_decimal_accepts_numbers_and_numeric_strings():
    assert require_decimal(285, "plumber", "where") == Decimal("285")
    assert require_decimal("285.50", "plumber", "where") == Decimal("285.50")
    assert require_decimal(0, "plumber", "where") == Decimal("0")


def test_require_decimal_rejects_infinity():
    with pytest.raises(RecipeError):
        require_decimal(float("inf"), "plumber", "where")


def test_require_decimal_raises_the_error_type_it_is_given():
    with pytest.raises(MissingPriceError):
        require_decimal("£24.99", "list", "where", error=MissingPriceError)


def test_require_rate_accepts_a_proportion():
    assert require_rate(0.15, "default", "where") == Decimal("0.15")
    assert require_rate(0, "default", "where") == Decimal("0")


@pytest.mark.parametrize("value", [15, 1, 1.5, -0.01])
def test_require_rate_rejects_anything_outside_zero_to_one(value):
    with pytest.raises(RecipeError) as exc:
        require_rate(value, "default", "client 'demo-nw' discounts.yaml")
    assert "default" in str(exc.value)


def test_require_positive_rejects_zero_and_negative():
    for value in (0, -1):
        with pytest.raises(RecipeError):
            require_positive(value, "plumber", "where")


def test_require_positive_accepts_a_day_rate():
    assert require_positive(285, "plumber", "where") == Decimal("285")
