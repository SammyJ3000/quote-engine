from decimal import Decimal

import pytest

from engine.clientconfig import ClientConfig
from engine.errors import MissingPriceError, RecipeError
from engine.models import ResolvedMaterial, ResolvedTask, Sku
from engine.prices import DiscountMatrix, PriceBook
from engine.pricing import cost_tasks


@pytest.fixture
def client():
    return ClientConfig(
        slug="test",
        day_rates={"tiler": Decimal("260"), "labourer": Decimal("160")},
        discounts=DiscountMatrix(
            default=Decimal("0.15"),
            by_category={"finishes": Decimal("0.20"), "plant": Decimal("0")},
            by_sku={},
        ),
        overhead_margin=Decimal("0.22"),
        contingency=Decimal("0.05"),
        quote_band=Decimal("0.08"),
        vat_rate=Decimal("0.20"),
        display_rounding=50,
    )


@pytest.fixture
def book():
    return PriceBook(
        captured="2026-08-20",
        prices={
            "tile-mid": {"list": 24.99, "unit": "m2"},
            "skip-6yd": {"list": 260.00, "unit": "each"},
        },
    )


TILE = Sku(id="tile-mid", name="Tile", unit="m2", category="finishes")
SKIP = Sku(id="skip-6yd", name="Skip", unit="each", category="plant", discrete=True)


def test_labour_cost_is_days_times_day_rate(client, book):
    tasks = [ResolvedTask(id="t", label="Tiling", trade="tiler", days=Decimal("3.5"))]
    line = cost_tasks(tuple(tasks), client, book)[0]
    assert line.labour_cost == Decimal("910.00")


def test_material_cost_applies_the_discount(client, book):
    tasks = [
        ResolvedTask(
            id="t", label="Tiling", trade="tiler", days=Decimal("0"),
            materials=(ResolvedMaterial(sku=TILE, raw_qty=Decimal("20"), units=Decimal("22")),),
        )
    ]
    line = cost_tasks(tuple(tasks), client, book)[0]
    material = line.materials[0]
    # 24.99 * (1 - 0.20) = 19.992 -> 19.99 per m2; 22 * 19.99 = 439.78
    assert material.unit_net == Decimal("19.99")
    assert material.cost == Decimal("439.78")


def test_zero_discount_category_pays_list(client, book):
    tasks = [
        ResolvedTask(
            id="t", label="Strip", trade="labourer", days=Decimal("0"),
            materials=(ResolvedMaterial(sku=SKIP, raw_qty=Decimal("1"), units=Decimal("1")),),
        )
    ]
    assert cost_tasks(tuple(tasks), client, book)[0].materials[0].cost == Decimal("260.00")


def test_task_material_cost_sums_its_lines(client, book):
    tasks = [
        ResolvedTask(
            id="t", label="Mixed", trade="tiler", days=Decimal("1"),
            materials=(
                ResolvedMaterial(sku=TILE, raw_qty=Decimal("10"), units=Decimal("10")),
                ResolvedMaterial(sku=SKIP, raw_qty=Decimal("1"), units=Decimal("1")),
            ),
        )
    ]
    line = cost_tasks(tuple(tasks), client, book)[0]
    assert line.material_cost == Decimal("199.90") + Decimal("260.00")


def test_money_fields_are_decimal_not_float(client, book):
    """Decimal("5") == 5.0 is True in Python, so equality alone would not catch
    a regression where a money field silently became a float. Pin the type."""
    tasks = [
        ResolvedTask(
            id="t", label="Tiling", trade="tiler", days=Decimal("3.5"),
            materials=(ResolvedMaterial(sku=TILE, raw_qty=Decimal("20"), units=Decimal("22")),),
        )
    ]
    line = cost_tasks(tuple(tasks), client, book)[0]
    assert isinstance(line.labour_cost, Decimal)
    assert isinstance(line.day_rate, Decimal)
    assert isinstance(line.material_cost, Decimal)
    material = line.materials[0]
    assert isinstance(material.list_price, Decimal)
    assert isinstance(material.discount, Decimal)
    assert isinstance(material.unit_net, Decimal)
    assert isinstance(material.cost, Decimal)


def test_missing_price_raises_missing_price_error_naming_the_sku(client, book):
    unpriced = Sku(id="ghost-sku", name="Ghost", unit="each", category="finishes")
    tasks = [
        ResolvedTask(
            id="t", label="Ghost task", trade="tiler", days=Decimal("0"),
            materials=(ResolvedMaterial(sku=unpriced, raw_qty=Decimal("1"), units=Decimal("1")),),
        )
    ]
    with pytest.raises(MissingPriceError, match="ghost-sku"):
        cost_tasks(tuple(tasks), client, book)


def test_missing_day_rate_raises_recipe_error_naming_the_trade(client, book):
    tasks = [ResolvedTask(id="t", label="Plumbing", trade="plumber", days=Decimal("1"))]
    with pytest.raises(RecipeError, match="plumber"):
        cost_tasks(tuple(tasks), client, book)
