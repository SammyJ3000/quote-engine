from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Sku:
    id: str
    name: str
    unit: str
    category: str
    discrete: bool = False
    coverage_per_unit: Decimal | None = None
    tiers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedMaterial:
    sku: Sku                 # already tier-resolved
    raw_qty: Decimal         # before waste
    units: Decimal           # after waste, coverage conversion and rounding


@dataclass(frozen=True)
class ResolvedTask:
    id: str
    label: str
    trade: str
    days: Decimal
    materials: tuple[ResolvedMaterial, ...] = ()


@dataclass(frozen=True)
class MaterialLine:
    sku_id: str
    name: str
    category: str
    unit: str
    raw_qty: Decimal
    units: Decimal
    list_price: Decimal
    discount: Decimal
    unit_net: Decimal
    cost: Decimal


@dataclass(frozen=True)
class TaskLine:
    id: str
    label: str
    trade: str
    days: Decimal
    day_rate: Decimal
    labour_cost: Decimal
    materials: tuple[MaterialLine, ...] = ()

    @property
    def material_cost(self) -> Decimal:
        return sum((m.cost for m in self.materials), Decimal("0"))


@dataclass(frozen=True)
class QuoteTotals:
    labour_cost: Decimal
    material_cost: Decimal      # excludes plant
    plant_cost: Decimal
    direct_cost: Decimal
    contingency: Decimal
    cost_base: Decimal
    net_price: Decimal
    vat: Decimal
    gross: Decimal
    low: Decimal
    high: Decimal


@dataclass(frozen=True)
class QuoteResult:
    recipe_id: str
    recipe_label: str
    client_slug: str
    price_book_captured: str
    parameters: dict
    derived: dict
    tasks: tuple[TaskLine, ...]
    totals: QuoteTotals
