from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from engine.errors import QuoteError, RecipeError

PENNY = Decimal("0.01")
ONE = Decimal("1")


def to_decimal(value) -> Decimal:
    """Convert a YAML/JSON number to Decimal without inheriting float error."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def require_decimal(
    value, key: str, where: str, *, error: type[QuoteError] = RecipeError
) -> Decimal:
    """Convert a value loaded from a config file to a finite Decimal, or say which key is wrong.

    Mirrors the _require* helpers in engine/recipes.py. `"£285"` or `22%` is an
    authoring mistake to report by name, never a value to guess at — and never a
    decimal.InvalidOperation traceback on screen mid-demo.
    """
    if value is None or isinstance(value, bool):
        raise error(f"{where} key {key!r} must be a number, got {value!r}")
    try:
        number = to_decimal(value)
    except (ArithmeticError, InvalidOperation, TypeError, ValueError):
        raise error(f"{where} key {key!r} must be a number, got {value!r}") from None
    if not number.is_finite():
        raise error(f"{where} key {key!r} must be a finite number, got {value!r}")
    return number


def require_rate(
    value, key: str, where: str, *, error: type[QuoteError] = RecipeError
) -> Decimal:
    """A proportion of one: 0.15 means 15%. A rate of 15 is a typo, not 1500%."""
    number = require_decimal(value, key, where, error=error)
    if number < 0 or number >= ONE:
        raise error(
            f"{where} key {key!r} must be a rate between 0 and 1 "
            f"(0.15 means 15%), got {value!r}"
        )
    return number


def require_positive(
    value, key: str, where: str, *, error: type[QuoteError] = RecipeError
) -> Decimal:
    """A day rate or a price: a real number greater than zero."""
    number = require_decimal(value, key, where, error=error)
    if number <= 0:
        raise error(f"{where} key {key!r} must be greater than zero, got {value!r}")
    return number


def round_money(value: Decimal) -> Decimal:
    """Round to whole pence, half up — the convention people expect on an invoice."""
    return value.quantize(PENNY, rounding=ROUND_HALF_UP)


def round_to_nearest(value: Decimal, step: int) -> Decimal:
    """Round to the nearest `step` pounds, for display. Reads like a builder's quote."""
    step_dec = Decimal(step)
    return (value / step_dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step_dec
