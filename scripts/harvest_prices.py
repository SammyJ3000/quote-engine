"""Capture current list prices into a dated, immutable price book.

Run by hand ahead of time, never at quote time. This is the one module where
network access is allowed to live; fetch_prices() below is still a stub, so
today every price comes from the hand-entered file.

UK builders' merchants have no public developer API, so pricing is a mix of
published web prices and hand-entered trade figures. Heavy-side goods (bulk
aggregates, blocks, ready-mix, skips, muck-away) are quoted per branch by
phone and are simply not published anywhere — hand-entered prices are a
first-class, expected mode here, not a fallback. The `method` field on each
priced SKU records provenance ("scraped" vs "hand") so a hand-entered figure
stays visibly distinguishable from a scraped one.

Usage:
    uv run python -m scripts.harvest_prices --manual catalogue/manual_prices.yaml
"""

import argparse
import json
import math
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

import yaml

from engine.catalogue import Catalogue, load_catalogue

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class HarvestError(Exception):
    """A harvested or hand-entered price is malformed: unknown SKU or bad value."""


def _validated_sku(catalogue: Catalogue, sku_id: str, kind: str):
    """Look up a SKU, raising a clear error if the price file names one that doesn't exist."""
    if sku_id not in catalogue:
        raise HarvestError(f"{kind} price file names unknown SKU {sku_id!r} — not in the catalogue")
    return catalogue.get(sku_id)


def _validated_price(sku_id: str, value, kind: str) -> float:
    """Reject anything that isn't a positive, finite number — never coerce silently."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HarvestError(f"{kind} price for {sku_id!r} must be a number, got {value!r}")
    if not math.isfinite(value):
        raise HarvestError(f"{kind} price for {sku_id!r} must be a finite number, got {value!r}")
    if value <= 0:
        raise HarvestError(f"{kind} price for {sku_id!r} must be positive, got {value!r}")
    return value


def merge_prices(
    catalogue: Catalogue,
    fetched: dict[str, tuple[float, str]],
    manual: dict[str, float],
    captured: str,
) -> dict:
    """Combine scraped and hand-entered prices. Manual always wins.

    Provenance is recorded per SKU so hand-entered heavy-side and plant prices
    stay visibly distinguishable from scraped ones. Every SKU id and price is
    validated here so a malformed source file fails loudly at harvest time,
    not silently at quote time.
    """
    prices: dict[str, dict] = {}

    for sku_id, (value, source) in fetched.items():
        sku = _validated_sku(catalogue, sku_id, "fetched")
        price = _validated_price(sku_id, value, "fetched")
        prices[sku_id] = {"list": price, "unit": sku.unit, "source": source, "method": "scraped"}

    for sku_id, value in manual.items():
        sku = _validated_sku(catalogue, sku_id, "manual")
        price = _validated_price(sku_id, value, "manual")
        prices[sku_id] = {"list": price, "unit": sku.unit, "source": "manual", "method": "hand"}

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


def load_manual_prices(path: Path) -> dict[str, float]:
    """Load hand-entered prices from a YAML mapping of sku_id -> price.

    A missing file is not an error — it simply means no manual prices have
    been entered yet, and the `unpriced` list in the output will show what's
    outstanding rather than the run crashing. An empty file is likewise
    treated as no manual prices. Anything that isn't a mapping (a list, a
    scalar, invalid YAML) fails loudly with a message naming the file.

    Both of those "no manual prices" cases still print a line naming the
    path, so a typo'd --manual path gets a direct signal rather than only
    showing up later as extra entries in the `unpriced` list.
    """
    if not path.exists():
        print(f"no manual prices loaded from {path} (file not found)")
        return {}

    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        sys.exit(f"manual prices file {path} is not valid YAML: {exc}")

    if raw is None:
        print(f"no manual prices loaded from {path} (file is empty)")
        return {}

    if not isinstance(raw, dict):
        sys.exit(
            f"manual prices file {path} must be a mapping of sku_id: price, "
            f"got {type(raw).__name__}"
        )

    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture prices into a dated price book.")
    parser.add_argument("--manual", default=str(PROJECT_ROOT / "catalogue" / "manual_prices.yaml"))
    parser.add_argument("--out", default=str(PROJECT_ROOT / "data" / "pricebook"))
    args = parser.parse_args(argv)

    materials_path = PROJECT_ROOT / "catalogue" / "materials.yaml"
    try:
        catalogue = load_catalogue(materials_path)
    except FileNotFoundError:
        sys.exit(f"catalogue file not found: {materials_path}")

    sources_path = PROJECT_ROOT / "catalogue" / "sources.yaml"
    try:
        sources_text = sources_path.read_text()
    except FileNotFoundError:
        sys.exit(f"sources file not found: {sources_path}")
    try:
        sources = yaml.safe_load(sources_text) or {}
    except yaml.YAMLError as exc:
        sys.exit(f"sources file {sources_path} is not valid YAML: {exc}")

    manual = load_manual_prices(Path(args.manual))

    try:
        book = merge_prices(catalogue, fetch_prices(sources), manual, date.today().isoformat())
    except HarvestError as exc:
        sys.exit(f"error: {exc}")

    out_dir = Path(args.out)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        sys.exit(f"could not create output directory {out_dir}: {exc}")

    out_path = out_dir / f"{book['captured']}.json"

    try:
        content = json.dumps(book, indent=2) + "\n"
    except (TypeError, ValueError) as exc:
        sys.exit(f"could not serialise price book: {exc}")

    # Write to a temp file in the same directory, then atomically rename it
    # into place. This script is re-run repeatedly on the same day while
    # hand-entering prices — a crash or interrupt mid-write must never leave
    # a truncated JSON file at the exact path the engine reads from, and
    # must never destroy an already-good price book that was there before.
    # os.replace() is only atomic within a single filesystem, hence "same
    # directory".
    tmp_fd, tmp_name = tempfile.mkstemp(
        dir=out_dir, prefix=f".{book['captured']}.json.", suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            f.write(content)
        os.replace(tmp_name, out_path)
    except OSError as exc:
        sys.exit(f"could not write price book to {out_path}: {exc}")
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)

    print(f"wrote {out_path} — {len(book['prices'])} priced, {len(book['unpriced'])} unpriced")
    for sku_id in book["unpriced"]:
        print(f"  UNPRICED: {sku_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
