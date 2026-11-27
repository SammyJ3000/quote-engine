from decimal import Decimal

import pytest

from engine.clientconfig import ClientConfig
from engine.models import MaterialLine, TaskLine
from engine.prices import DiscountMatrix
from engine.totals import total_quote


@pytest.fixture
def client():
    return ClientConfig(
        slug="test",
        day_rates={},
        discounts=DiscountMatrix(default=Decimal("0"), by_category={}, by_sku={}),
        overhead_margin=Decimal("0.20"),
        contingency=Decimal("0.05"),
        quote_band=Decimal("0.10"),
        vat_rate=Decimal("0.20"),
        display_rounding=50,
    )


def _material(cost, category="finishes"):
    return MaterialLine(
        sku_id="x", name="X", category=category, unit="m2",
        raw_qty=Decimal("1"), units=Decimal("1"),
        list_price=Decimal(cost), discount=Decimal("0"),
        unit_net=Decimal(cost), cost=Decimal(cost),
    )


@pytest.fixture
def lines():
    return (
        TaskLine(
            id="a", label="A", trade="tiler", days=Decimal("1"),
            day_rate=Decimal("1000"), labour_cost=Decimal("1000"),
            materials=(_material("400"), _material("200", category="plant")),
        ),
    )


def test_labour_and_materials_split_plant_out(lines, client):
    totals = total_quote(lines, client)
    assert totals.labour_cost == Decimal("1000")
    assert totals.material_cost == Decimal("400")     # excludes plant
    assert totals.plant_cost == Decimal("200")


def test_direct_cost_is_labour_plus_materials_plus_plant(lines, client):
    assert total_quote(lines, client).direct_cost == Decimal("1600")


def test_contingency_then_margin_then_vat_in_that_order(lines, client):
    totals = total_quote(lines, client)
    assert totals.contingency == Decimal("80.00")     # 1600 * 0.05
    assert totals.cost_base == Decimal("1680.00")
    assert totals.net_price == Decimal("2016.00")     # 1680 * 1.20
    assert totals.vat == Decimal("403.20")            # 2016 * 0.20
    assert totals.gross == Decimal("2419.20")


def test_range_is_banded_and_rounded_to_display_step(lines, client):
    totals = total_quote(lines, client)
    # 2419.20 -/+ 10% = 2177.28 / 2661.12, rounded to nearest 50
    assert totals.low == Decimal("2200")
    assert totals.high == Decimal("2650")


def test_empty_quote_is_zero_not_an_error(client):
    totals = total_quote((), client)
    assert totals.gross == Decimal("0.00")
    assert totals.low == Decimal("0")


def test_money_fields_are_decimal_not_float(lines, client):
    totals = total_quote(lines, client)
    for field in (
        totals.labour_cost, totals.material_cost, totals.plant_cost,
        totals.direct_cost, totals.contingency, totals.cost_base,
        totals.net_price, totals.vat, totals.gross, totals.low, totals.high,
    ):
        assert isinstance(field, Decimal)


def test_material_and_plant_cost_together_account_for_every_material_line(lines, client):
    totals = total_quote(lines, client)
    all_material_cost = sum(
        (m.cost for line in lines for m in line.materials), Decimal("0")
    )
    assert totals.material_cost + totals.plant_cost == all_material_cost
