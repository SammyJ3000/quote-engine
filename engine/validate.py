"""Pre-demo check that one client's setup can actually quote one recipe.

load_recipe checks SKU references against the catalogue, but nothing checks a
client's trades against labour.yaml or its SKUs against the price book until a
particular dropdown combination fires. A skin created the night before a visit
gets none of that. This module checks the whole cross-product up front.
"""

from engine.catalogue import Catalogue
from engine.clientconfig import ClientConfig
from engine.errors import QuoteError
from engine.prices import PriceBook
from engine.recipes import MaterialSpec, Recipe


def material_variants(material: MaterialSpec, catalogue: Catalogue) -> list[str]:
    """Every SKU this material could resolve to, including each tier variant."""
    base = catalogue.get(material.sku)
    if material.tier_from is None:
        return [base.id]
    return [base.id, *base.tiers.values()]


def _needed_by(tasks: list[str]) -> str:
    return ", ".join(tasks)


def validate_setup(
    recipe: Recipe,
    client: ClientConfig,
    book: PriceBook,
    catalogue: Catalogue,
) -> list[str]:
    """Report every gap between a recipe and a client's setup, not just the first.

    Returns a list of problems, empty when the combination is ready to quote:
    every trade any task names has a day rate, and every SKU any task can
    resolve to — every tier variant included — has a usable price.
    """
    missing_trades: dict[str, list[str]] = {}
    unknown_skus: dict[str, list[str]] = {}
    price_problems: dict[str, tuple[str, list[str]]] = {}

    for task in recipe.tasks:
        if task.trade not in client.day_rates:
            missing_trades.setdefault(task.trade, []).append(task.id)

        for material in task.materials:
            if material.sku not in catalogue:
                unknown_skus.setdefault(material.sku, []).append(task.id)
                continue
            for sku_id in material_variants(material, catalogue):
                try:
                    book.list_price(sku_id)
                except QuoteError as exc:
                    reason, tasks = price_problems.setdefault(sku_id, (str(exc), []))
                    if task.id not in tasks:
                        tasks.append(task.id)

    problems = [
        f"no day rate for trade {trade!r} in client {client.slug!r} "
        f"labour.yaml (needed by {_needed_by(tasks)})"
        for trade, tasks in missing_trades.items()
    ]
    problems += [
        f"unknown SKU {sku_id!r}, not in the catalogue (used by {_needed_by(tasks)})"
        for sku_id, tasks in unknown_skus.items()
    ]
    problems += [
        f"{reason} (needed by {_needed_by(tasks)})"
        for reason, tasks in price_problems.values()
    ]
    return problems
