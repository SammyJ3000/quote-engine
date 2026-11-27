from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from engine.errors import RecipeError
from engine.money import require_positive, require_rate
from engine.prices import DiscountMatrix, load_discounts

COMMERCIAL_DEFAULTS = {
    "overhead_margin": "0.22",
    "contingency": "0.05",
    "quote_band": "0.08",
    "vat_rate": "0.20",
}


@dataclass(frozen=True)
class ClientConfig:
    slug: str
    day_rates: dict[str, Decimal]
    discounts: DiscountMatrix
    overhead_margin: Decimal
    contingency: Decimal
    quote_band: Decimal
    vat_rate: Decimal
    display_rounding: int

    def day_rate(self, trade: str) -> Decimal:
        try:
            return self.day_rates[trade]
        except KeyError:
            raise RecipeError(
                f"no day rate for trade {trade!r} in client {self.slug!r}"
            ) from None


def _mapping(raw, where: str) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise RecipeError(f"{where} must be a mapping, got {type(raw).__name__}")
    return raw


def _rate(commercial: dict, key: str, where: str) -> Decimal:
    """A commercial rate, falling back to the house default when unset."""
    return require_rate(commercial.get(key, COMMERCIAL_DEFAULTS[key]), key, where)


def load_client(directory: str | Path) -> ClientConfig:
    d = Path(directory)
    labour_where = f"client {d.name!r} labour.yaml"
    commercial_where = f"client {d.name!r} commercial.yaml"
    labour = _mapping(yaml.safe_load((d / "labour.yaml").read_text()), labour_where)
    commercial = _mapping(
        yaml.safe_load((d / "commercial.yaml").read_text()), commercial_where
    )

    raw_rounding = commercial.get("display_rounding", 50)
    if isinstance(raw_rounding, bool):
        raise RecipeError(
            f"display_rounding must be a positive integer for client {d.name!r}, "
            f"got {raw_rounding!r}"
        )
    try:
        display_rounding = int(raw_rounding)
    except (TypeError, ValueError):
        raise RecipeError(
            f"display_rounding must be a positive integer for client {d.name!r}, "
            f"got {raw_rounding!r}"
        ) from None
    if display_rounding <= 0:
        raise RecipeError(
            f"display_rounding must be a positive integer for client {d.name!r}, "
            f"got {raw_rounding!r}"
        )

    return ClientConfig(
        slug=d.name,
        day_rates={
            trade: require_positive(rate, trade, labour_where)
            for trade, rate in labour.items()
        },
        discounts=load_discounts(d / "discounts.yaml"),
        overhead_margin=_rate(commercial, "overhead_margin", commercial_where),
        contingency=_rate(commercial, "contingency", commercial_where),
        quote_band=_rate(commercial, "quote_band", commercial_where),
        vat_rate=_rate(commercial, "vat_rate", commercial_where),
        display_rounding=display_rounding,
    )
