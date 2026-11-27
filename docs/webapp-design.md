# Quote engine: web app design spec (Plan 2)

**Date:** 2026-08-21
**Status:** Approved for planning. Not built yet: no `app/` or `agent/` code exists in this repo.
**Builds on:** [`design.md`](design.md) (§9, §11 amended here)
**Depends on:** Plan 1, complete and merged — deterministic engine, 490 tests

---

## 1. Purpose

An internal web tool for the person answering the phone at a UK domestic building
firm. A customer calls asking what a new bathroom costs. Today that person cannot
answer. This tool lets them give a defensible ballpark **while the caller is still
on the line**, without knowing the trade.

It amends §11 of the product design, which specified a form with a free-text box
above it. The interaction is now conversational: a chat panel that fills a job
sheet, with the job sheet remaining the primary, always-editable surface.

## 2. Users

| User | Context | Needs |
|---|---|---|
| **Receptionist** (primary) | Live call, untrained, customer talking | Told what to ask; cannot enter an invalid value; never has to scroll to check state |
| **Firm owner** | Reviewing, configuring | Sees how the number was built; can defend it |
| **Setup operator** | Configuring a new firm | Never fails on a live call; a new firm is set up in about 20 min |

## 3. Success criteria

1. Complete bathroom quote in **under 60 seconds** from a standing start.
2. An untrained user can complete one **without training**, because the tool
   supplies the questions.
3. Changing any field recomputes the total **visibly instantly**.
4. **The whole tool works with no API key and no network.** Free-text parsing
   degrades; nothing else does.
5. An invalid parameter value **cannot** enter the engine, whatever the model emits.

## 4. Scope

### In scope

- Two screens: job-type picker, and the split workspace
- Chat panel with authored questions and quick-reply chips
- Job sheet: nine rows, all directly editable, always visible
- Quote panel: range plus labour / materials / plant / contingency
- Internal detail: expandable, every task and SKU with cost vs sell
- LLM free-text parsing into parameter deltas
- LLM assumptions and exclusions narrative
- Branded PDF: preview and download, operator-initiated
- Graceful degradation when the model is unavailable

### Out of scope

- **Email sending.** Needs per-client SMTP, a sending domain, deliverability, and
  puts customer addresses into the tool. Dragging a PDF into an email takes
  four seconds. Deferred indefinitely.
- **Kitchen recipe** — Plan 3. The app is recipe-agnostic; the kitchen appears as
  a second tile with no code change.
- **Dark mode.** A laptop in a bright office. Tokens allow it later; nothing
  half-built ships.
- Voice input, customer-facing self-serve version, multi-tenant hosting, auth,
  persistence beyond the session, analytics.

## 5. The hard rule, restated

**The LLM never performs arithmetic and never sees a price.** It has exactly two
jobs, both linguistic. Every pound comes from Plan 1's engine.

This is a correctness property, and it gives a straight answer when a builder asks
"how do I know it isn't inventing the prices?": it structurally cannot.

## 6. Architecture

### 6.1 Authored questions, not generated ones

Each recipe parameter gains four presentation fields — `label` and `unit` so the
job sheet reads as English rather than as field ids, and `ask`/`labels` for the
conversation:

```yaml
- id: shower_type
  type: enum
  label: "Shower"
  values: [over-bath, walk-in, enclosure]
  ask: "What kind of shower is she after?"
  labels:
    over-bath: "Over the bath"
    walk-in:   "Walk-in wetroom"
    enclosure: "Separate enclosure"

- id: length_m
  type: number
  label: "Room length"
  unit: "m"
  min: 1.2
  max: 6.0
  ask: "How long is the room?"
```

Consequences, all of them wanted:

- **Zero latency on a chip click** — no model call, pure Python.
- **Questions phrased in trade language we control**, consistently, rather than
  whatever the model produces on the day.
- **Chips are provably the recipe's allowed values**, so an invalid value cannot
  be offered.
- **The tool works completely with no API key.**

### 6.2 The two LLM calls

| Call | Trigger | Input | Output |
|---|---|---|---|
| `parse_intake` | Operator types free text | their text + the recipe's parameter schema | parameter deltas + unresolved list |
| `write_narrative` | Quote complete, PDF requested | the computed `QuoteResult` | assumptions and exclusions prose |

Both are pure functions over their inputs, mockable, and the app has a working
path without either.

`write_narrative` receives the computed result and may reference the *shape* of
the job. It is never asked to state or derive a figure not already in the result.

**`write_narrative` is called once, when the operator presses Preview PDF — never
on recompute.** Otherwise every dropdown change would cost a model call and the
live-recompute promise in §7.2 would be untrue. If the call fails, the PDF still
renders with a stock assumptions block authored in the template; the narrative is
an enhancement, never a dependency.

### 6.3 A turn

```
operator types free text
        |
   parse_intake  ---- fails/timeout ----> quiet degradation notice, job sheet unaffected
        |
   schema validation      (invalid values discarded, reported unresolved)
        |
   merge into session parameters
        |
   all 7 required present?  --yes-->  build_quote(...)   ~16ms
        |
   next unfilled field -> its authored `ask:` + chips from `values:`/`labels:`
        |
   HTML fragments returned: chat append, job sheet, quote panel
```

A chip click skips straight to schema validation — no model call.

### 6.4 Files

```
app/
  main.py             FastAPI routes
  session.py          in-memory sessions, keyed by cookie
  render.py           QuoteResult -> view models (pure, unit-tested)
  templates/
    base.html  index.html  quote.html
    _chat.html  _jobsheet.html  _quotepanel.html  _detail.html
    pdf.html
  static/
    app.css           design tokens + components
    inter/            self-hosted woff2
agent/
  client.py           Anthropic wrapper: timeout, one retry, degrade cleanly
  intake.py           free text -> parameter deltas
  schemas.py          strict validation of model output
  narrative.py        QuoteResult -> assumptions prose
scripts/
  render_pdf.py
  new_client.py
```

### 6.5 Engine changes

Four additive optional fields on `Parameter` in `engine/recipes.py` (`label: str
| None`, `unit: str | None`, `ask: str | None`, `labels: dict[str, str]`), all
presentation-only and ignored by every existing code path, plus the content in
`recipes/bathroom-refit.yaml`. Nothing else under `engine/` changes. All 490
existing tests keep passing.

### 6.6 Stack

Python 3.12 · FastAPI · Jinja2 · HTMX · hand-written CSS · WeasyPrint · `uv`.

No Node build step. No CSS framework — the design is specific enough that
utility classes would fight it. Session state in memory: one operator, one
laptop, no database. Fonts self-hosted, never a CDN.

## 7. Screens

### 7.1 Job type

Client logo, services as large tiles. One tile today. Two clicks in.

### 7.2 Workspace (55 / 45 split)

**Left — the conversation.** The operator types what they hear, in any order, as
messy as they like. The assistant replies with the next question and its chips.
Free text and chips both work at any time: a fast operator types "2.4 by 1.8 mid
range walk-in tiles to ceiling" and fills four fields at once.

**Right — the job sheet.** Nine rows, always visible, **always directly
editable** — every row a real input, not a read-out. Filled rows settle; unfilled
rows show a dash. The two defaulted rows (`height_m` 2.4, `openings_m2` 2.2) show
their default greyed and edit on click.

**Beneath it — the quote panel.** Before all seven required fields are present it
names what is still needed. When the last lands, the range appears with the
four-line breakdown: labour, materials, plant, contingency.

**Every edit recomputes.** At ~16ms this is genuinely instant, so there is no
loading state — a spinner would be a lie.

### 7.3 Internal detail

A toggle within the workspace, not a separate page. Expands to every task with
trade, days and day rate, and every SKU with units, unit net, list price and the
discount applied. Staff-facing only; never in the customer PDF.

### 7.4 Output

Preview PDF, then download. Operator-initiated; nothing leaves automatically.

Customer PDF: branded, two pages, range, category-level breakdown, assumptions,
exclusions, "subject to site survey". **Never itemised** — a line-by-line
breakdown at cost is a shopping list for a cheaper competitor.

## 8. Degradation

The job sheet is built first and is the primary interface. The chat is an
accelerator layered on top.

When a model call fails, times out, or no API key is configured, the chat panel
shows one quiet line — *"Assistant unavailable — fill the sheet directly."* —
and everything else continues working, because the pricing engine is local and
needs nothing.

Because the job sheet came first, this path is exercised by every test that runs
without a key, rather than being a fallback nobody has run.

## 9. Visual system

Light only, committed.

```css
--paper:      #FBFAF7   /* app ground */
--surface:    #FFFFFF   /* job sheet, quote panel */
--ink:        #16181C   /* primary text, buttons */
--ink-muted:  #6E7076   /* labels, secondary */
--line:       #E6E3DC   /* hairlines */
--accent:     #1F4E46   /* deep pine: confirmed state, primary action */
--needed:     #B4741A   /* amber: the field being asked about */
```

Pine rather than a tech blue: blue is the default accent of every SaaS product
the firm has already ignored, and it goes cold against warm paper.

**Type:** Inter, one family, **self-hosted woff2**. Not a CDN link: the office
machine may have no wifi, and the tool must look and work the same with no
network at all.

Money uses `font-variant-numeric: tabular-nums` throughout. When the operator
changes a dropdown and the total recomputes, proportional digits visibly jump and
shuffle; tabular figures change in place. That is the difference between "the
software updated" and "the software glitched".

**Space:** 4px base; 24/32/48 panel padding. Generous. Cramming is the most
common way an internal tool looks cheap.

**Motion:** one thing — a 180ms crossfade on the total when it changes. No slide,
no bounce, no spinner.

The PDF shares these tokens via WeasyPrint, so the preview is what the customer
receives and branding is set in one place.

## 10. Testing

- **View models** (`app/render.py`) are pure functions with unit tests.
- **Routes** tested with FastAPI `TestClient` — no browser, no API key.
- **LLM layer mocked**, plus a **hostile-output test**: feed the validator
  garbage, invalid enum values, out-of-range numbers, unknown field ids and
  prompt-injection strings, and assert none reaches the engine.
- **One end-to-end test with the API key deliberately unset**, asserting a
  complete quote is still reachable — so degradation cannot silently rot.
- **A test asserting no model call occurs on recompute**: drive a chip click and
  a field edit with a mock that raises if called. This pins the §6.2 timing rule,
  which is otherwise a comment nothing enforces.
- Plan 1's 490 tests keep passing throughout.

## 11. Build order

Chosen so the fallback path is the foundation, not an afterthought.

| # | Milestone | Delivers |
|---|---|---|
| 1 | `label`/`unit`/`ask`/`labels` on `Parameter` + recipe content | Authored questions, English job sheet |
| 2 | Session store + view models | Pure, testable, no HTTP |
| 3 | **Job sheet screen — no chat, no LLM** | A usable quoting tool |
| 4 | Quote panel + live recompute | Instant totals |
| 5 | Internal detail toggle | "How did it get that?" |
| 6 | Chat panel: authored questions + chips, no LLM | Feels like the product |
| 7 | `parse_intake` + schemas + degrading client | Free text works |
| 8 | `write_narrative` | Assumptions and exclusions |
| 9 | PDF | Something to hand over |
| 10 | Visual polish pass | Premium rather than fine |
| 11 | `new_client.py` | Twenty minute setup for a new firm |

Milestones 1 to 6 give a usable tool with no API key at all.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Model unavailable mid-call | Job sheet is primary and complete; degradation tested on every keyless run |
| Model emits an invalid parameter value | Strict schema validation; chips generated from the recipe, never from the model |
| Prompt injection via caller-quoted text | Model output is data, never instructions; only whitelisted field ids and allowed values are merged |
| Font or asset fails to load offline | Everything self-hosted; no CDN anywhere |
| Recompute feels sluggish | 16ms measured; fragments not full pages; no spinner; `write_narrative` fires only on PDF preview, never on recompute |
| Operator loses track of state on a live call | Job sheet always visible; no scrolling to check |

## 13. Deferred, with the seam in place

- **Email** — the PDF exists; sending is an SMTP config away if a client insists.
- **Kitchen and further archetypes** — recipe-agnostic; a new YAML is a new tile.
- **Customer-facing version** — same engine, internal detail removed, tighter
  input validation.
