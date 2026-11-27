# Quote engine: design spec

**Date:** 2026-08-20
**Status:** Approved for planning. The engine (milestones 1 to 4) is built; the LLM layer, web app and PDF are not.
**Author:** Sam Jordan, with Claude

---

## 1. Purpose

An instant quoting tool for UK domestic building firms. Each firm runs its own
configured instance: its own labour rates, merchant discounts and commercial settings.

The problem it solves: a customer phones a building firm asking
"how much for a new bathroom?". Today the person answering the phone cannot answer.
They take details, promise a call back, and the owner quotes it days later at 9pm —
by which point the lead is cold or gone. This tool lets whoever answers the phone
give a defensible ballpark **while the caller is still on the line**.

The value is speed-to-quote, not estimating precision.

## 2. Users

| User | Context | Needs |
|---|---|---|
| **Office staff** (primary) | On a live call, untrained, under time pressure | Cannot get it wrong; fast; readable aloud |
| **Firm owner** | Reviewing, configuring rates | Sees how the number was built; can defend it |
| **Setup operator** | Configuring a new firm | Never fails on a live call; a new firm is set up in about 20 min |

## 3. Success criteria

1. A complete bathroom quote in **under 60 seconds** from a standing start.
2. Numbers a tradesperson **recognises as roughly right** — no obviously wrong lines.
3. Changing a spec dropdown moves the total **sensibly and instantly**.
4. **Zero network dependency at quote time.** A quote can never fail because a connection dropped while the customer is on the line.
5. Setting up a new firm is editing four small files.

## 4. Scope

### In scope (v1)

- Parametric quoting engine, archetype-driven
- Two archetypes: **bathroom refit**, **kitchen refit**
- Cached, versioned materials price book (~250-350 SKUs)
- Per-client merchant discount matrix
- Per-trade day-rate card (Northwest England)
- LLM intake parsing (free text -> form fields)
- LLM assumptions/exclusions narrative
- Four-screen local web app
- Branded PDF, human-approved before send
- Internal itemised view / external summary view

### Out of scope (v1)

- Live merchant API integration (deferred: scheduled scrape, then paid feed/EDI)
- Customer-facing self-serve version (the "external version" — later)
- Multi-tenant hosting, auth, user accounts
- Takeoff from drawings or PDFs
- Extension, loft, re-roof archetypes (planned next; engine must not need changes)
- Full KB/website RAG ingestion (**rejected** — small builders' sites contain
  almost nothing worth indexing)
- CIS deductions (payroll concern, not quoting)
- Reduced-rate 5% VAT cases (noted, deferred)
- Regional multipliers (NW England only for now)

## 5. Architecture

Three layers.

```
DIRECTIVE      markdown SOPs
               authoring a recipe · setting up a new firm
               refreshing the price book
                        |
ORCHESTRATION  the LLM — language work only
               free text -> validated parameters
               computed result -> assumptions prose
                        |
EXECUTION      deterministic Python — every number
               quantities · pricing · discounts · margin · VAT · PDF
```

### The hard rule

**The LLM never performs arithmetic and never sees a price.**

It has two jobs, both linguistic. Its output is validated against a JSON schema
derived from the active recipe's parameter definitions; any value outside the
allowed set is discarded and the field left blank and flagged for the operator.

This is a correctness measure, and it gives a straight answer when a builder asks
"how do I know it isn't inventing prices?": it structurally cannot.

### Quote flow

1. Operator selects job type -> loads recipe
2. Free text -> LLM -> partial parameters + unresolved field list
3. Operator reviews and corrects the form (source of truth)
4. Engine computes derived values
5. Per task: labour days x day rate; material quantities x discounted price x waste
6. Direct cost -> contingency -> overhead/margin -> net
7. VAT 20% -> gross -> +/- band -> displayed range
8. LLM writes assumptions and exclusions from the computed result
9. Operator reviews, presses send -> branded PDF

## 6. Repo layout

This is the planned layout. As built, `engine/`, `recipes/bathroom-refit.yaml`,
`catalogue/`, `data/pricebook/`, `clients/demo-nw/` (three of the four files),
`scripts/harvest_prices.py`, `scripts/quote_cli.py` and `tests/golden/` exist.
`agent/`, `app/`, `directives/`, `new_client.py`, `render_quote.py`, `branding.yaml`
and the kitchen recipe do not exist yet.

```
quote-engine/
  planning/                 product decisions, this spec
  directives/               SOPs
  engine/                   deterministic core
    errors.py               shared exception types
    money.py                Decimal helpers, half-up rounding
    quantities.py           safe formula evaluation
    models.py               typed dataclasses
    catalogue.py            SKU definitions, tier resolution
    prices.py               price book loading, discount resolution
    clientconfig.py         per-client labour, discounts, commercial
    recipes.py              load + validate recipe files
    quantify.py             parameters -> derived -> quantities (no money)
    pricing.py              quantities -> costed lines
    totals.py               contingency, margin, VAT, range, rounding
    quote.py                build_quote() — the one public entry point
  agent/
    intake.py               free text -> parameters
    narrative.py            result -> assumptions prose
    schemas.py              strict validation of model output
  scripts/
    harvest_prices.py       one-off capture -> dated pricebook
    new_client.py           scaffold a new firm's config
    render_quote.py         HTML -> branded PDF
  recipes/                  bathroom-refit.yaml, kitchen-refit.yaml
  catalogue/                SKU definitions
  data/pricebook/           YYYY-MM-DD.json (versioned, immutable)
  clients/<slug>/           labour · discounts · commercial · branding
  outputs/quotes/
  logs/
  tmp/
  tests/golden/             worked examples, hand-checked totals
  app/                      FastAPI + Jinja + HTMX
```

## 7. Data model

### 7.1 Catalogue — what exists, how it is measured. No prices.

```yaml
- id: tile-ceramic-mid
  name: Ceramic wall tile, mid range
  unit: m2
  category: finishes
  tiers: { budget: tile-ceramic-budget, premium: tile-porcelain-premium }

- id: adhesive-flexible-20kg
  name: Flexible tile adhesive 20kg
  unit: bag
  category: finishes
  discrete: true
  coverage: { unit: m2, per_unit: 4.5 }
```

`coverage` converts recipe units (m2, linear m) into purchasable units.
`discrete: true` forces rounding up to whole units — nobody buys 0.6 of a bag.

Categories: `timber`, `heavy-side`, `finishes`, `sanitaryware`, `electrical`,
`plumbing`, `plant`, `sundries`. Categories drive the discount matrix.

### 7.2 Price book — dated, immutable, one file per capture

```json
{ "captured": "2026-08-20",
  "source_run": "harvest_prices.py v1",
  "prices": {
    "tile-ceramic-mid":       { "list": 24.99, "unit": "m2",  "source": "<url>", "method": "scraped" },
    "aggregate-ballast-bulk": { "list": 62.00, "unit": "bag", "source": "manual", "method": "hand" }
  }}
```

`method` records provenance. Hand-entered heavy-side and plant prices are expected
and must be visibly distinguishable from scraped ones.

### 7.3 Client configuration: four small files, the whole personalisation story

```yaml
# clients/<slug>/labour.yaml          £/day, NW England
plumber: 300
tiler: 260
electrician: 320
plasterer: 250
joiner: 280
decorator: 220
labourer: 160

# clients/<slug>/discounts.yaml       % off list
default: 0.15
by_category: { timber: 0.38, heavy-side: 0.32, finishes: 0.20, sanitaryware: 0.35, plant: 0.0 }
by_sku: {}                            # overrides category

# clients/<slug>/commercial.yaml
overhead_margin: 0.22
contingency: 0.05
quote_band: 0.08
vat_rate: 0.20
display_rounding: 50

# clients/<slug>/branding.yaml
name: "Acme Bathrooms"
logo: logo.png
colours: { primary: "#1a3d5c", accent: "#c8a44d" }
services: [bathroom-refit, kitchen-refit]
```

These four files are all that changes from one firm to the next.

### 7.4 Recipes — the archetype, as data not code

```yaml
id: bathroom-refit
label: Bathroom refit

parameters:
  - { id: length_m, type: number, min: 1.2, max: 6.0 }
  - { id: width_m,  type: number, min: 1.2, max: 6.0 }
  - { id: height_m, type: number, default: 2.4 }
  - { id: spec_tier,     type: enum, values: [budget, mid, premium] }
  - { id: shower_type,   type: enum, values: [over-bath, walk-in, enclosure] }
  - { id: tiling_extent, type: enum, values: [floor-only, half-height, full-height] }
  - { id: layout_change, type: enum, values: [none, minor, full-move] }
  - { id: floor_type,    type: enum, values: [tile, lvt, vinyl] }

constants:
  tiling_factor:    { floor-only: 0.0, half-height: 0.5, full-height: 1.0 }
  shower_area:      { over-bath: 0.0, walk-in: 4.5, enclosure: 3.5 }
  first_fix_days:   { none: 1.0, minor: 1.5, full-move: 2.5 }

derived:
  floor_area_m2: length_m * width_m
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
    trade: plumber
    days: first_fix_days[layout_change]
    materials:
      - { sku: pipework-consumables, qty: 1 }

  - id: tanking
    trade: tiler
    when: shower_type != 'over-bath'
    days: tiled_area_m2 * 0.04
    materials:
      - { sku: tanking-kit, qty: ceil(shower_area_m2 / 5) }

  - id: tiling
    trade: tiler
    days: tiled_area_m2 / 6
    materials:
      - { sku: tile-ceramic-mid, qty: tiled_area_m2, waste: 0.10, tier: spec_tier }
      - { sku: adhesive-flexible-20kg, qty: tiled_area_m2, by_coverage: true }
```

**Bathroom task list (~12):** strip out · first fix plumbing · electrical first fix ·
stud/boarding alterations · tanking · floor prep · floor covering (trade follows
`floor_type`: tiler for tile, floor layer for lvt/vinyl) · wall tiling · sanitaryware and second
fix plumbing · electrical second fix · plastering and making good · decorating ·
final fix, silicone and clean.

**Kitchen task list (~12):** strip out · plumbing moves · electrical (ring main,
cooker circuit, lighting) · plastering and making good · flooring · unit install ·
worktop template and fit · splashback/tiling · appliance install · decorating ·
final fix and clean.

Kitchen is driven by **unit count and worktop linear metres**, not floor area.
**Appliances default to a provisional sum** — most firms do not supply them, and
quoting for a fridge you are not providing is exactly the error a customer pounces on.

`when:` lets tasks drop out when they do not apply. This is what makes the total move
sensibly when a dropdown changes.

### 7.5 Golden tests

Fixture jobs per recipe with hand-checked expected totals, covering each meaningful
variation (small/large, each spec tier, each shower type, each layout change).

## 8. Pricing pipeline — exact order

For each task where `when` evaluates true:

```
labour_days   = eval(task.days)
labour_cost   = labour_days * day_rate[task.trade]

for each material:
    raw_qty   = eval(material.qty)
    with_waste = raw_qty * (1 + material.waste)          # waste defaults to 0.0 if unset
    if by_coverage:  units = ceil(with_waste / sku.coverage.per_unit)
    elif sku.discrete: units = ceil(with_waste)
    else:            units = with_waste
    discount  = by_sku[sku] ?? by_category[sku.category] ?? default
    unit_net  = price_book[sku].list * (1 - discount)
    material_cost = units * unit_net
```

Then:

```
direct_cost = sum(labour_cost) + sum(material_cost)     # plant sits in materials, category 'plant', discount 0
contingency = direct_cost * commercial.contingency
cost_base   = direct_cost + contingency
net_price   = cost_base * (1 + commercial.overhead_margin)
gross       = net_price * (1 + commercial.vat_rate)
low         = round_to(gross * (1 - quote_band), display_rounding)
high        = round_to(gross * (1 + quote_band), display_rounding)
```

Display rounds to the nearest £50 — it reads like a builder's quote, not a computer's.
All money held as `Decimal`; rounding happens only at display.

**Tier resolution:** a material with `tier: spec_tier` resolves through the catalogue
`tiers` map before pricing. Missing tier variant falls back to the base SKU and logs.

**Missing price:** hard error, never a silent zero. The quote refuses to compute and
names the SKU. A setup that fails loudly in testing beats one that under-quotes on a live call.

## 9. LLM layer

Two calls, both language-only, both against the strongest available model.

**`agent/intake.py`** — `parse_intake(free_text, recipe) -> ParsedIntake`
Returns `{values: {...}, unresolved: [field_ids], suggested_questions: {...}}`.
Output validated in `agent/schemas.py` against a schema built from the recipe's
parameter definitions. Enum values outside the allowed set, numbers outside
min/max, or unknown field ids are **discarded and reported as unresolved**.

**`agent/narrative.py`** — `write_narrative(QuoteResult, client) -> prose`
Receives the computed result and produces the assumptions and exclusions paragraphs.
It may reference the *shape* of the job but is never asked to state or derive a
figure that is not already in the result object.

Both are pure functions over their inputs, mockable, and the engine has zero
dependency on either. The full pipeline is testable with the model turned off.

## 10. Formula evaluation

Recipe expressions run through a **restricted evaluator** (`simpleeval` or
equivalent) with a whitelisted namespace: parameter values, derived values,
constants, and `ceil`, `floor`, `round`, `min`, `max`. No imports, no attribute
access, no builtins, no dunder. Recipes are data; data must not execute.

**Lookup tables live in `constants:`, never inline in an expression.** An inline
map like `{ none: 1.0, full-move: 2.5 }[layout_change]` is not valid Python —
`full-move` parses as subtraction and the keys parse as names. Constants are
loaded from YAML as real dicts and indexed by a parameter value.

Recipe files are schema-validated on load — unknown keys, unknown trades, unknown
SKUs and unparseable expressions all fail at load time, not mid-call.

## 11. Interface — four screens

| Screen | Content |
|---|---|
| **1. Job type** | Client logo, their services as large tiles. Two clicks in. |
| **2. Intake** | Free-text box above, form below. Parsed fields settle green; unresolved pulse amber with a suggested question to read aloud. |
| **3. Quote** | Large range. Four-line breakdown: labour, materials, plant, contingency. Dropdowns stay live on the side — change one, total updates instantly. |
| **4. Internal detail** | Staff only. Every line, every SKU, cost vs sell, margin. |

Then: preview PDF -> **operator presses send**. Nothing leaves automatically.

Screen 3's recompute must be visibly instant, because the operator is talking to the customer while it happens.

## 12. Output

- **Customer-facing PDF:** branded, two pages. Range, category-level breakdown,
  assumptions, exclusions, "subject to site survey". **Never itemised** — a
  line-by-line breakdown at cost is a shopping list for a cheaper competitor.
- **Internal view:** full itemisation, on screen only.
- Quotes written to `outputs/quotes/`, run records to `logs/`.

## 13. Stack

Python 3.12 · FastAPI · Jinja2 + HTMX · Tailwind · WeasyPrint · `uv`.
No Node build step. One command to run. PDF shares styling with the app so
branding is set in one place. Runs locally on the office machine; no hosting, no auth,
no personal data leaving the machine.

## 14. Build sequence

| # | Milestone | Output |
|---|---|---|
| 1 | Engine core: recipe loader, safe evaluator, pricing, totals | CLI produces a bathroom quote from a stub catalogue |
| 2 | Catalogue + `harvest_prices.py` + first price book | Real materials pricing |
| 3 | NW day rate research + client config files | Real labour pricing |
| 4 | Golden tests for bathroom | Regression safety net |
| 5 | FastAPI app, screens 1 to 4 | Usable without the LLM |
| 6 | LLM intake + narrative + schema guards | The "clever" moment |
| 7 | PDF + branding + `new_client.py` | Ready for a firm to use |
| 8 | Kitchen recipe | Second vertical |
| 9 | Directives and run books | Operable by someone else |

Milestones 1 to 5 give a working tool. 6 to 9 finish it. Milestones 1 to 4 are built.

## 15. Assumptions to verify with the trade

These are the numbers that decide whether the quote is believable. All should be
sense-checked by someone working in NW England before the tool is used for real.

1. Day rates per trade (research first, then confirm)
2. Labour day allowances per task — the single biggest source of error
3. Typical overhead + margin for a small domestic firm (assumed 22%)
4. Typical merchant discount by category (assumed 15-38%)
5. That appliances are normally excluded / provisional in kitchen quotes
6. Skip sizing and muck-away assumptions

## 16. Risks

| Risk | Mitigation |
|---|---|
| Labour allowances wrong -> whole quote wrong (labour is 50-60% of these jobs) | Golden tests + trade sense check before first real use |
| Builder spots a missing line item | Task lists reviewed by someone in the trade |
| Price drift in cached book | Acceptable for a ballpark; scheduled refresh once a firm uses it day to day |
| List price != what the builder pays | Discount matrix: the quote is built at the firm's own buying cost |
| Failure on a live call | Zero network calls at quote time; LLM parse failure degrades to manual form entry |
| Expectation that it quotes any building work | Archetypes are a growing library; each new job type is a new recipe file |

## 17. Deferred, with the seam already in place

- **Price source** is behind an interface. Swapping cached -> scheduled scrape ->
  merchant feed/EDI is one module, not a rewrite, so connecting a firm's own
  merchant trade account later does not touch the engine.
- **Archetypes** are data. New verticals are authoring work, not engineering.
- **External customer-facing version** reuses the engine with the internal view
  removed and tighter input validation.
