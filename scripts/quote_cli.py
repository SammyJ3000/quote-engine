import argparse
import sys

from engine.errors import QuoteError
from engine.models import QuoteResult
from engine.quote import build_quote, load_setup
from engine.validate import material_variants, validate_setup


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


NAME_WIDTH = 34


def _fit(text: str, width: int) -> str:
    """Pad or trim a name to a fixed column so the money below it stays aligned."""
    if len(text) <= width:
        return text.ljust(width)
    return text[: width - 1] + "…"


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
        "  ----------------------------",
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
                # m.units is the purchasable quantity in m.unit (e.g. bags of
                # adhesive); m.raw_qty is in a different unit (e.g. m² of
                # tiling coverage) whenever the SKU is priced by coverage.
                # Only m.units is labelled with m.unit here — never pair
                # raw_qty with m.unit, that would misrepresent the quantity.
                # The human name leads: this screen is read by staff and by
                # customers, and 'Ceramic wall tile, mid range' is what they buy.
                # The SKU id follows it for anyone reconciling against the book.
                lines.append(
                    f"      {_fit(m.name, NAME_WIDTH)}  {m.sku_id:<23} "
                    f"{m.units:>7.2f} {m.unit:<6} "
                    f"@ £{m.unit_net:>8,.2f} (list £{m.list_price:,.2f} "
                    f"less {m.discount:.0%}) = £{m.cost:,.2f}"
                )

    return "\n".join(lines)


def format_check(recipe, client, book, catalogue, problems: list[str]) -> str:
    """The pre-demo smoke test's report: a clear pass, or every gap found."""
    header = f"Setup check: recipe {recipe.id!r} + client {client.slug!r}"
    if problems:
        return "\n".join(
            [header, "", f"{len(problems)} problem(s) to fix before quoting:"]
            + [f"  - {problem}" for problem in problems]
        )

    trades = sorted({task.trade for task in recipe.tasks})
    skus = sorted({
        sku_id
        for task in recipe.tasks
        for material in task.materials
        for sku_id in material_variants(material, catalogue)
    })
    return "\n".join([
        header,
        f"Prices captured {book.captured}",
        "",
        f"  OK — {len(recipe.tasks)} tasks, {len(trades)} trades all have a day rate, "
        f"{len(skus)} SKUs all priced.",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Produce a quote from a recipe.")
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--client", default="demo-nw")
    parser.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--detail", action="store_true", help="show the internal itemised view")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate this recipe against this client's setup and exit, without quoting",
    )
    args = parser.parse_args(argv)

    if args.check:
        try:
            recipe, client, book, catalogue = load_setup(args.recipe, args.client)
            problems = validate_setup(recipe, client, book, catalogue)
        except QuoteError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(format_check(recipe, client, book, catalogue, problems))
        return 1 if problems else 0

    try:
        result = build_quote(args.recipe, parse_params(args.param), args.client)
    except QuoteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(format_quote(result, detail=args.detail))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
