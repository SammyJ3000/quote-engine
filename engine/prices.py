import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

from engine.errors import MissingPriceError, RecipeError
from engine.models import Sku
from engine.money import require_positive, require_rate


class PriceBook:
    def __init__(self, captured: str, prices: dict[str, dict]):
        self.captured = captured
        self._prices = prices

    def list_price(self, sku_id: str) -> Decimal:
        entry = self._prices.get(sku_id)
        if entry is None:
            raise MissingPriceError(
                f"no price for SKU {sku_id!r} in price book captured {self.captured}"
            )
        where = f"price book captured {self.captured} SKU {sku_id!r}"
        if not isinstance(entry, dict):
            raise MissingPriceError(f"{where} is {entry!r}, not a price entry")
        if "list" not in entry:
            raise MissingPriceError(f"{where} missing required key 'list'")
        return require_positive(entry["list"], "list", where, error=MissingPriceError)

    def method(self, sku_id: str) -> str:
        entry = self._prices.get(sku_id)
        if not isinstance(entry, dict):
            return "unknown"
        return entry.get("method", "unknown")

    def __contains__(self, sku_id: str) -> bool:
        return sku_id in self._prices


def load_price_book(path: str | Path) -> PriceBook:
    raw = json.loads(Path(path).read_text())
    where = f"price book {str(path)!r}"
    if not isinstance(raw, dict):
        raise MissingPriceError(f"{where} must be a mapping, got {type(raw).__name__}")
    for key in ("captured", "prices"):
        if key not in raw:
            raise MissingPriceError(f"{where} missing required key {key!r}")
    if not isinstance(raw["prices"], dict):
        raise MissingPriceError(
            f"{where} key 'prices' must be a mapping, got {type(raw['prices']).__name__}"
        )
    return PriceBook(captured=raw["captured"], prices=raw["prices"])


def latest_price_book(directory: str | Path) -> PriceBook:
    """Load the most recent dated price book. Filenames are YYYY-MM-DD.json.

    Anything else in the directory — zz-backup.json, prices.json — is skipped
    rather than sorted lexically to the end and quoted as if it were current.
    """
    dated: list[tuple[date, Path]] = []
    for path in Path(directory).glob("*.json"):
        try:
            captured = date.fromisoformat(path.stem)
        except ValueError:
            continue
        dated.append((captured, path))

    if not dated:
        raise MissingPriceError(
            f"no price books named YYYY-MM-DD.json found in {directory}"
        )
    return load_price_book(max(dated)[1])


class DiscountMatrix:
    def __init__(
        self,
        default: Decimal,
        by_category: dict[str, Decimal],
        by_sku: dict[str, Decimal],
    ):
        self._default = default
        self._by_category = by_category
        self._by_sku = by_sku

    def for_sku(self, sku: Sku) -> Decimal:
        """SKU override beats category, category beats default. 0.0 is a real value."""
        if sku.id in self._by_sku:
            return self._by_sku[sku.id]
        if sku.category in self._by_category:
            return self._by_category[sku.category]
        return self._default


def _rate_mapping(raw: dict, key: str, where: str) -> dict[str, Decimal]:
    section = raw.get(key)
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise RecipeError(
            f"{where} key {key!r} must be a mapping, got {type(section).__name__}"
        )
    return {k: require_rate(v, f"{key}.{k}", where) for k, v in section.items()}


def load_discounts(path: str | Path) -> DiscountMatrix:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    # Named the way labour.yaml and commercial.yaml are, so the three client
    # files report themselves consistently: client 'demo-nw' discounts.yaml.
    where = f"client {Path(path).parent.name!r} {Path(path).name}"
    if not isinstance(raw, dict):
        raise RecipeError(f"{where} must be a mapping, got {type(raw).__name__}")
    if "default" not in raw:
        # Defaulting to 0% quietly quotes every material at full list price.
        raise RecipeError(f"{where} missing required key 'default'")

    return DiscountMatrix(
        default=require_rate(raw["default"], "default", where),
        by_category=_rate_mapping(raw, "by_category", where),
        by_sku=_rate_mapping(raw, "by_sku", where),
    )
