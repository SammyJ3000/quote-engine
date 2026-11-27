from decimal import Decimal
from pathlib import Path

import yaml

from engine.errors import RecipeError
from engine.models import Sku
from engine.money import require_decimal

REQUIRED_FIELDS = ("id", "name", "unit", "category")


class Catalogue:
    def __init__(self, skus: dict[str, Sku]):
        self._skus = skus

    def get(self, sku_id: str) -> Sku:
        try:
            return self._skus[sku_id]
        except KeyError:
            raise RecipeError(f"unknown SKU {sku_id!r}") from None

    def resolve_tier(self, sku_id: str, tier: str | None) -> Sku:
        """Swap a base SKU for its tier variant. Absent tier falls back to the base."""
        sku = self.get(sku_id)
        if tier is None:
            return sku
        variant_id = sku.tiers.get(tier)
        if variant_id is None:
            return sku
        return self.get(variant_id)

    def ids(self) -> list[str]:
        """Every SKU id in the catalogue, sorted. Used by the price harvester."""
        return sorted(self._skus)

    def __contains__(self, sku_id: str) -> bool:
        return sku_id in self._skus

    def __len__(self) -> int:
        return len(self._skus)


def _discrete(entry: dict, where: str) -> bool:
    value = entry.get("discrete")
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    # bool("false") is True. A quoted boolean is an authoring mistake, not a value
    # to guess at — guessing would silently start rounding a SKU up to whole units.
    raise RecipeError(f"{where} key 'discrete' must be a boolean, got {value!r}")


def _coverage_per_unit(entry: dict, where: str) -> Decimal | None:
    coverage = entry.get("coverage")
    if coverage is None:
        return None
    if not isinstance(coverage, dict):
        raise RecipeError(
            f"{where} key 'coverage' must be a mapping, got {type(coverage).__name__}"
        )
    if "per_unit" not in coverage:
        raise RecipeError(f"{where} key 'coverage' missing required key 'per_unit'")
    return require_decimal(coverage["per_unit"], "coverage.per_unit", where)


def load_catalogue(path: str | Path) -> Catalogue:
    raw = yaml.safe_load(Path(path).read_text()) or []
    where_file = f"catalogue {str(path)!r}"
    if not isinstance(raw, list):
        raise RecipeError(f"{where_file} must be a list of SKUs, got {type(raw).__name__}")

    skus: dict[str, Sku] = {}

    for i, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise RecipeError(f"{where_file} entry {i} must be a mapping, got {entry!r}")
        missing = [f for f in REQUIRED_FIELDS if f not in entry]
        if missing:
            raise RecipeError(f"SKU {entry.get('id', '<no id>')!r} missing fields: {missing}")
        if entry["id"] in skus:
            raise RecipeError(f"duplicate SKU id {entry['id']!r}")

        where = f"SKU {entry['id']!r}"
        tiers = entry.get("tiers")
        if tiers is not None and not isinstance(tiers, dict):
            raise RecipeError(
                f"{where} key 'tiers' must be a mapping, got {type(tiers).__name__}"
            )

        skus[entry["id"]] = Sku(
            id=entry["id"],
            name=entry["name"],
            unit=entry["unit"],
            category=entry["category"],
            discrete=_discrete(entry, where),
            coverage_per_unit=_coverage_per_unit(entry, where),
            tiers=dict(tiers or {}),
        )

    # Tier targets must exist, and we can only know that once everything is loaded.
    for sku in skus.values():
        for tier, target in sku.tiers.items():
            if target not in skus:
                raise RecipeError(f"SKU {sku.id!r} tier {tier!r} points at unknown SKU {target!r}")

    return Catalogue(skus)
