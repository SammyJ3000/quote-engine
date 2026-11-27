# Quote Engine Implementation Plan (Plan 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A deterministic quoting engine that turns a job archetype plus parameters into a costed, VAT-inclusive price range, driven from a CLI and covered by hand-checked golden tests.

**Architecture:** Recipes, catalogue, price book and client config are all YAML/JSON data loaded and validated at startup. A restricted expression evaluator computes quantities from parameters. Pricing, totals and VAT are pure functions over typed dataclasses. No LLM, no network, no web framework in this plan.

**Tech Stack:** Python 3.12 · PyYAML · simpleeval · pytest · uv

## Global Constraints

- Python `>=3.12`. Managed with `uv`. Run everything via `uv run`.
- **All money is `decimal.Decimal`.** Never `float` for money. Quantize only at display.
- **The engine performs every calculation.** No LLM code in `engine/`.
- **No network calls anywhere in `engine/`.** Only `scripts/harvest_prices.py` may use the network.
- Money rounds with `ROUND_HALF_UP`, not banker's rounding.
- A missing price is a hard error (`MissingPriceError`), never a silent zero.
- Lookup tables live in a recipe's `constants:` block, never inline in an expression.
- Currency is GBP. VAT default 20%. Region: Northwest England.
- Every task ends with a passing test run and a commit.

---

## File Structure

| File | Responsibility |
|---|---|
| `engine/errors.py` | Exception types shared across the engine |
| `engine/money.py` | `Money` helpers: `to_decimal`, `round_money`, `round_to_nearest` |
| `engine/quantities.py` | Restricted formula evaluation |
| `engine/models.py` | Frozen dataclasses: `Sku`, `MaterialLine`, `TaskLine`, `QuoteResult` |
| `engine/catalogue.py` | Load + validate SKU definitions, resolve spec tiers |
| `engine/prices.py` | Load a dated price book, resolve per-client discounts |
| `engine/clientconfig.py` | Load `labour.yaml`, `discounts.yaml`, `commercial.yaml` |
| `engine/recipes.py` | Load + validate recipe files |
| `engine/quantify.py` | Parameters -> derived values -> resolved tasks with quantities (no money) |
| `engine/pricing.py` | Resolved tasks -> costed `TaskLine`s |
| `engine/totals.py` | Costed lines -> contingency, margin, VAT, range |
| `engine/quote.py` | `build_quote()` — the one public entry point |
| `scripts/quote_cli.py` | CLI wrapper |
| `scripts/harvest_prices.py` | One-off price capture -> dated price book |

---

### Task 1: Project scaffold and the safe formula evaluator

**Files:**
- Create: `pyproject.toml`, `engine/__init__.py`, `engine/errors.py`, `engine/quantities.py`
- Test: `tests/test_quantities.py`

**Interfaces:**
- Consumes: nothing
- Produces: `evaluate(expr: str, namespace: dict) -> float`, `FormulaError`

- [ ] **Step 1: Create the project scaffold**

`pyproject.toml`:

```toml
[project]
name = "quote-agent"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["pyyaml>=6.0", "simpleeval>=1.0"]

[dependency-groups]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Then:

```bash
touch engine/__init__.py agent/__init__.py tests/__init__.py
uv sync
```

`engine/errors.py`:

```python
class QuoteError(Exception):
    """Base class for all engine errors."""


class FormulaError(QuoteError):
    """A recipe expression could not be evaluated safely."""


class MissingPriceError(QuoteError):
    """A SKU used by a recipe has no price in the active price book."""


class RecipeError(QuoteError):
    """A recipe file is malformed or references something that does not exist."""


class ParameterError(QuoteError):
    """Supplied job parameters are missing or out of range."""
```

- [ ] **Step 2: Write the failing test**

`tests/test_quantities.py`:

```python
import pytest

from engine.errors import FormulaError
from engine.quantities import evaluate


def test_arithmetic():
    assert evaluate("2 * (3 + 4)", {}) == 14


def test_reads_names_from_namespace():
    assert evaluate("length_m * width_m", {"length_m": 2.4, "width_m": 1.8}) == pytest.approx(4.32)


def test_indexes_a_constant_lookup_table():
    ns = {"tiling_factor": {"full-height": 1.0, "half-height": 0.5}, "tiling_extent": "half-height"}
    assert evaluate("tiling_factor[tiling_extent]", ns) == 0.5


def test_ceil_is_available():
    assert evaluate("ceil(4.2 / 5)", {}) == 1


def test_rejects_attribute_access():
    with pytest.raises(FormulaError):
        evaluate("x.__class__", {"x": 1})


def test_rejects_unknown_names():
    with pytest.raises(FormulaError):
        evaluate("__import__('os')", {})


def test_rejects_unknown_key_with_a_useful_message():
    ns = {"t": {"a": 1.0}, "k": "b"}
    with pytest.raises(FormulaError) as exc:
        evaluate("t[k]", ns)
    assert "b" in str(exc.value)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_quantities.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.quantities'`

- [ ] **Step 4: Write the implementation**

`engine/quantities.py`:

```python
import ast
import math

from simpleeval import SimpleEval
from simpleeval import InvalidExpression

from engine.errors import FormulaError

SAFE_FUNCTIONS = {
    "ceil": math.ceil,
    "floor": math.floor,
    "round": round,
    "min": min,
    "max": max,
    "abs": abs,
}


def _build_evaluator(namespace: dict) -> SimpleEval:
    evaluator = SimpleEval(names=dict(namespace), functions=dict(SAFE_FUNCTIONS))
    # Recipes are data. Data must not reach into objects.
    evaluator.nodes.pop(ast.Attribute, None)
    return evaluator


def evaluate(expr: str, namespace: dict) -> float:
    """Evaluate a recipe expression against a whitelisted namespace.

    Only arithmetic, comparisons, subscripting and SAFE_FUNCTIONS are permitted.
    """
    if not isinstance(expr, str):
        # YAML gives us a bare number for constant allowances like `days: 1.5`.
        return expr

    evaluator = _build_evaluator(namespace)
    try:
        return evaluator.eval(expr)
    except InvalidExpression as exc:
        raise FormulaError(f"{expr!r}: {exc}") from exc
    except KeyError as exc:
        raise FormulaError(f"{expr!r}: no such key {exc}") from exc
    except Exception as exc:
        raise FormulaError(f"{expr!r}: {exc}") from exc
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_quantities.py -v`
Expected: PASS, 7 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock engine/ agent/__init__.py tests/
git commit -m "feat: project scaffold and restricted formula evaluator"
```

---

### Task 2: Money helpers

**Files:**
- Create: `engine/money.py`
- Test: `tests/test_money.py`

**Interfaces:**
- Consumes: nothing
- Produces: `to_decimal(value) -> Decimal`, `round_money(Decimal) -> Decimal`, `round_to_nearest(Decimal, int) -> Decimal`

- [ ] **Step 1: Write the failing test**

`tests/test_money.py`:

```python
from decimal import Decimal

from engine.money import round_money, round_to_nearest, to_decimal


def test_to_decimal_from_float_does_not_leak_binary_error():
    assert to_decimal(24.99) == Decimal("24.99")


def test_to_decimal_passes_decimals_through():
    assert to_decimal(Decimal("10.5")) == Decimal("10.5")


def test_round_money_uses_half_up_not_bankers():
    assert round_money(Decimal("2.125")) == Decimal("2.13")
    assert round_money(Decimal("2.135")) == Decimal("2.14")


def test_round_to_nearest_fifty():
    assert round_to_nearest(Decimal("8421.00"), 50) == Decimal("8400")
    assert round_to_nearest(Decimal("8426.00"), 50) == Decimal("8450")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_money.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.money'`

- [ ] **Step 3: Write the implementation**

`engine/money.py`:

```python
from decimal import Decimal, ROUND_HALF_UP

PENNY = Decimal("0.01")


def to_decimal(value) -> Decimal:
    """Convert a YAML/JSON number to Decimal without inheriting float error."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_money(value: Decimal) -> Decimal:
    """Round to whole pence, half up — the convention people expect on an invoice."""
    return value.quantize(PENNY, rounding=ROUND_HALF_UP)


def round_to_nearest(value: Decimal, step: int) -> Decimal:
    """Round to the nearest `step` pounds, for display. Reads like a builder's quote."""
    step_dec = Decimal(step)
    return (value / step_dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step_dec
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_money.py -v`
Expected: PASS, 4 passed

- [ ] **Step 5: Commit**

```bash
git add engine/money.py tests/test_money.py
git commit -m "feat: decimal money helpers with half-up rounding"
```

---

### Task 3: Catalogue loader and tier resolution

**Files:**
- Create: `engine/models.py`, `engine/catalogue.py`, `catalogue/materials.yaml`
- Test: `tests/test_catalogue.py`

**Interfaces:**
- Consumes: `to_decimal` (Task 2), `RecipeError` (Task 1)
- Produces: `Sku` dataclass; `Catalogue` with `.get(sku_id) -> Sku` and `.resolve_tier(sku_id, tier) -> Sku`; `load_catalogue(path) -> Catalogue`

- [ ] **Step 1: Write the failing test**

`tests/test_catalogue.py`:

```python
from decimal import Decimal

import pytest

from engine.catalogue import load_catalogue
from engine.errors import RecipeError

FIXTURE = """
- id: tile-ceramic-mid
  name: Ceramic wall tile, mid range
  unit: m2
  category: finishes
  tiers:
    budget: tile-ceramic-budget
    premium: tile-porcelain-premium

- id: tile-ceramic-budget
  name: Ceramic wall tile, budget
  unit: m2
  category: finishes

- id: tile-porcelain-premium
  name: Porcelain wall tile, premium
  unit: m2
  category: finishes

- id: adhesive-flexible-20kg
  name: Flexible tile adhesive 20kg
  unit: bag
  category: finishes
  discrete: true
  coverage:
    unit: m2
    per_unit: 4.5
"""


@pytest.fixture
def catalogue(tmp_path):
    path = tmp_path / "materials.yaml"
    path.write_text(FIXTURE)
    return load_catalogue(path)


def test_loads_a_sku(catalogue):
    sku = catalogue.get("tile-ceramic-mid")
    assert sku.name == "Ceramic wall tile, mid range"
    assert sku.category == "finishes"
    assert sku.unit == "m2"


def test_coverage_is_decimal(catalogue):
    assert catalogue.get("adhesive-flexible-20kg").coverage_per_unit == Decimal("4.5")


def test_discrete_defaults_to_false(catalogue):
    assert catalogue.get("tile-ceramic-mid").discrete is False
    assert catalogue.get("adhesive-flexible-20kg").discrete is True


def test_resolve_tier_swaps_the_sku(catalogue):
    assert catalogue.resolve_tier("tile-ceramic-mid", "premium").id == "tile-porcelain-premium"


def test_resolve_tier_falls_back_to_base_when_tier_absent(catalogue):
    assert catalogue.resolve_tier("tile-ceramic-mid", "mid").id == "tile-ceramic-mid"


def test_ids_lists_every_sku_sorted(catalogue):
    assert catalogue.ids() == [
        "adhesive-flexible-20kg",
        "tile-ceramic-budget",
        "tile-ceramic-mid",
        "tile-porcelain-premium",
    ]


def test_unknown_sku_raises(catalogue):
    with pytest.raises(RecipeError) as exc:
        catalogue.get("does-not-exist")
    assert "does-not-exist" in str(exc.value)


def test_tier_pointing_at_a_missing_sku_fails_at_load(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "- id: a\n  name: A\n  unit: m2\n  category: finishes\n  tiers:\n    premium: nope\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_catalogue(path)
    assert "nope" in str(exc.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_catalogue.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.catalogue'`

- [ ] **Step 3: Write the models**

`engine/models.py`:

```python
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
```

- [ ] **Step 4: Write the catalogue loader**

`engine/catalogue.py`:

```python
from pathlib import Path

import yaml

from engine.errors import RecipeError
from engine.models import Sku
from engine.money import to_decimal

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


def load_catalogue(path: str | Path) -> Catalogue:
    raw = yaml.safe_load(Path(path).read_text()) or []
    skus: dict[str, Sku] = {}

    for entry in raw:
        missing = [f for f in REQUIRED_FIELDS if f not in entry]
        if missing:
            raise RecipeError(f"SKU {entry.get('id', '<no id>')!r} missing fields: {missing}")
        if entry["id"] in skus:
            raise RecipeError(f"duplicate SKU id {entry['id']!r}")

        coverage = entry.get("coverage")
        skus[entry["id"]] = Sku(
            id=entry["id"],
            name=entry["name"],
            unit=entry["unit"],
            category=entry["category"],
            discrete=bool(entry.get("discrete", False)),
            coverage_per_unit=to_decimal(coverage["per_unit"]) if coverage else None,
            tiers=dict(entry.get("tiers", {})),
        )

    # Tier targets must exist, and we can only know that once everything is loaded.
    for sku in skus.values():
        for tier, target in sku.tiers.items():
            if target not in skus:
                raise RecipeError(f"SKU {sku.id!r} tier {tier!r} points at unknown SKU {target!r}")

    return Catalogue(skus)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_catalogue.py -v`
Expected: PASS, 8 passed

- [ ] **Step 6: Commit**

```bash
git add engine/models.py engine/catalogue.py tests/test_catalogue.py
git commit -m "feat: catalogue loader with tier resolution and load-time validation"
```

---

### Task 4: Price book and discount resolution

**Files:**
- Create: `engine/prices.py`
- Test: `tests/test_prices.py`

**Interfaces:**
- Consumes: `Sku` (Task 3), `to_decimal` (Task 2), `MissingPriceError` (Task 1)
- Produces: `PriceBook` with `.list_price(sku_id) -> Decimal` and `.captured -> str`; `load_price_book(path) -> PriceBook`; `DiscountMatrix` with `.for_sku(Sku) -> Decimal`; `load_discounts(path) -> DiscountMatrix`

- [ ] **Step 1: Write the failing test**

`tests/test_prices.py`:

```python
import json
from decimal import Decimal

import pytest

from engine.errors import MissingPriceError
from engine.models import Sku
from engine.prices import load_discounts, load_price_book

BOOK = {
    "captured": "2026-08-20",
    "prices": {
        "tile-ceramic-mid": {"list": 24.99, "unit": "m2", "source": "x", "method": "scraped"},
    },
}

DISCOUNTS = """
default: 0.15
by_category:
  finishes: 0.20
  plant: 0.0
by_sku:
  tile-ceramic-mid: 0.30
"""


@pytest.fixture
def book(tmp_path):
    path = tmp_path / "2026-08-20.json"
    path.write_text(json.dumps(BOOK))
    return load_price_book(path)


@pytest.fixture
def discounts(tmp_path):
    path = tmp_path / "discounts.yaml"
    path.write_text(DISCOUNTS)
    return load_discounts(path)


def test_list_price_is_decimal(book):
    assert book.list_price("tile-ceramic-mid") == Decimal("24.99")


def test_captured_date_is_available(book):
    assert book.captured == "2026-08-20"


def test_missing_price_raises_and_names_the_sku(book):
    with pytest.raises(MissingPriceError) as exc:
        book.list_price("skip-6yd")
    assert "skip-6yd" in str(exc.value)


def _sku(sku_id, category):
    return Sku(id=sku_id, name=sku_id, unit="m2", category=category)


def test_by_sku_wins_over_category(discounts):
    assert discounts.for_sku(_sku("tile-ceramic-mid", "finishes")) == Decimal("0.30")


def test_category_wins_over_default(discounts):
    assert discounts.for_sku(_sku("other-tile", "finishes")) == Decimal("0.20")


def test_falls_back_to_default(discounts):
    assert discounts.for_sku(_sku("timber-c16", "timber")) == Decimal("0.15")


def test_zero_category_discount_is_respected_not_treated_as_absent(discounts):
    assert discounts.for_sku(_sku("skip-6yd", "plant")) == Decimal("0")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_prices.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.prices'`

- [ ] **Step 3: Write the implementation**

`engine/prices.py`:

```python
import json
from decimal import Decimal
from pathlib import Path

import yaml

from engine.errors import MissingPriceError
from engine.models import Sku
from engine.money import to_decimal


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
        return to_decimal(entry["list"])

    def method(self, sku_id: str) -> str:
        return self._prices.get(sku_id, {}).get("method", "unknown")

    def __contains__(self, sku_id: str) -> bool:
        return sku_id in self._prices


def load_price_book(path: str | Path) -> PriceBook:
    raw = json.loads(Path(path).read_text())
    return PriceBook(captured=raw["captured"], prices=raw["prices"])


def latest_price_book(directory: str | Path) -> PriceBook:
    """Load the most recent dated price book. Filenames are YYYY-MM-DD.json."""
    books = sorted(Path(directory).glob("*.json"))
    if not books:
        raise MissingPriceError(f"no price books found in {directory}")
    return load_price_book(books[-1])


class DiscountMatrix:
    def __init__(self, default: Decimal, by_category: dict[str, Decimal], by_sku: dict[str, Decimal]):
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


def load_discounts(path: str | Path) -> DiscountMatrix:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return DiscountMatrix(
        default=to_decimal(raw.get("default", 0)),
        by_category={k: to_decimal(v) for k, v in (raw.get("by_category") or {}).items()},
        by_sku={k: to_decimal(v) for k, v in (raw.get("by_sku") or {}).items()},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_prices.py -v`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add engine/prices.py tests/test_prices.py
git commit -m "feat: price book loading and per-client discount resolution"
```

---

### Task 5: Client configuration

**Files:**
- Create: `engine/clientconfig.py`, `clients/demo-nw/labour.yaml`, `clients/demo-nw/discounts.yaml`, `clients/demo-nw/commercial.yaml`
- Test: `tests/test_clientconfig.py`

**Interfaces:**
- Consumes: `load_discounts` (Task 4), `to_decimal` (Task 2)
- Produces: `ClientConfig` with fields `slug`, `day_rates: dict[str, Decimal]`, `discounts: DiscountMatrix`, `overhead_margin`, `contingency`, `quote_band`, `vat_rate`, `display_rounding`; method `.day_rate(trade) -> Decimal`; `load_client(dir) -> ClientConfig`

- [ ] **Step 1: Write the failing test**

`tests/test_clientconfig.py`:

```python
from decimal import Decimal

import pytest

from engine.clientconfig import load_client
from engine.errors import RecipeError


@pytest.fixture
def client_dir(tmp_path):
    d = tmp_path / "demo-nw"
    d.mkdir()
    (d / "labour.yaml").write_text("plumber: 300\ntiler: 260\nlabourer: 160\n")
    (d / "discounts.yaml").write_text("default: 0.15\n")
    (d / "commercial.yaml").write_text(
        "overhead_margin: 0.22\ncontingency: 0.05\nquote_band: 0.08\n"
        "vat_rate: 0.20\ndisplay_rounding: 50\n"
    )
    return d


def test_day_rates_are_decimal(client_dir):
    assert load_client(client_dir).day_rate("plumber") == Decimal("300")


def test_commercial_settings_load(client_dir):
    client = load_client(client_dir)
    assert client.overhead_margin == Decimal("0.22")
    assert client.contingency == Decimal("0.05")
    assert client.quote_band == Decimal("0.08")
    assert client.vat_rate == Decimal("0.20")
    assert client.display_rounding == 50


def test_slug_comes_from_directory_name(client_dir):
    assert load_client(client_dir).slug == "demo-nw"


def test_unknown_trade_raises_and_names_it(client_dir):
    with pytest.raises(RecipeError) as exc:
        load_client(client_dir).day_rate("stonemason")
    assert "stonemason" in str(exc.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_clientconfig.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.clientconfig'`

- [ ] **Step 3: Write the implementation**

`engine/clientconfig.py`:

```python
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from engine.errors import RecipeError
from engine.money import to_decimal
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


def load_client(directory: str | Path) -> ClientConfig:
    d = Path(directory)
    labour = yaml.safe_load((d / "labour.yaml").read_text()) or {}
    commercial = yaml.safe_load((d / "commercial.yaml").read_text()) or {}

    return ClientConfig(
        slug=d.name,
        day_rates={k: to_decimal(v) for k, v in labour.items()},
        discounts=load_discounts(d / "discounts.yaml"),
        overhead_margin=to_decimal(commercial.get("overhead_margin", COMMERCIAL_DEFAULTS["overhead_margin"])),
        contingency=to_decimal(commercial.get("contingency", COMMERCIAL_DEFAULTS["contingency"])),
        quote_band=to_decimal(commercial.get("quote_band", COMMERCIAL_DEFAULTS["quote_band"])),
        vat_rate=to_decimal(commercial.get("vat_rate", COMMERCIAL_DEFAULTS["vat_rate"])),
        display_rounding=int(commercial.get("display_rounding", 50)),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_clientconfig.py -v`
Expected: PASS, 4 passed

- [ ] **Step 5: Create the demo client files**

`clients/demo-nw/labour.yaml` — placeholder rates, replaced with researched figures in Task 13:

```yaml
plumber: 300
tiler: 260
electrician: 320
plasterer: 250
joiner: 280
decorator: 220
floor-layer: 240
labourer: 160
```

`clients/demo-nw/discounts.yaml`:

```yaml
default: 0.15
by_category:
  timber: 0.38
  heavy-side: 0.32
  finishes: 0.20
  sanitaryware: 0.35
  electrical: 0.25
  plumbing: 0.30
  sundries: 0.15
  plant: 0.0
by_sku: {}
```

`clients/demo-nw/commercial.yaml`:

```yaml
overhead_margin: 0.22
contingency: 0.05
quote_band: 0.08
vat_rate: 0.20
display_rounding: 50
```

Spec section 7.3 describes a fourth client file, `branding.yaml`. It is deliberately
not created here — nothing in the engine reads it. It arrives in Plan 2 alongside
the PDF renderer that consumes it.

- [ ] **Step 6: Commit**

```bash
git add engine/clientconfig.py tests/test_clientconfig.py clients/demo-nw/
git commit -m "feat: client configuration loading and demo-nw client files"
```

---

### Task 6: Recipe loader and validation

**Files:**
- Create: `engine/recipes.py`
- Test: `tests/test_recipes.py`

**Interfaces:**
- Consumes: `Catalogue` (Task 3), `RecipeError` (Task 1)
- Produces: `Parameter`, `MaterialSpec`, `TaskSpec`, `Recipe` dataclasses; `load_recipe(path, catalogue) -> Recipe`

- [ ] **Step 1: Write the failing test**

`tests/test_recipes.py`:

```python
import pytest

from engine.catalogue import load_catalogue
from engine.errors import RecipeError
from engine.recipes import load_recipe

CATALOGUE = """
- id: tile-ceramic-mid
  name: Tile
  unit: m2
  category: finishes
- id: skip-6yd
  name: Skip
  unit: each
  category: plant
  discrete: true
"""

RECIPE = """
id: test-job
label: Test job
parameters:
  - { id: length_m, type: number, min: 1.0, max: 6.0 }
  - { id: spec_tier, type: enum, values: [budget, mid, premium] }
  - { id: height_m, type: number, default: 2.4 }
constants:
  tiling_factor: { budget: 0.5, mid: 1.0, premium: 1.0 }
derived:
  tiled_area_m2: length_m * tiling_factor[spec_tier]
tasks:
  - id: strip_out
    label: Strip out
    trade: labourer
    days: 0.5
    materials:
      - { sku: skip-6yd, qty: 1 }
  - id: tiling
    label: Tiling
    trade: tiler
    days: tiled_area_m2 / 6
    materials:
      - { sku: tile-ceramic-mid, qty: tiled_area_m2, waste: 0.10, tier: spec_tier }
"""


@pytest.fixture
def catalogue(tmp_path):
    p = tmp_path / "materials.yaml"
    p.write_text(CATALOGUE)
    return load_catalogue(p)


@pytest.fixture
def recipe(tmp_path, catalogue):
    p = tmp_path / "test-job.yaml"
    p.write_text(RECIPE)
    return load_recipe(p, catalogue)


def test_loads_identity(recipe):
    assert recipe.id == "test-job"
    assert recipe.label == "Test job"


def test_parameters_keep_bounds_and_defaults(recipe):
    params = {p.id: p for p in recipe.parameters}
    assert params["length_m"].min == 1.0
    assert params["length_m"].max == 6.0
    assert params["height_m"].default == 2.4
    assert params["spec_tier"].values == ["budget", "mid", "premium"]


def test_tasks_and_materials_parse(recipe):
    tiling = [t for t in recipe.tasks if t.id == "tiling"][0]
    assert tiling.trade == "tiler"
    assert tiling.materials[0].waste == 0.10
    assert tiling.materials[0].tier_from == "spec_tier"


def test_waste_defaults_to_zero(recipe):
    strip = [t for t in recipe.tasks if t.id == "strip_out"][0]
    assert strip.materials[0].waste == 0.0


def test_unknown_sku_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "id: bad\nlabel: Bad\nparameters: []\ntasks:\n"
        "  - { id: t, label: T, trade: tiler, days: 1, materials: [{ sku: nope, qty: 1 }] }\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    assert "nope" in str(exc.value)


def test_duplicate_task_id_fails_at_load(tmp_path, catalogue):
    p = tmp_path / "dup.yaml"
    p.write_text(
        "id: dup\nlabel: Dup\nparameters: []\ntasks:\n"
        "  - { id: t, label: T, trade: tiler, days: 1 }\n"
        "  - { id: t, label: T2, trade: tiler, days: 1 }\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_recipe(p, catalogue)
    assert "t" in str(exc.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_recipes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.recipes'`

- [ ] **Step 3: Write the implementation**

`engine/recipes.py`:

```python
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from engine.catalogue import Catalogue
from engine.errors import RecipeError


@dataclass(frozen=True)
class Parameter:
    id: str
    type: str                      # "number" | "enum" | "boolean"
    values: list[str] | None = None
    min: float | None = None
    max: float | None = None
    default: object | None = None

    @property
    def required(self) -> bool:
        return self.default is None


@dataclass(frozen=True)
class MaterialSpec:
    sku: str
    qty: str | float
    waste: float = 0.0
    by_coverage: bool = False
    tier_from: str | None = None   # name of the parameter holding the tier


@dataclass(frozen=True)
class TaskSpec:
    id: str
    label: str
    trade: str
    days: str | float
    when: str | None = None
    materials: tuple[MaterialSpec, ...] = ()


@dataclass(frozen=True)
class Recipe:
    id: str
    label: str
    parameters: tuple[Parameter, ...]
    tasks: tuple[TaskSpec, ...]
    constants: dict = field(default_factory=dict)
    derived: dict = field(default_factory=dict)


def _parse_material(raw: dict) -> MaterialSpec:
    return MaterialSpec(
        sku=raw["sku"],
        qty=raw["qty"],
        waste=float(raw.get("waste", 0.0)),
        by_coverage=bool(raw.get("by_coverage", False)),
        tier_from=raw.get("tier"),
    )


def load_recipe(path: str | Path, catalogue: Catalogue) -> Recipe:
    raw = yaml.safe_load(Path(path).read_text())

    for key in ("id", "label", "tasks"):
        if key not in raw:
            raise RecipeError(f"recipe {path} missing required key {key!r}")

    parameters = tuple(
        Parameter(
            id=p["id"],
            type=p["type"],
            values=p.get("values"),
            min=p.get("min"),
            max=p.get("max"),
            default=p.get("default"),
        )
        for p in raw.get("parameters", [])
    )

    tasks: list[TaskSpec] = []
    seen: set[str] = set()
    for t in raw["tasks"]:
        if t["id"] in seen:
            raise RecipeError(f"recipe {raw['id']!r} has duplicate task id {t['id']!r}")
        seen.add(t["id"])
        tasks.append(
            TaskSpec(
                id=t["id"],
                label=t["label"],
                trade=t["trade"],
                days=t["days"],
                when=t.get("when"),
                materials=tuple(_parse_material(m) for m in t.get("materials", [])),
            )
        )

    # Fail at load, not mid-demo.
    for task in tasks:
        for material in task.materials:
            if material.sku not in catalogue:
                raise RecipeError(
                    f"recipe {raw['id']!r} task {task.id!r} references unknown SKU {material.sku!r}"
                )

    return Recipe(
        id=raw["id"],
        label=raw["label"],
        parameters=parameters,
        tasks=tuple(tasks),
        constants=raw.get("constants", {}) or {},
        derived=raw.get("derived", {}) or {},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_recipes.py -v`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
git add engine/recipes.py tests/test_recipes.py
git commit -m "feat: recipe loader validating SKU references at load time"
```

---

### Task 7: Quantification — parameters to quantities, no money

**Files:**
- Create: `engine/quantify.py`
- Modify: `engine/models.py` (append `ResolvedMaterial`, `ResolvedTask`)
- Test: `tests/test_quantify.py`

**Interfaces:**
- Consumes: `Recipe` (Task 6), `Catalogue` (Task 3), `evaluate` (Task 1), `to_decimal` (Task 2), `ParameterError` (Task 1)
- Produces: `resolve_parameters(recipe, supplied) -> dict`, `build_namespace(recipe, params) -> dict`, `quantify(recipe, params, catalogue) -> tuple[ResolvedTask, ...]`

- [ ] **Step 1: Write the failing test**

`tests/test_quantify.py`:

```python
from decimal import Decimal

import pytest

from engine.catalogue import load_catalogue
from engine.errors import ParameterError
from engine.quantify import build_namespace, quantify, resolve_parameters
from engine.recipes import load_recipe

CATALOGUE = """
- id: tile-mid
  name: Tile mid
  unit: m2
  category: finishes
  tiers: { premium: tile-premium }
- id: tile-premium
  name: Tile premium
  unit: m2
  category: finishes
- id: adhesive-20kg
  name: Adhesive 20kg
  unit: bag
  category: finishes
  discrete: true
  coverage: { unit: m2, per_unit: 4.5 }
- id: skip-6yd
  name: Skip
  unit: each
  category: plant
  discrete: true
"""

RECIPE = """
id: test-job
label: Test job
parameters:
  - { id: length_m, type: number, min: 1.0, max: 6.0 }
  - { id: width_m, type: number, min: 1.0, max: 6.0 }
  - { id: spec_tier, type: enum, values: [budget, mid, premium] }
  - { id: shower_type, type: enum, values: [over-bath, walk-in] }
  - { id: height_m, type: number, default: 2.4 }
constants:
  wall_factor: { budget: 0.5, mid: 1.0, premium: 1.0 }
derived:
  floor_area_m2: length_m * width_m
  tiled_area_m2: 2 * (length_m + width_m) * height_m * wall_factor[spec_tier]
tasks:
  - id: strip_out
    label: Strip out
    trade: labourer
    days: 0.5
    materials:
      - { sku: skip-6yd, qty: 1 }
  - id: tanking
    label: Tanking
    trade: tiler
    when: shower_type != 'over-bath'
    days: 0.5
  - id: tiling
    label: Tiling
    trade: tiler
    days: tiled_area_m2 / 6
    materials:
      - { sku: tile-mid, qty: tiled_area_m2, waste: 0.10, tier: spec_tier }
      - { sku: adhesive-20kg, qty: tiled_area_m2, by_coverage: true }
"""

BASE = {
    "length_m": 2.4,
    "width_m": 1.8,
    "spec_tier": "mid",
    "shower_type": "walk-in",
}


@pytest.fixture
def catalogue(tmp_path):
    p = tmp_path / "materials.yaml"
    p.write_text(CATALOGUE)
    return load_catalogue(p)


@pytest.fixture
def recipe(tmp_path, catalogue):
    p = tmp_path / "test-job.yaml"
    p.write_text(RECIPE)
    return load_recipe(p, catalogue)


def test_defaults_are_applied(recipe):
    assert resolve_parameters(recipe, BASE)["height_m"] == 2.4


def test_missing_required_parameter_raises(recipe):
    with pytest.raises(ParameterError) as exc:
        resolve_parameters(recipe, {"length_m": 2.4})
    assert "width_m" in str(exc.value)


def test_number_out_of_range_raises(recipe):
    with pytest.raises(ParameterError) as exc:
        resolve_parameters(recipe, BASE | {"length_m": 99})
    assert "length_m" in str(exc.value)


def test_enum_outside_allowed_values_raises(recipe):
    with pytest.raises(ParameterError) as exc:
        resolve_parameters(recipe, BASE | {"spec_tier": "gold"})
    assert "gold" in str(exc.value)


def test_unknown_parameter_raises(recipe):
    with pytest.raises(ParameterError) as exc:
        resolve_parameters(recipe, BASE | {"colour": "blue"})
    assert "colour" in str(exc.value)


def test_derived_values_compute(recipe):
    ns = build_namespace(recipe, resolve_parameters(recipe, BASE))
    assert ns["floor_area_m2"] == pytest.approx(4.32)
    # 2 * (2.4 + 1.8) * 2.4 * 1.0
    assert ns["tiled_area_m2"] == pytest.approx(20.16)


def test_when_false_drops_the_task(recipe, catalogue):
    tasks = quantify(recipe, resolve_parameters(recipe, BASE | {"shower_type": "over-bath"}), catalogue)
    assert "tanking" not in {t.id for t in tasks}


def test_when_true_keeps_the_task(recipe, catalogue):
    tasks = quantify(recipe, resolve_parameters(recipe, BASE), catalogue)
    assert "tanking" in {t.id for t in tasks}


def test_days_are_decimal(recipe, catalogue):
    tasks = {t.id: t for t in quantify(recipe, resolve_parameters(recipe, BASE), catalogue)}
    assert tasks["tiling"].days == pytest.approx(Decimal("3.36"), abs=Decimal("0.01"))


def test_waste_is_applied(recipe, catalogue):
    tasks = {t.id: t for t in quantify(recipe, resolve_parameters(recipe, BASE), catalogue)}
    tile = tasks["tiling"].materials[0]
    assert tile.raw_qty == pytest.approx(Decimal("20.16"), abs=Decimal("0.01"))
    assert tile.units == pytest.approx(Decimal("22.176"), abs=Decimal("0.01"))


def test_coverage_converts_to_whole_bags(recipe, catalogue):
    tasks = {t.id: t for t in quantify(recipe, resolve_parameters(recipe, BASE), catalogue)}
    adhesive = tasks["tiling"].materials[1]
    # 20.16 m2 / 4.5 m2 per bag = 4.48 -> 5 bags
    assert adhesive.units == Decimal("5")


def test_tier_swaps_the_sku(recipe, catalogue):
    tasks = {t.id: t for t in quantify(recipe, resolve_parameters(recipe, BASE | {"spec_tier": "premium"}), catalogue)}
    assert tasks["tiling"].materials[0].sku.id == "tile-premium"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_quantify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.quantify'`

- [ ] **Step 3: Append the resolved models**

Append to `engine/models.py`:

```python
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
```

- [ ] **Step 4: Write the implementation**

`engine/quantify.py`:

```python
import math
from decimal import Decimal

from engine.catalogue import Catalogue
from engine.errors import ParameterError, RecipeError
from engine.models import ResolvedMaterial, ResolvedTask
from engine.money import to_decimal
from engine.quantities import evaluate
from engine.recipes import MaterialSpec, Recipe


def resolve_parameters(recipe: Recipe, supplied: dict) -> dict:
    """Validate supplied parameters against the recipe and fill in defaults."""
    declared = {p.id: p for p in recipe.parameters}

    unknown = set(supplied) - set(declared)
    if unknown:
        raise ParameterError(f"unknown parameters for recipe {recipe.id!r}: {sorted(unknown)}")

    resolved: dict = {}
    for param_id, param in declared.items():
        if param_id in supplied:
            value = supplied[param_id]
        elif param.default is not None:
            value = param.default
        else:
            raise ParameterError(f"missing required parameter {param_id!r}")

        if param.type == "number":
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ParameterError(f"parameter {param_id!r} must be a number, got {value!r}") from None
            if param.min is not None and value < param.min:
                raise ParameterError(f"parameter {param_id!r} value {value} below minimum {param.min}")
            if param.max is not None and value > param.max:
                raise ParameterError(f"parameter {param_id!r} value {value} above maximum {param.max}")
        elif param.type == "enum":
            if value not in (param.values or []):
                raise ParameterError(
                    f"parameter {param_id!r} value {value!r} not one of {param.values}"
                )
        elif param.type == "boolean":
            value = bool(value)

        resolved[param_id] = value

    return resolved


def build_namespace(recipe: Recipe, params: dict) -> dict:
    """Constants, then parameters, then derived values computed in declaration order."""
    namespace = dict(recipe.constants)
    namespace.update(params)
    for name, expr in recipe.derived.items():
        namespace[name] = evaluate(expr, namespace)
    return namespace


def _units_for(spec: MaterialSpec, sku, raw_qty: Decimal) -> Decimal:
    with_waste = raw_qty * (Decimal("1") + to_decimal(spec.waste))

    if spec.by_coverage:
        if sku.coverage_per_unit is None:
            raise RecipeError(f"SKU {sku.id!r} used with by_coverage but has no coverage defined")
        return Decimal(math.ceil(with_waste / sku.coverage_per_unit))

    if sku.discrete:
        return Decimal(math.ceil(with_waste))

    return with_waste


def quantify(recipe: Recipe, params: dict, catalogue: Catalogue) -> tuple[ResolvedTask, ...]:
    """Turn a recipe plus parameters into tasks with quantities. Touches no prices."""
    namespace = build_namespace(recipe, params)
    resolved: list[ResolvedTask] = []

    for task in recipe.tasks:
        if task.when is not None and not evaluate(task.when, namespace):
            continue

        materials: list[ResolvedMaterial] = []
        for spec in task.materials:
            tier = namespace.get(spec.tier_from) if spec.tier_from else None
            sku = catalogue.resolve_tier(spec.sku, tier)
            raw_qty = to_decimal(evaluate(spec.qty, namespace))
            materials.append(
                ResolvedMaterial(sku=sku, raw_qty=raw_qty, units=_units_for(spec, sku, raw_qty))
            )

        resolved.append(
            ResolvedTask(
                id=task.id,
                label=task.label,
                trade=task.trade,
                days=to_decimal(evaluate(task.days, namespace)),
                materials=tuple(materials),
            )
        )

    return tuple(resolved)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_quantify.py -v`
Expected: PASS, 12 passed

- [ ] **Step 6: Commit**

```bash
git add engine/quantify.py engine/models.py tests/test_quantify.py
git commit -m "feat: parameter validation and quantity resolution"
```

---

### Task 8: Costing — quantities to money

**Files:**
- Create: `engine/pricing.py`
- Modify: `engine/models.py` (append `MaterialLine`, `TaskLine`)
- Test: `tests/test_pricing.py`

**Interfaces:**
- Consumes: `ResolvedTask` (Task 7), `ClientConfig` (Task 5), `PriceBook` (Task 4), `round_money` (Task 2)
- Produces: `cost_tasks(tasks, client, book) -> tuple[TaskLine, ...]`

- [ ] **Step 1: Write the failing test**

`tests/test_pricing.py`:

```python
from decimal import Decimal

import pytest

from engine.clientconfig import ClientConfig
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pricing.py -v`
Expected: FAIL — `ImportError: cannot import name 'cost_tasks'`

- [ ] **Step 3: Append the costed models**

Append to `engine/models.py`:

```python
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
```

- [ ] **Step 4: Write the implementation**

`engine/pricing.py`:

```python
from decimal import Decimal

from engine.clientconfig import ClientConfig
from engine.models import MaterialLine, ResolvedTask, TaskLine
from engine.money import round_money
from engine.prices import PriceBook


def _cost_material(material, client: ClientConfig, book: PriceBook) -> MaterialLine:
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
    """Attach money to resolved tasks. Raises MissingPriceError if any SKU is unpriced."""
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_pricing.py -v`
Expected: PASS, 4 passed

- [ ] **Step 6: Commit**

```bash
git add engine/pricing.py engine/models.py tests/test_pricing.py
git commit -m "feat: material and labour costing with discount application"
```

---

### Task 9: Totals — contingency, margin, VAT, range

**Files:**
- Create: `engine/totals.py`
- Modify: `engine/models.py` (append `QuoteTotals`)
- Test: `tests/test_totals.py`

**Interfaces:**
- Consumes: `TaskLine` (Task 8), `ClientConfig` (Task 5), `round_money`, `round_to_nearest` (Task 2)
- Produces: `QuoteTotals` dataclass; `total_quote(lines, client) -> QuoteTotals`

- [ ] **Step 1: Write the failing test**

`tests/test_totals.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_totals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.totals'`

- [ ] **Step 3: Append the totals model**

Append to `engine/models.py`:

```python
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
```

- [ ] **Step 4: Write the implementation**

`engine/totals.py`:

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_totals.py -v`
Expected: PASS, 5 passed

- [ ] **Step 6: Commit**

```bash
git add engine/totals.py engine/models.py tests/test_totals.py
git commit -m "feat: quote totals with contingency, margin, VAT and display band"
```

---

### Task 10: Bathroom catalogue, recipe and placeholder price book

**Files:**
- Create: `catalogue/materials.yaml`, `recipes/bathroom-refit.yaml`, `data/pricebook/2026-08-20.json`
- Test: `tests/test_content.py`

**Interfaces:**
- Consumes: the loaders from Tasks 3, 4 and 6
- Produces: recipe id `bathroom-refit`; trades used — `labourer`, `plumber`, `electrician`, `joiner`, `tiler`, `plasterer`, `decorator`, `floor-layer`

Prices here are **placeholders** flagged `"method": "placeholder"`. Task 15 replaces them with harvested and researched figures. The engine must work end-to-end before the numbers are trustworthy.

- [ ] **Step 1: Write the failing test**

`tests/test_content.py` — this is the guard against the single most likely
demo failure: a recipe referencing something that is not priced.

```python
from pathlib import Path

import pytest

from engine.catalogue import load_catalogue
from engine.clientconfig import load_client
from engine.prices import latest_price_book
from engine.recipes import load_recipe

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def catalogue():
    return load_catalogue(ROOT / "catalogue" / "materials.yaml")


@pytest.fixture(scope="module")
def book():
    return latest_price_book(ROOT / "data" / "pricebook")


@pytest.fixture(scope="module")
def recipe(catalogue):
    return load_recipe(ROOT / "recipes" / "bathroom-refit.yaml", catalogue)


def test_recipe_loads(recipe):
    assert recipe.id == "bathroom-refit"
    assert len(recipe.tasks) >= 12


def test_every_catalogue_sku_has_a_price(catalogue, book):
    assert [s for s in catalogue.ids() if s not in book] == []


def test_every_recipe_sku_is_in_the_catalogue(recipe, catalogue):
    missing = [m.sku for t in recipe.tasks for m in t.materials if m.sku not in catalogue]
    assert missing == []


def test_every_tier_variant_is_priced(recipe, catalogue, book):
    missing = []
    for task in recipe.tasks:
        for material in task.materials:
            if not material.tier_from:
                continue
            for variant in catalogue.get(material.sku).tiers.values():
                if variant not in book:
                    missing.append(variant)
    assert missing == []


def test_every_trade_used_has_a_day_rate(recipe):
    client = load_client(ROOT / "clients" / "demo-nw")
    for task in recipe.tasks:
        client.day_rate(task.trade)      # raises RecipeError if absent


def test_number_parameters_are_bounded(recipe):
    for param in recipe.parameters:
        if param.type == "number" and param.default is None:
            assert param.min is not None and param.max is not None, param.id


def test_enum_parameters_declare_values(recipe):
    for param in recipe.parameters:
        if param.type == "enum":
            assert param.values, param.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_content.py -v`
Expected: FAIL — `FileNotFoundError` for `catalogue/materials.yaml`

- [ ] **Step 3: Write the catalogue**

`catalogue/materials.yaml`:

```yaml
# Plant and disposal
- { id: skip-6yd, name: "Skip, 6 yard, delivered and collected", unit: each, category: plant, discrete: true }

# Sanitaryware
- id: suite-mid
  name: "Bathroom suite (bath, basin, WC), mid range"
  unit: each
  category: sanitaryware
  discrete: true
  tiers: { budget: suite-budget, premium: suite-premium }
- { id: suite-budget, name: "Bathroom suite, budget", unit: each, category: sanitaryware, discrete: true }
- { id: suite-premium, name: "Bathroom suite, premium", unit: each, category: sanitaryware, discrete: true }
- id: shower-valve-mid
  name: "Thermostatic shower valve, mid range"
  unit: each
  category: sanitaryware
  discrete: true
  tiers: { budget: shower-valve-budget, premium: shower-valve-premium }
- { id: shower-valve-budget, name: "Shower valve, budget", unit: each, category: sanitaryware, discrete: true }
- { id: shower-valve-premium, name: "Shower valve, premium", unit: each, category: sanitaryware, discrete: true }
- { id: shower-enclosure, name: "Shower enclosure and door", unit: each, category: sanitaryware, discrete: true }
- { id: shower-tray, name: "Shower tray", unit: each, category: sanitaryware, discrete: true }
- { id: towel-rail, name: "Heated towel rail", unit: each, category: sanitaryware, discrete: true }

# Plumbing
- { id: pipework-consumables, name: "Pipework, fittings and consumables", unit: each, category: plumbing, discrete: true }
- { id: waste-kit, name: "Waste and trap kit", unit: each, category: plumbing, discrete: true }

# Wall and floor finishes
- id: tile-ceramic-mid
  name: "Ceramic wall tile, mid range"
  unit: m2
  category: finishes
  tiers: { budget: tile-ceramic-budget, premium: tile-porcelain-premium }
- { id: tile-ceramic-budget, name: "Ceramic wall tile, budget", unit: m2, category: finishes }
- { id: tile-porcelain-premium, name: "Porcelain wall tile, premium", unit: m2, category: finishes }
- { id: floor-tile-mid, name: "Porcelain floor tile", unit: m2, category: finishes }
- { id: lvt-mid, name: "Luxury vinyl tile flooring", unit: m2, category: finishes }
- { id: vinyl-budget, name: "Cushioned vinyl flooring", unit: m2, category: finishes }
- { id: adhesive-flexible-20kg, name: "Flexible tile adhesive 20kg", unit: bag, category: finishes, discrete: true, coverage: { unit: m2, per_unit: 4.5 } }
- { id: grout-5kg, name: "Wall and floor grout 5kg", unit: bag, category: finishes, discrete: true, coverage: { unit: m2, per_unit: 8.0 } }
- { id: tanking-kit, name: "Wet area tanking kit", unit: each, category: finishes, discrete: true, coverage: { unit: m2, per_unit: 5.0 } }
- { id: silicone-tube, name: "Sanitary silicone", unit: each, category: sundries, discrete: true }
- { id: paint-bathroom-2_5l, name: "Bathroom emulsion 2.5L", unit: tin, category: finishes, discrete: true, coverage: { unit: m2, per_unit: 12.0 } }

# Boarding, plaster, timber
- { id: moisture-board-12_5, name: "Moisture resistant plasterboard 12.5mm", unit: sheet, category: heavy-side, discrete: true, coverage: { unit: m2, per_unit: 2.88 } }
- { id: plaster-skim-25kg, name: "Multi finish plaster 25kg", unit: bag, category: heavy-side, discrete: true, coverage: { unit: m2, per_unit: 10.0 } }
- { id: ply-18mm, name: "Plywood 18mm 2440x1220", unit: sheet, category: timber, discrete: true, coverage: { unit: m2, per_unit: 2.88 } }
- { id: levelling-compound-20kg, name: "Floor levelling compound 20kg", unit: bag, category: heavy-side, discrete: true, coverage: { unit: m2, per_unit: 4.0 } }
- { id: timber-cls-38x63, name: "CLS studwork timber 38x63 2.4m", unit: length, category: timber, discrete: true }

# Electrical
- { id: extractor-fan, name: "Inline extractor fan", unit: each, category: electrical, discrete: true }
- { id: downlight, name: "IP65 LED downlight", unit: each, category: electrical, discrete: true }
- { id: shaver-socket, name: "Shaver socket", unit: each, category: electrical, discrete: true }
- { id: cable-1_5mm-50m, name: "Twin and earth cable 1.5mm 50m", unit: reel, category: electrical, discrete: true }

# Sundries
- { id: fixings-sundries, name: "Screws, fixings and sundries", unit: each, category: sundries, discrete: true }
```

- [ ] **Step 4: Write the bathroom recipe**

`recipes/bathroom-refit.yaml`:

```yaml
id: bathroom-refit
label: Bathroom refit

parameters:
  - { id: length_m, type: number, min: 1.2, max: 6.0 }
  - { id: width_m, type: number, min: 1.2, max: 6.0 }
  - { id: height_m, type: number, default: 2.4 }
  - { id: spec_tier, type: enum, values: [budget, mid, premium] }
  - { id: shower_type, type: enum, values: [over-bath, walk-in, enclosure] }
  - { id: tiling_extent, type: enum, values: [floor-only, half-height, full-height] }
  - { id: layout_change, type: enum, values: [none, minor, full-move] }
  - { id: floor_type, type: enum, values: [tile, lvt, vinyl] }

constants:
  tiling_factor:   { floor-only: 0.0, half-height: 0.5, full-height: 1.0 }
  shower_area:     { over-bath: 0.0, walk-in: 4.5, enclosure: 3.5 }
  first_fix_days:  { none: 1.0, minor: 1.5, full-move: 2.5 }
  elec_first_days: { none: 0.5, minor: 0.75, full-move: 1.25 }
  suite_fit_days:  { over-bath: 1.0, walk-in: 1.5, enclosure: 1.25 }

derived:
  floor_area_m2: length_m * width_m
  ceiling_area_m2: length_m * width_m
  wall_area_m2: 2 * (length_m + width_m) * height_m
  tiled_area_m2: wall_area_m2 * tiling_factor[tiling_extent]
  shower_area_m2: shower_area[shower_type]

tasks:
  - id: strip_out
    label: Strip out and muck away
    trade: labourer
    days: 0.5 + floor_area_m2 * 0.10
    materials:
      - { sku: skip-6yd, qty: 1 }

  - id: first_fix_plumbing
    label: First fix plumbing
    trade: plumber
    days: first_fix_days[layout_change]
    materials:
      - { sku: pipework-consumables, qty: 1 }
      - { sku: waste-kit, qty: 1 }

  - id: first_fix_electrical
    label: First fix electrical
    trade: electrician
    days: elec_first_days[layout_change]
    materials:
      - { sku: cable-1_5mm-50m, qty: 1 }
      - { sku: extractor-fan, qty: 1 }
      - { sku: downlight, qty: "max(3, ceil(floor_area_m2 / 1.5))" }
      - { sku: shaver-socket, qty: 1 }

  - id: boarding
    label: Boarding and stud alterations
    trade: joiner
    days: 0.5 + wall_area_m2 * 0.025
    materials:
      - { sku: moisture-board-12_5, qty: wall_area_m2, waste: 0.10, by_coverage: true }
      - { sku: timber-cls-38x63, qty: ceil(wall_area_m2 / 3) }
      - { sku: fixings-sundries, qty: 1 }

  - id: tanking
    label: Wet area tanking
    trade: tiler
    when: shower_type != 'over-bath'
    days: shower_area_m2 * 0.15
    materials:
      - { sku: tanking-kit, qty: shower_area_m2, by_coverage: true }

  - id: floor_prep
    label: Floor preparation
    trade: joiner
    days: 0.25 + floor_area_m2 * 0.08
    materials:
      - { sku: ply-18mm, qty: floor_area_m2, waste: 0.10, by_coverage: true }
      - { sku: levelling-compound-20kg, qty: floor_area_m2, by_coverage: true }

  - id: wall_tiling
    label: Wall tiling
    trade: tiler
    when: tiling_extent != 'floor-only'
    days: tiled_area_m2 / 6
    materials:
      - { sku: tile-ceramic-mid, qty: tiled_area_m2, waste: 0.10, tier: spec_tier }
      - { sku: adhesive-flexible-20kg, qty: tiled_area_m2, by_coverage: true }
      - { sku: grout-5kg, qty: tiled_area_m2, by_coverage: true }

  - id: floor_tiling
    label: Floor tiling
    trade: tiler
    when: floor_type == 'tile'
    days: floor_area_m2 / 5
    materials:
      - { sku: floor-tile-mid, qty: floor_area_m2, waste: 0.12 }
      - { sku: adhesive-flexible-20kg, qty: floor_area_m2, by_coverage: true }
      - { sku: grout-5kg, qty: floor_area_m2, by_coverage: true }

  - id: floor_lvt
    label: LVT flooring
    trade: floor-layer
    when: floor_type == 'lvt'
    days: 0.5 + floor_area_m2 / 8
    materials:
      - { sku: lvt-mid, qty: floor_area_m2, waste: 0.10 }

  - id: floor_vinyl
    label: Vinyl flooring
    trade: floor-layer
    when: floor_type == 'vinyl'
    days: 0.5
    materials:
      - { sku: vinyl-budget, qty: floor_area_m2, waste: 0.15 }

  - id: second_fix_plumbing
    label: Sanitaryware install and second fix plumbing
    trade: plumber
    days: suite_fit_days[shower_type]
    materials:
      - { sku: suite-mid, qty: 1, tier: spec_tier }
      - { sku: shower-valve-mid, qty: 1, tier: spec_tier }
      - { sku: towel-rail, qty: 1 }

  - id: shower_enclosure_fit
    label: Shower enclosure and tray
    trade: plumber
    when: shower_type == 'enclosure'
    days: 0.5
    materials:
      - { sku: shower-enclosure, qty: 1 }
      - { sku: shower-tray, qty: 1 }

  - id: second_fix_electrical
    label: Second fix electrical and test
    trade: electrician
    days: 0.5

  - id: plastering
    label: Plastering and making good
    trade: plasterer
    days: 0.5 + ceiling_area_m2 * 0.12
    materials:
      - { sku: plaster-skim-25kg, qty: ceiling_area_m2 + wall_area_m2 - tiled_area_m2, by_coverage: true }

  - id: decorating
    label: Decorating
    trade: decorator
    days: 0.75 + ceiling_area_m2 * 0.08
    materials:
      - { sku: paint-bathroom-2_5l, qty: ceiling_area_m2 + wall_area_m2 - tiled_area_m2, by_coverage: true }

  - id: final_fix
    label: Silicone, final fix and clean
    trade: plumber
    days: 0.5
    materials:
      - { sku: silicone-tube, qty: 3 }
```

- [ ] **Step 5: Write the placeholder price book**

`data/pricebook/2026-08-20.json` — every value carries `"method": "placeholder"`:

```json
{
  "captured": "2026-08-20",
  "source_run": "placeholder — replaced in Task 15",
  "prices": {
    "skip-6yd":                { "list": 260.00, "unit": "each",   "source": "placeholder", "method": "placeholder" },
    "suite-budget":            { "list": 320.00, "unit": "each",   "source": "placeholder", "method": "placeholder" },
    "suite-mid":               { "list": 620.00, "unit": "each",   "source": "placeholder", "method": "placeholder" },
    "suite-premium":           { "list": 1450.00, "unit": "each",  "source": "placeholder", "method": "placeholder" },
    "shower-valve-budget":     { "list": 110.00, "unit": "each",   "source": "placeholder", "method": "placeholder" },
    "shower-valve-mid":        { "list": 210.00, "unit": "each",   "source": "placeholder", "method": "placeholder" },
    "shower-valve-premium":    { "list": 480.00, "unit": "each",   "source": "placeholder", "method": "placeholder" },
    "shower-enclosure":        { "list": 380.00, "unit": "each",   "source": "placeholder", "method": "placeholder" },
    "shower-tray":             { "list": 180.00, "unit": "each",   "source": "placeholder", "method": "placeholder" },
    "towel-rail":              { "list": 140.00, "unit": "each",   "source": "placeholder", "method": "placeholder" },
    "pipework-consumables":    { "list": 180.00, "unit": "each",   "source": "placeholder", "method": "placeholder" },
    "waste-kit":               { "list": 45.00,  "unit": "each",   "source": "placeholder", "method": "placeholder" },
    "tile-ceramic-budget":     { "list": 14.50,  "unit": "m2",     "source": "placeholder", "method": "placeholder" },
    "tile-ceramic-mid":        { "list": 24.99,  "unit": "m2",     "source": "placeholder", "method": "placeholder" },
    "tile-porcelain-premium":  { "list": 42.00,  "unit": "m2",     "source": "placeholder", "method": "placeholder" },
    "floor-tile-mid":          { "list": 28.00,  "unit": "m2",     "source": "placeholder", "method": "placeholder" },
    "lvt-mid":                 { "list": 32.00,  "unit": "m2",     "source": "placeholder", "method": "placeholder" },
    "vinyl-budget":            { "list": 15.00,  "unit": "m2",     "source": "placeholder", "method": "placeholder" },
    "adhesive-flexible-20kg":  { "list": 18.49,  "unit": "bag",    "source": "placeholder", "method": "placeholder" },
    "grout-5kg":               { "list": 12.99,  "unit": "bag",    "source": "placeholder", "method": "placeholder" },
    "tanking-kit":             { "list": 68.00,  "unit": "each",   "source": "placeholder", "method": "placeholder" },
    "silicone-tube":           { "list": 6.50,   "unit": "each",   "source": "placeholder", "method": "placeholder" },
    "paint-bathroom-2_5l":     { "list": 28.00,  "unit": "tin",    "source": "placeholder", "method": "placeholder" },
    "moisture-board-12_5":     { "list": 14.80,  "unit": "sheet",  "source": "placeholder", "method": "placeholder" },
    "plaster-skim-25kg":       { "list": 11.50,  "unit": "bag",    "source": "placeholder", "method": "placeholder" },
    "ply-18mm":                { "list": 32.00,  "unit": "sheet",  "source": "placeholder", "method": "placeholder" },
    "levelling-compound-20kg": { "list": 19.00,  "unit": "bag",    "source": "placeholder", "method": "placeholder" },
    "timber-cls-38x63":        { "list": 4.20,   "unit": "length", "source": "placeholder", "method": "placeholder" },
    "extractor-fan":           { "list": 65.00,  "unit": "each",   "source": "placeholder", "method": "placeholder" },
    "downlight":               { "list": 12.50,  "unit": "each",   "source": "placeholder", "method": "placeholder" },
    "shaver-socket":           { "list": 22.00,  "unit": "each",   "source": "placeholder", "method": "placeholder" },
    "cable-1_5mm-50m":         { "list": 42.00,  "unit": "reel",   "source": "placeholder", "method": "placeholder" },
    "fixings-sundries":        { "list": 35.00,  "unit": "each",   "source": "placeholder", "method": "placeholder" }
  }
}
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS, all tests. Every SKU the recipe uses — including every tier
variant — is priced, and every trade it uses has a day rate.

- [ ] **Step 7: Commit**

```bash
git add catalogue/ recipes/ data/pricebook/ tests/test_content.py
git commit -m "feat: bathroom refit recipe, catalogue and placeholder price book"
```

---

### Task 11: `build_quote` — the single public entry point

**Files:**
- Create: `engine/quote.py`
- Modify: `engine/models.py` (append `QuoteResult`)
- Test: `tests/test_quote.py`

**Interfaces:**
- Consumes: everything from Tasks 3–9, plus the content from Task 10
- Produces: `QuoteResult` dataclass; `build_quote(recipe_id, parameters, client_slug, root=None) -> QuoteResult`

- [ ] **Step 1: Write the failing test**

`tests/test_quote.py`:

```python
from decimal import Decimal

import pytest

from engine.errors import ParameterError
from engine.quote import build_quote


def test_end_to_end_produces_a_positive_range():
    result = build_quote(
        recipe_id="bathroom-refit",
        parameters={
            "length_m": 2.4, "width_m": 1.8, "spec_tier": "mid",
            "shower_type": "walk-in", "tiling_extent": "full-height",
            "layout_change": "none", "floor_type": "tile",
        },
        client_slug="demo-nw",
    )
    assert result.totals.low > Decimal("0")
    assert result.totals.high > result.totals.low
    assert result.recipe_label == "Bathroom refit"


def test_result_carries_provenance_for_the_internal_view():
    result = build_quote(
        recipe_id="bathroom-refit",
        parameters={
            "length_m": 2.4, "width_m": 1.8, "spec_tier": "mid",
            "shower_type": "walk-in", "tiling_extent": "full-height",
            "layout_change": "none", "floor_type": "tile",
        },
        client_slug="demo-nw",
    )
    assert result.price_book_captured
    assert result.client_slug == "demo-nw"
    assert len(result.tasks) > 5
    assert "floor_area_m2" in result.derived


def test_bad_parameters_raise_before_any_pricing():
    with pytest.raises(ParameterError):
        build_quote(recipe_id="bathroom-refit", parameters={}, client_slug="demo-nw")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_quote.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.quote'`

- [ ] **Step 3: Append the result model**

Append to `engine/models.py`:

```python
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
```

- [ ] **Step 4: Write the implementation**

`engine/quote.py`:

```python
from pathlib import Path

from engine.catalogue import load_catalogue
from engine.clientconfig import load_client
from engine.models import QuoteResult
from engine.prices import latest_price_book
from engine.pricing import cost_tasks
from engine.quantify import build_namespace, quantify, resolve_parameters
from engine.recipes import load_recipe
from engine.totals import total_quote

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def build_quote(
    recipe_id: str,
    parameters: dict,
    client_slug: str,
    root: Path | None = None,
) -> QuoteResult:
    """Load everything, validate, quantify, cost, total. The only public entry point."""
    root = root or PROJECT_ROOT

    catalogue = load_catalogue(root / "catalogue" / "materials.yaml")
    recipe = load_recipe(root / "recipes" / f"{recipe_id}.yaml", catalogue)
    client = load_client(root / "clients" / client_slug)
    book = latest_price_book(root / "data" / "pricebook")

    params = resolve_parameters(recipe, parameters)
    namespace = build_namespace(recipe, params)
    resolved = quantify(recipe, params, catalogue)
    lines = cost_tasks(resolved, client, book)

    derived = {k: namespace[k] for k in recipe.derived}

    return QuoteResult(
        recipe_id=recipe.id,
        recipe_label=recipe.label,
        client_slug=client.slug,
        price_book_captured=book.captured,
        parameters=params,
        derived=derived,
        tasks=lines,
        totals=total_quote(lines, client),
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest -v`
Expected: PASS, all tests. The recipe content landed in Task 10, so `build_quote`
is green on arrival.

- [ ] **Step 6: Sanity check the number by hand**

Run:

```bash
uv run python -c "
from engine.quote import build_quote
r = build_quote('bathroom-refit', {'length_m':2.4,'width_m':1.8,'spec_tier':'mid','shower_type':'walk-in','tiling_extent':'full-height','layout_change':'none','floor_type':'tile'}, 'demo-nw')
print(r.totals.low, '-', r.totals.high)
print('labour', r.totals.labour_cost, 'materials', r.totals.material_cost, 'plant', r.totals.plant_cost)
"
```

Expected: a range in the region of **£7,000-£11,000 inc VAT** for a standard
2.4 x 1.8m mid-spec bathroom. If it lands outside £5,000-£14,000, a formula is
wrong — investigate before continuing. Do not adjust numbers to hit a target;
find the faulty line.

- [ ] **Step 7: Commit**

```bash
git add engine/quote.py engine/models.py tests/test_quote.py
git commit -m "feat: build_quote entry point wiring the engine together"
```

---

### Task 12: CLI

**Files:**
- Create: `scripts/quote_cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `build_quote` (Task 11)
- Produces: `python -m scripts.quote_cli --recipe <id> --client <slug> --param k=v ...`; `format_quote(QuoteResult, detail: bool) -> str`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:

```python
import pytest

from engine.quote import build_quote
from scripts.quote_cli import format_quote, parse_params

PARAMS = {
    "length_m": 2.4, "width_m": 1.8, "spec_tier": "mid", "shower_type": "walk-in",
    "tiling_extent": "full-height", "layout_change": "none", "floor_type": "tile",
}


def test_parse_params_coerces_numbers():
    parsed = parse_params(["length_m=2.4", "spec_tier=mid"])
    assert parsed["length_m"] == 2.4
    assert parsed["spec_tier"] == "mid"


def test_parse_params_rejects_malformed_pairs():
    with pytest.raises(SystemExit):
        parse_params(["length_m"])


def test_summary_shows_the_range_and_the_four_line_breakdown():
    out = format_quote(build_quote("bathroom-refit", PARAMS, "demo-nw"), detail=False)
    assert "Bathroom refit" in out
    assert "Labour" in out and "Materials" in out and "Plant" in out and "Contingency" in out


def test_detail_view_lists_tasks_and_skus():
    out = format_quote(build_quote("bathroom-refit", PARAMS, "demo-nw"), detail=True)
    assert "Wall tiling" in out
    assert "tile-ceramic-mid" in out


def test_summary_view_hides_skus():
    out = format_quote(build_quote("bathroom-refit", PARAMS, "demo-nw"), detail=False)
    assert "tile-ceramic-mid" not in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.quote_cli'`

- [ ] **Step 3: Write the implementation**

First `touch scripts/__init__.py`, then `scripts/quote_cli.py`:

```python
import argparse
import sys

from engine.errors import QuoteError
from engine.models import QuoteResult
from engine.quote import build_quote


def parse_params(pairs: list[str]) -> dict:
    """Turn ['length_m=2.4', 'spec_tier=mid'] into a parameter dict."""
    params: dict = {}
    for pair in pairs:
        if "=" not in pair:
            sys.exit(f"malformed --param {pair!r}, expected key=value")
        key, _, value = pair.partition("=")
        try:
            params[key] = float(value)
        except ValueError:
            params[key] = value
    return params


def format_quote(result: QuoteResult, detail: bool = False) -> str:
    t = result.totals
    lines = [
        f"{result.recipe_label} — {result.client_slug}",
        f"Prices captured {result.price_book_captured}",
        "",
        f"  £{t.low:,.0f} – £{t.high:,.0f} inc VAT",
        "",
        f"  Labour       £{t.labour_cost:,.2f}",
        f"  Materials    £{t.material_cost:,.2f}",
        f"  Plant        £{t.plant_cost:,.2f}",
        f"  Contingency  £{t.contingency:,.2f}",
        f"  ----------------------------",
        f"  Net          £{t.net_price:,.2f}",
        f"  VAT          £{t.vat:,.2f}",
        f"  Gross        £{t.gross:,.2f}",
    ]

    if detail:
        lines += ["", "Internal detail:"]
        for task in result.tasks:
            lines.append(
                f"  {task.label} — {task.trade} {task.days:.2f}d "
                f"@ £{task.day_rate:,.0f} = £{task.labour_cost:,.2f}"
            )
            for m in task.materials:
                lines.append(
                    f"      {m.sku_id:<26} {m.units:>8.2f} {m.unit:<6} "
                    f"@ £{m.unit_net:>8,.2f} (list £{m.list_price:,.2f} "
                    f"less {m.discount:.0%}) = £{m.cost:,.2f}"
                )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Produce a quote from a recipe.")
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--client", default="demo-nw")
    parser.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--detail", action="store_true", help="show the internal itemised view")
    args = parser.parse_args(argv)

    try:
        result = build_quote(args.recipe, parse_params(args.param), args.client)
    except QuoteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(format_quote(result, detail=args.detail))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS, 5 passed

- [ ] **Step 5: Run it for real**

```bash
uv run python -m scripts.quote_cli --recipe bathroom-refit \
  --param length_m=2.4 --param width_m=1.8 --param spec_tier=mid \
  --param shower_type=walk-in --param tiling_extent=full-height \
  --param layout_change=none --param floor_type=tile --detail
```

Expected: a formatted quote with a range and an itemised breakdown.

- [ ] **Step 6: Commit**

```bash
git add scripts/quote_cli.py scripts/__init__.py tests/test_cli.py
git commit -m "feat: quote CLI with summary and internal detail views"
```

---

### Task 13: Golden tests

**Files:**
- Create: `tests/golden/bathroom-standard.json`, `tests/golden/bathroom-premium-enclosure.json`, `tests/golden/bathroom-budget-overbath.json`, `tests/golden/bathroom-large-fullmove.json`, `tests/test_golden.py`, `scripts/update_golden.py`
- Test: `tests/test_golden.py`

**Interfaces:**
- Consumes: `build_quote` (Task 11)
- Produces: regression coverage over whole-quote totals

A golden file pins the totals for a known job. Any formula change that moves a
number fails loudly instead of drifting unnoticed.

- [ ] **Step 1: Write the golden runner test**

`tests/test_golden.py`:

```python
import json
from decimal import Decimal
from pathlib import Path

import pytest

from engine.quote import build_quote

GOLDEN_DIR = Path(__file__).parent / "golden"
CASES = sorted(GOLDEN_DIR.glob("*.json"))


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_golden_case(path):
    case = json.loads(path.read_text())
    result = build_quote(case["recipe"], case["parameters"], case["client"])
    expected = case["expected"]

    assert result.totals.low == Decimal(expected["low"]), (
        f"{path.stem}: low moved from {expected['low']} to {result.totals.low}. "
        "If this change is intended, run scripts/update_golden.py and review the diff."
    )
    assert result.totals.high == Decimal(expected["high"])
    assert result.totals.labour_cost == Decimal(expected["labour_cost"])
    assert result.totals.material_cost == Decimal(expected["material_cost"])
    assert result.totals.plant_cost == Decimal(expected["plant_cost"])


def test_at_least_four_golden_cases_exist():
    assert len(CASES) >= 4
```

- [ ] **Step 2: Write the four case files without expected values**

Each file, e.g. `tests/golden/bathroom-standard.json`:

```json
{
  "recipe": "bathroom-refit",
  "client": "demo-nw",
  "description": "Standard 2.4 x 1.8m mid-spec bathroom, walk-in shower, tiled floor to ceiling",
  "parameters": {
    "length_m": 2.4, "width_m": 1.8, "spec_tier": "mid", "shower_type": "walk-in",
    "tiling_extent": "full-height", "layout_change": "none", "floor_type": "tile"
  },
  "expected": {"low": "0", "high": "0", "labour_cost": "0", "material_cost": "0", "plant_cost": "0"}
}
```

`tests/golden/bathroom-premium-enclosure.json` — same shape, description
"Large premium bathroom with separate enclosure and full layout move", parameters:

```json
{"length_m": 3.2, "width_m": 2.6, "spec_tier": "premium", "shower_type": "enclosure",
 "tiling_extent": "full-height", "layout_change": "full-move", "floor_type": "tile"}
```

`tests/golden/bathroom-budget-overbath.json` — description "Small budget bathroom,
shower over bath, half-height tiling, vinyl floor", parameters:

```json
{"length_m": 1.7, "width_m": 1.4, "spec_tier": "budget", "shower_type": "over-bath",
 "tiling_extent": "half-height", "layout_change": "none", "floor_type": "vinyl"}
```

`tests/golden/bathroom-large-fullmove.json` — description "Large mid-spec bathroom,
LVT floor, floor tiling only, minor layout change", parameters:

```json
{"length_m": 3.0, "width_m": 2.2, "spec_tier": "mid", "shower_type": "walk-in",
 "tiling_extent": "floor-only", "layout_change": "minor", "floor_type": "lvt"}
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_golden.py -v`
Expected: FAIL on all four — expected `0`, got a real number.

- [ ] **Step 4: Write the updater**

`scripts/update_golden.py`:

```python
"""Regenerate expected totals in tests/golden/*.json.

Run this ONLY after deliberately changing a formula, and always read the diff
before committing. It records what the engine currently does — it does not
verify that what the engine does is correct.
"""

import json
from pathlib import Path

from engine.quote import build_quote

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "tests" / "golden"


def main() -> int:
    for path in sorted(GOLDEN_DIR.glob("*.json")):
        case = json.loads(path.read_text())
        totals = build_quote(case["recipe"], case["parameters"], case["client"]).totals
        case["expected"] = {
            "low": str(totals.low),
            "high": str(totals.high),
            "labour_cost": str(totals.labour_cost),
            "material_cost": str(totals.material_cost),
            "plant_cost": str(totals.plant_cost),
        }
        path.write_text(json.dumps(case, indent=2) + "\n")
        print(f"{path.stem}: £{totals.low} – £{totals.high}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Generate and eyeball the values**

Run: `uv run python -m scripts.update_golden`

**Stop and read the four ranges.** Each must be plausible for the job described.
A budget 1.7 × 1.4m over-bath refit should come out well below a premium 3.2 × 2.6m
with a separate enclosure. If the ordering is wrong, or any number looks absurd,
fix the recipe — do not accept the generated value.

- [ ] **Step 6: Run and commit**

Run: `uv run pytest -v`
Expected: PASS, all tests

```bash
git add tests/golden/ tests/test_golden.py scripts/update_golden.py
git commit -m "test: golden regression cases for bathroom quotes"
```

---

### Task 14: Price harvest script

**Files:**
- Create: `scripts/harvest_prices.py`, `catalogue/sources.yaml`
- Test: `tests/test_harvest.py`

**Interfaces:**
- Consumes: `load_catalogue` (Task 3)
- Produces: `merge_prices(catalogue, fetched, manual, captured) -> dict`; CLI writing `data/pricebook/<date>.json`

The network-touching part is isolated behind one function so the merge logic is
testable offline. **This is the only file in the project permitted to make network calls.**

- [ ] **Step 1: Write the failing test**

`tests/test_harvest.py`:

```python
import pytest

from engine.catalogue import load_catalogue
from scripts.harvest_prices import merge_prices

CATALOGUE = """
- { id: a, name: A, unit: m2, category: finishes }
- { id: b, name: B, unit: each, category: plant, discrete: true }
- { id: c, name: C, unit: bag, category: heavy-side, discrete: true }
"""


@pytest.fixture
def catalogue(tmp_path):
    p = tmp_path / "materials.yaml"
    p.write_text(CATALOGUE)
    return load_catalogue(p)


def test_fetched_prices_are_marked_scraped(catalogue):
    book = merge_prices(catalogue, {"a": (12.5, "http://x")}, {}, "2026-08-20")
    assert book["prices"]["a"]["list"] == 12.5
    assert book["prices"]["a"]["method"] == "scraped"


def test_manual_prices_are_marked_hand(catalogue):
    book = merge_prices(catalogue, {}, {"b": 260.0}, "2026-08-20")
    assert book["prices"]["b"]["method"] == "hand"


def test_manual_overrides_fetched(catalogue):
    book = merge_prices(catalogue, {"a": (12.5, "http://x")}, {"a": 99.0}, "2026-08-20")
    assert book["prices"]["a"]["list"] == 99.0
    assert book["prices"]["a"]["method"] == "hand"


def test_unpriced_skus_are_reported_not_silently_dropped(catalogue):
    book = merge_prices(catalogue, {"a": (12.5, "http://x")}, {}, "2026-08-20")
    assert set(book["unpriced"]) == {"b", "c"}


def test_unit_comes_from_the_catalogue(catalogue):
    book = merge_prices(catalogue, {"a": (12.5, "http://x")}, {}, "2026-08-20")
    assert book["prices"]["a"]["unit"] == "m2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_harvest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.harvest_prices'`

- [ ] **Step 3: Write the implementation**

`catalogue/sources.yaml` — starts with the SKUs whose prices are published online.
Fill in real product URLs as they are found; SKUs absent from this file fall to manual.

```yaml
# sku_id: product page URL
tile-ceramic-mid: ""
adhesive-flexible-20kg: ""
grout-5kg: ""
moisture-board-12_5: ""
plaster-skim-25kg: ""
ply-18mm: ""
levelling-compound-20kg: ""
timber-cls-38x63: ""
extractor-fan: ""
downlight: ""
cable-1_5mm-50m: ""
paint-bathroom-2_5l: ""
```

`scripts/harvest_prices.py`:

```python
"""Capture current list prices into a dated, immutable price book.

Run offline, days before a demo — never at quote time. This is the only module
in the project that touches the network.

Usage:
    uv run python -m scripts.harvest_prices --manual catalogue/manual_prices.yaml
"""

import argparse
import json
from datetime import date
from pathlib import Path

import yaml

from engine.catalogue import Catalogue, load_catalogue

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def merge_prices(
    catalogue: Catalogue,
    fetched: dict[str, tuple[float, str]],
    manual: dict[str, float],
    captured: str,
) -> dict:
    """Combine scraped and hand-entered prices. Manual always wins.

    Provenance is recorded per SKU so hand-entered heavy-side and plant prices
    stay visibly distinguishable from scraped ones.
    """
    prices: dict[str, dict] = {}

    for sku_id, (value, source) in fetched.items():
        sku = catalogue.get(sku_id)
        prices[sku_id] = {"list": value, "unit": sku.unit, "source": source, "method": "scraped"}

    for sku_id, value in manual.items():
        sku = catalogue.get(sku_id)
        prices[sku_id] = {"list": value, "unit": sku.unit, "source": "manual", "method": "hand"}

    unpriced = [sku_id for sku_id in catalogue.ids() if sku_id not in prices]

    return {
        "captured": captured,
        "source_run": "harvest_prices.py v1",
        "prices": prices,
        "unpriced": unpriced,
    }


def fetch_prices(sources: dict[str, str]) -> dict[str, tuple[float, str]]:
    """Fetch published list prices. Left unimplemented deliberately.

    Populate catalogue/sources.yaml with product URLs, then implement per-site
    extraction here. Until then every SKU is hand-priced, which is a valid and
    fully supported mode — see the `unpriced` list in the output.
    """
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture prices into a dated price book.")
    parser.add_argument("--manual", default=str(PROJECT_ROOT / "catalogue" / "manual_prices.yaml"))
    parser.add_argument("--out", default=str(PROJECT_ROOT / "data" / "pricebook"))
    args = parser.parse_args(argv)

    catalogue = load_catalogue(PROJECT_ROOT / "catalogue" / "materials.yaml")
    sources = yaml.safe_load((PROJECT_ROOT / "catalogue" / "sources.yaml").read_text()) or {}
    manual_path = Path(args.manual)
    manual = yaml.safe_load(manual_path.read_text()) if manual_path.exists() else {}

    book = merge_prices(catalogue, fetch_prices(sources), manual or {}, date.today().isoformat())

    out_path = Path(args.out) / f"{book['captured']}.json"
    out_path.write_text(json.dumps(book, indent=2) + "\n")

    print(f"wrote {out_path} — {len(book['prices'])} priced, {len(book['unpriced'])} unpriced")
    for sku_id in book["unpriced"]:
        print(f"  UNPRICED: {sku_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_harvest.py -v`
Expected: PASS, 5 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/harvest_prices.py catalogue/sources.yaml tests/test_harvest.py
git commit -m "feat: price harvest script with provenance tracking"
```

---

### Task 15: Replace placeholders with researched figures

**Files:**
- Modify: `clients/demo-nw/labour.yaml`, `data/pricebook/<today>.json`
- Create: `catalogue/manual_prices.yaml`, `logs/rates-research-2026-08-20.md`
- Test: `tests/test_golden.py` (regenerate and review)

**Interfaces:**
- Consumes: `harvest_prices` (Task 14), `update_golden` (Task 13)
- Produces: a price book and rate card with no `"method": "placeholder"` entries

- [ ] **Step 1: Research Northwest England day rates**

Use web search (Exa is authorised) for current NW England day rates for:
`plumber`, `tiler`, `electrician`, `plasterer`, `joiner`, `decorator`, `floor-layer`, `labourer`.

Record every figure with its source and date in `logs/rates-research-2026-08-20.md`.
Where sources disagree, record the range and take the midpoint. Do not average a
national figure with a regional one — prefer regional.

- [ ] **Step 2: Update the rate card**

Write the researched figures into `clients/demo-nw/labour.yaml`, keeping the same keys.

- [ ] **Step 3: Research material list prices**

For each SKU in `catalogue/materials.yaml`, find a current published UK list price.
Put every figure into `catalogue/manual_prices.yaml` as `sku_id: price`, and record
the source URL alongside it as a YAML comment.

Heavy-side and plant items (`skip-6yd`, bulk materials) are typically not published
online. Use a trade-typical figure and note in the log that it is estimated.

- [ ] **Step 4: Regenerate the price book**

Run: `uv run python -m scripts.harvest_prices`
Expected: `0 unpriced`. Any UNPRICED line must be resolved before proceeding.

Then delete the placeholder book:

```bash
git rm data/pricebook/2026-08-20.json   # only if today's date differs
```

- [ ] **Step 5: Regenerate and review the golden values**

Run: `uv run python -m scripts.update_golden`

**Stop and check every range against trade intuition.** The standard 2.4 × 1.8m
mid-spec bathroom is the one to trust your gut on — it should land in the region
of £7,000–£11,000 inc VAT. Then run the full suite:

Run: `uv run pytest -v`
Expected: PASS

- [ ] **Step 6: Verify no placeholders remain**

Run: `grep -rc placeholder data/pricebook/ || echo "clean"`
Expected: `clean`, or a count of 0.

- [ ] **Step 7: Commit**

```bash
git add clients/demo-nw/labour.yaml catalogue/manual_prices.yaml data/pricebook/ tests/golden/ logs/
git commit -m "feat: researched NW England day rates and material list prices"
```

---

## Done when

- `uv run pytest -v` passes with every test green
- `uv run python -m scripts.quote_cli --recipe bathroom-refit ... --detail` prints a
  complete itemised quote
- No `"method": "placeholder"` remains in the active price book
- The standard bathroom golden case has been sense-checked by someone in the trade

## Next plans

- **Plan 2:** FastAPI app (four screens), LLM intake parsing, assumptions narrative, branded PDF, `new_client.py`
- **Plan 3:** kitchen recipe and directives
