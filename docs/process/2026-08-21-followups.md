# Quote engine: outstanding work after Plan 1

Compiled from sixteen code reviews during the Plan 1 build (2026-08-20/21).
Plan 1 delivered the deterministic engine; this is everything deliberately
left undone, ranked.

---

## 1. Take this to a bathroom fitter — highest value, lowest effort

Nothing on this list matters as much as fifteen minutes with someone in the
trade looking at `--detail` output and saying which lines he'd argue with.
Run:

```
uv run python -m scripts.quote_cli --recipe bathroom-refit \
  --param length_m=2.4 --param width_m=1.8 --param spec_tier=mid \
  --param shower_type=walk-in --param tiling_extent=full-height \
  --param layout_change=none --param floor_type=tile --detail
```

Ask him specifically about:

- **Days per task.** Labour is 50-60% of the job, so a wrong allowance
  dominates every material error combined. Second fix / suite install is
  currently 1.0-1.25 days; two reviewers thought 1.5-2.0 is realistic for
  bath, basin, WC, taps, towel rail and commissioning.
- **Strip out** assumes one labourer for a day. Two men is reality — the
  model has no crew concept, so the allowance has to absorb it.
- **Floor tiling at 5 m2/day** — slow, though it self-corrects on a small
  cut-heavy floor.
- **What's missing from the nineteen tasks** (see section 2).

## 2. Content gaps a builder would notice

Each needs a new SKU and a price, so they land together as one content pass.

| # | Gap | Why it matters |
|---|-----|----------------|
| 1 | **No Part P certificate** despite two electrician tasks | £100-250 a builder actually carries; first thing a spark asks about |
| 2 | **No tile trim / edging** anywhere | Small money, large signal — every tiled job has it |
| 3 | **No bath panel, boxing-in of the soil stack, or skirting** | The joiner is already on site for boarding and floor prep |
| 4 | **No fan ducting or external grille** despite specifying an extractor | Line item a customer expects to see named |
| 5 | **`floor_prep` buys 18mm ply AND levelling compound on every job** | Real practice is one or the other — ply over timber, latex over concrete. Reads as padding. Wants a `floor_substrate: [timber, concrete]` parameter gating each |
| 6 | **`spec_tier` reaches only 3 SKUs** (suite, shower valve, wall tile) | "Premium" still buys a standard floor tile, enclosure and towel rail |
| 7 | **`cable-1_5mm-50m` qty is always 1** even at `layout_change: none` | Nothing is re-cabled on a like-for-like swap |

## 3. Two coverage rates that are wrong — ask the trade contact

Both are one-number edits in `catalogue/materials.yaml`:

- **`plaster-skim-25kg` at 10.0 m2/bag** is a *single-coat* figure. A whole
  bathroom currently orders one £6.38 bag. A plasterer reading the detail
  view will notice this faster than anything else on the screen.
- **`adhesive-flexible-20kg` at 4.5 m2/bag** is right for a 6mm wall notch
  but a 10mm floor bed is nearer 3 m2/bag, so floor adhesive under-orders
  by roughly 30%. Wants separate wall and floor SKUs.

Checked and correct: paint at 12 m2/tin (conservative for mist + two coats),
tanking at 4.0 m2 (matches the priced product), board and ply at 2.88 m2
(real metric sheet sizes).

## 4. Pricing provenance

Several sourced figures are **Screwfix / Wickes / Victorian Plumbing retail**
prices, while the discount matrix assumes **merchant list** prices. That makes
timber, heavy-side and sanitaryware buying prices optimistic. Quantified
during review at roughly 2-3% of the total — comfortably inside the ±8% quote
band, but worth correcting.

**The fix is to re-source timber and heavy-side from Travis Perkins or Huws
Gray list prices. Do NOT compensate by editing the discount matrix** — that
would hide the problem rather than fix it.

Also: these are live retail prices captured 2026-08-21. One tile moved £35 →
£40 in a single day during the build. **Re-run `uv run python -m
scripts.harvest_prices` before quoting for real.**

## 5. Engineering debt, none of it on the quote path

- **Move recipe-shape validation from `quantify` to `load_recipe`.** The
  codebase states "fail at load, not mid-quote" and enforces it for SKU
  references, but unknown parameter types, duplicate ids, valueless enums and
  non-numeric bounds are all diagnosed at quote time. It doesn't bite today
  because the 243-combination sweep in `tests/test_content.py` catches them in
  CI — but it will bite whoever authors the kitchen recipe. **Do this before
  Plan 3.** Fold in the `engine/quote.py` double `build_namespace` call at the
  same time, since both want the same signature change.
- `catalogue.py:35` reads `coverage.unit` and discards it — nothing checks it
  against the SKU's own unit. Worth a look when the kitchen catalogue lands
  and coverage units stop all being m2.
- `quantities.py` silently truncates a multi-statement expression like
  `1; something_else` and emits a warning rather than raising. No exposure —
  recipe formulas are author-trusted and the LLM layer never writes them.
- `--check` validates one recipe against one client; a second recipe will want
  a loop.
- `require_rate` excludes 1.0, so a genuine 100% category discount would need
  a code change rather than a config edit.

## 6. Explicitly closed — do not revisit

- **Labour share.** Was flagged as possibly too high against placeholder
  prices. With researched prices the four golden cases sit at 54.8 / 57.5 /
  60.1 / 63.8%. Three are in or at the edge of the 50-60% band; the outlier is
  a small budget job that is legitimately labour-dominated. No day-rate work
  indicated.
- **Plastering allowance.** Recalibrated during Plan 1 from 0.06 to 0.035
  day/m2 (16.7 → 28.6 m2/day) against sourced figures of 20-40.
- **Walk-in shower ordering.** Was backwards (cheapest of three); now carries
  a former, linear drain and glass panel and is correctly the dearest.
  Verified: over-bath £7,091 < enclosure £7,795 < walk-in £8,832.

## 7. Next plans

- **Plan 2** — FastAPI app, four screens, LLM intake parsing, assumptions
  narrative, branded PDF, `new_client.py`.
- **Plan 3**: kitchen recipe and directives.

`build_quote` runs in ~16ms, so HTMX-driven live recompute on the quote screen
will feel instant even reloading every file per request.
