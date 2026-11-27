from decimal import Decimal

from engine.clientconfig import ClientConfig
from engine.models import QuoteTotals, TaskLine
from engine.money import round_money, round_to_nearest

PLANT = "plant"


def total_quote(lines: tuple[TaskLine, ...], client: ClientConfig) -> QuoteTotals:
    """Roll costed task lines up into the numbers a customer sees.

    Order matters and is fixed: direct cost -> contingency -> overhead and
    margin -> VAT -> display band.
    """
    labour = sum((line.labour_cost for line in lines), Decimal("0"))
    materials = sum(
        (m.cost for line in lines for m in line.materials if m.category != PLANT), Decimal("0")
    )
    plant = sum(
        (m.cost for line in lines for m in line.materials if m.category == PLANT), Decimal("0")
    )

    direct = labour + materials + plant
    contingency = round_money(direct * client.contingency)
    cost_base = direct + contingency
    net = round_money(cost_base * (Decimal("1") + client.overhead_margin))
    vat = round_money(net * client.vat_rate)
    gross = net + vat

    return QuoteTotals(
        labour_cost=labour,
        material_cost=materials,
        plant_cost=plant,
        direct_cost=direct,
        contingency=contingency,
        cost_base=cost_base,
        net_price=net,
        vat=vat,
        gross=gross,
        low=round_to_nearest(gross * (Decimal("1") - client.quote_band), client.display_rounding),
        high=round_to_nearest(gross * (Decimal("1") + client.quote_band), client.display_rounding),
    )
