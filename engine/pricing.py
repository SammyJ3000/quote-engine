from decimal import Decimal

from engine.clientconfig import ClientConfig
from engine.models import MaterialLine, ResolvedMaterial, ResolvedTask, TaskLine
from engine.money import round_money
from engine.prices import PriceBook


def _cost_material(material: ResolvedMaterial, client: ClientConfig, book: PriceBook) -> MaterialLine:
    sku = material.sku
    list_price = book.list_price(sku.id)
    discount = client.discounts.for_sku(sku)
    unit_net = round_money(list_price * (Decimal("1") - discount))

    return MaterialLine(
        sku_id=sku.id,
        name=sku.name,
        category=sku.category,
        unit=sku.unit,
        raw_qty=material.raw_qty,
        units=material.units,
        list_price=list_price,
        discount=discount,
        unit_net=unit_net,
        cost=round_money(material.units * unit_net),
    )


def cost_tasks(
    tasks: tuple[ResolvedTask, ...], client: ClientConfig, book: PriceBook
) -> tuple[TaskLine, ...]:
    """Attach money to resolved tasks. Raises MissingPriceError if any SKU is unpriced,
    or RecipeError if a task's trade has no day rate in the client config."""
    lines: list[TaskLine] = []

    for task in tasks:
        day_rate = client.day_rate(task.trade)
        lines.append(
            TaskLine(
                id=task.id,
                label=task.label,
                trade=task.trade,
                days=task.days,
                day_rate=day_rate,
                labour_cost=round_money(task.days * day_rate),
                materials=tuple(_cost_material(m, client, book) for m in task.materials),
            )
        )

    return tuple(lines)
