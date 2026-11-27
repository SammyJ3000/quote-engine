# Quote engine

[![CI](https://github.com/SammyJ3000/quote-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/SammyJ3000/quote-engine/actions/workflows/ci.yml)

A deterministic quote engine for small UK building firms. You give it a few room measurements and spec choices, and it gives back a priced bathroom refit where every pound traces back to a day rate, a quantity and a dated list price.

## The problem

A customer rings a small building firm and asks how much a new bathroom will cost. Usually whoever picks up can't say. They take some details, promise a call back, and the owner prices it days later at nine at night. By then the customer has rung someone else.

I built this so whoever answers the phone can give a defensible ballpark while the customer is still on the line. The value is speed to quote, not precision to the pound. A quote takes about 20 milliseconds on my laptop, including reading every config file from disk, and it needs no network at all. Prices are captured ahead of time into a dated file, so nothing can fail during a call because a website is slow or the wifi has dropped.

## How it works

There are three kinds of data and one pipeline.

**A recipe** (`recipes/bathroom-refit.yaml`) describes the job as data, not code. It declares the inputs: room length, width and height, door and window area, spec tier, shower type, tiling extent, layout change and floor type. Each number has a minimum and maximum and each choice has a fixed list of allowed values. Derived values such as wall area and tiled area are formulas over those inputs. Then come 19 tasks, each with a trade, a formula for the days it takes, and the materials it uses. A task can carry a `when:` condition, so tanking drops out when the shower is over the bath.

**A catalogue** (`catalogue/materials.yaml`) says what each of the 37 materials is and how it is bought: wall tiles by the square metre, adhesive in 20kg bags that cover 4.5 m², plasterboard by the sheet. Anything sold in whole units is always rounded up, because nobody buys 0.6 of a bag. Spec tiers point a mid range item at its budget and premium alternatives.

**Money** comes from two places. A versioned price book (`data/pricebook/2026-08-21.json`) holds list prices, one immutable file per capture date. A folder per firm (`clients/demo-nw/`, a fictional firm in Northwest England) holds that firm's labour card, its merchant discounts by category, and its commercial settings: contingency, overhead and margin, VAT, quote band and display rounding.

The engine evaluates the recipe formulas in a restricted evaluator (simpleeval, with attribute access removed and only `ceil`, `floor`, `round`, `min`, `max` and `abs` allowed), turns quantities into units you can actually buy, prices each one at list less the firm's discount, and adds labour as days times day rate. It then applies contingency, overhead and margin, and VAT. The customer hears a range: the gross figure plus or minus 8%, rounded to the nearest £50, because that sounds like a builder's quote rather than a computer's.

Money is held as `Decimal` throughout and rounded half up to the penny at each step. Floats only exist inside formula evaluation, and they are rounded to nine decimal places at the single point where they become `Decimal`.

Validation is strict and specific. Every config file is checked as it loads, and every error names the file and the key. Recipes are checked for unknown materials when they load. A missing price is a hard error that names the material, never a silent zero. A quote that refuses to run is better than one that quietly comes in low.

## Example

This is the demo firm quoting a standard 2.4m by 1.8m bathroom with a walk in shower, mid range spec, tiled floor to ceiling, no layout change:

```
$ uv run python -m scripts.quote_cli --recipe bathroom-refit \
    --param length_m=2.4 --param width_m=1.8 --param spec_tier=mid \
    --param shower_type=walk-in --param tiling_extent=full-height \
    --param layout_change=none --param floor_type=tile
Bathroom refit — demo-nw
Prices captured 2026-08-21

  £8,100 – £9,550 inc VAT

  Labour       £3,146.07
  Materials    £2,359.11
  Plant        £240.00
  Contingency  £287.26
  ----------------------------
  Net          £7,359.58
  VAT          £1,471.92
  Gross        £8,831.50
```

Height and door and window area weren't given, so the recipe defaults of 2.4m and 2.2 m² were used. Adding `--detail` prints the internal view: every task with its trade, days and day rate, and every material with units, list price, discount and line cost. These are its first lines:

```
Internal detail:
  Strip out and muck away — labourer 0.93d @ £130 = £121.16
      Skip, 6 yard, delivered and colle…  skip-6yd                   1.00 each   @ £  240.00 (list £240.00 less 0%) = £240.00
  First fix plumbing — plumber 1.00d @ £285 = £285.00
      Pipework, fittings and consumables  pipework-consumables       1.00 each   @ £  140.00 (list £200.00 less 30%) = £140.00
      Waste and trap kit                  waste-kit                  1.00 each   @ £   40.60 (list £58.00 less 30%) = £40.60
```

Bad input is refused with a reason rather than turned into a strange number:

```
$ uv run python -m scripts.quote_cli --recipe bathroom-refit --param height_m=24 ...
error: parameter 'height_m' value 24.0 above maximum 3.5

$ uv run python -m scripts.quote_cli --recipe bathroom-refit --param spec_tier=luxury ...
error: parameter 'spec_tier' value 'luxury' not one of ['budget', 'mid', 'premium']
```

## Status

**Done and tested:** the engine, the bathroom refit recipe, the catalogue with researched Northwest England list prices, the demo firm's config, the quote CLI, the `--check` setup validator, and the price book script. 490 tests, all passing in CI.

**Designed but not built yet:**

* **LLM intake.** The person on the phone types what they hear in free text, and a model turns it into the form fields. Its output is validated against a schema generated from the recipe, so a value outside the allowed set is thrown away. The model never does arithmetic and never sees a price.
* **The web app.** The first spec had four screens; the later web app spec reworks that into a job type picker and a workspace with a chat panel, an always editable job sheet and a live quote panel. It also covers an assumptions and exclusions narrative and a branded PDF.
* **A kitchen recipe**, which should need no engine changes, only a new YAML file.

Both specs are in [`docs/`](docs/), and the step by step plans are in [`docs/process/`](docs/process/).

## What broke and what changed

**Float noise bought a whole extra tin of paint.** A 2.0m by 1.8m room, 2.5m high and half tiled leaves exactly 12 m² to paint, and a tin covers 12 m². But the formulas run in float, so the area came out as 12.000000000000002, and rounding up to whole tins turned that last bit into a second tin. A sweep of about 150,000 parameter combinations found 14 cases like it, and the same path runs through plasterboard and plywood sheets. The fix was to round once, to nine decimal places, at the one point where floats become `Decimal`. There is a test pinned to that exact room.

**A typo quoted minus £78,100.** A discounts file with `default: 15`, meaning 15%, was read as a 1500% discount and produced a negative quote with no warning. A day rate written as `£285` crashed with a raw traceback. Now every number in every config file goes through one validator that checks its type and range and names the file and the key:

```
error: client 'demo-nw' discounts.yaml key 'default' must be a rate between 0 and 1 (0.15 means 15%), got 15
```

**The golden tests couldn't see a margin change.** They pinned the low and high figures, but those are rounded to the nearest £50, so nudging overhead and margin from 0.22 to 0.221 moved nothing. The golden cases now pin the exact gross too, and I checked that all four fail under that change.

**A YAML shortcut silently cut a formula in half.** In a flow mapping like `{ sku: downlight, qty: max(3, ceil(x)) }` the comma ends the entry, so the quantity was read as the string `max(3`. The recipe still loaded and only failed when a quote ran. Formulas with commas in them are now quoted. Catching that kind of recipe error at load time instead of quote time is on the list in [`docs/process/2026-08-21-followups.md`](docs/process/2026-08-21-followups.md).

## Setup and run

You need [uv](https://docs.astral.sh/uv/). It will fetch a suitable Python (3.12 or later) if you don't have one.

```
uv sync
uv run pytest
```

Quote a job with the command in the example above. Every parameter without a default must be given; leave one out and the CLI tells you which one is missing.

To set up a new firm, copy `clients/demo-nw/` to `clients/<your-firm>/`, edit the three files, and run the setup check before quoting:

```
uv run python -m scripts.quote_cli --recipe bathroom-refit --client <your-firm> --check
```

It checks the whole recipe against that firm's setup in one go: every trade any task uses has a day rate, and every material any task can resolve to, every spec tier included, has a usable price. It lists every gap rather than stopping at the first, and exits with code 1 if there are any. For example, with the plumber removed from the labour card:

```
Setup check: recipe 'bathroom-refit' + client 'new-firm'

1 problem(s) to fix before quoting:
  - no day rate for trade 'plumber' in client 'new-firm' labour.yaml (needed by first_fix_plumbing, second_fix_plumbing, shower_enclosure_fit, wetroom_kit_fit, bath_screen_fit, final_fix)
```

### The price book script

`scripts/harvest_prices.py` builds a new dated price book. It is run by hand when prices need refreshing, never at quote time:

```
uv run python -m scripts.harvest_prices
```

Today it reads hand entered list prices from `catalogue/manual_prices.yaml`, checks that every material exists in the catalogue and every price is a positive number, records each one as hand entered, and writes `data/pricebook/<today>.json` atomically so a failed run can't damage an existing book. It lists any material still unpriced. The engine always uses the newest book.

It does not fetch anything from the web yet. The fetch step is a stub that returns nothing, and `catalogue/sources.yaml` has no URLs filled in. The current prices were looked up by hand from public product pages at Screwfix, Wickes, Victorian Plumbing, B&Q and a Greater Manchester skip firm, converted from inc VAT to ex VAT, with the source URL written above each line. Four are estimates and are marked as such. The day rates were researched the same way from published rate guides. All of it is written up in [`docs/rates-research.md`](docs/rates-research.md).

## Tests

490 tests, run with `uv run pytest`. The main groups:

* **Golden cases** (`tests/golden/`): four complete jobs (small budget, standard, large mid range, large premium) that pin the low and high range, labour, materials, plant and exact gross. Each case sets every parameter explicitly, so a changed default can't move them silently. When a formula or price changes on purpose, `uv run python -m scripts.update_golden` rewrites them and the diff gets read before it is committed.
* **The content sweep** (`tests/test_content.py`): all 243 combinations of the five choice inputs, each at the smallest and largest allowed room and with a case that drives wall area to zero, must produce tasks with no negative days or quantities. It also checks that every material has a price, every number input has both bounds, and the shipped setup passes `--check`.
* **Loaders and validation**: recipes, catalogue, price book and client config each reject malformed files with an error that names the file, including quoted booleans like `"false"`, non numeric rates and out of range discounts.
* **Pricing, totals and money**: discount lookup order, rounding, VAT, the quote band, and the order contingency, margin and VAT are applied in.
* **The CLI and the price book script**, including the atomic write.

## Stack

Python 3.12, PyYAML, simpleeval, pytest, ruff and uv, with GitHub Actions running ruff and the tests on every push to main and every pull request.

## Where things are

| Path | What it holds |
|---|---|
| `engine/` | The engine. `quote.py` has `build_quote()`, the one public entry point. |
| `recipes/` | Job recipes. One so far: `bathroom-refit.yaml`. |
| `catalogue/` | Material definitions, hand entered list prices, and the empty source URL list. |
| `data/pricebook/` | Dated, immutable price books. |
| `clients/demo-nw/` | The fictional demo firm: labour card, discounts, commercial settings. |
| `scripts/` | The quote CLI, the price book script, and the golden case updater. |
| `tests/` | The test suite, with golden cases in `tests/golden/`. |
| `docs/` | The design spec, the web app spec and the rates research. |
| `docs/process/` | The build plans and review follow ups. |

---

This repo was published from a private working copy, so earlier history is not included.

I'm Sam Jordan. I design and build apps and AI tools. More of my work: https://sam-jordan-cv.vercel.app
