from pathlib import Path

from engine.catalogue import Catalogue, load_catalogue
from engine.clientconfig import ClientConfig, load_client
from engine.errors import RecipeError
from engine.models import QuoteResult
from engine.prices import PriceBook, latest_price_book
from engine.pricing import cost_tasks
from engine.quantify import build_namespace, quantify, resolve_parameters
from engine.recipes import Recipe, load_recipe
from engine.totals import total_quote

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_setup(
    recipe_id: str,
    client_slug: str,
    root: Path | None = None,
) -> tuple[Recipe, ClientConfig, PriceBook, Catalogue]:
    """Load everything a quote needs from disk, with errors that name the file.

    A recipe id or client slug that has no matching file/directory on disk raises
    RecipeError naming what was looked for, rather than letting a bare
    FileNotFoundError escape with a raw path traceback.
    """
    root = Path(root) if root is not None else PROJECT_ROOT

    catalogue_path = root / "catalogue" / "materials.yaml"
    try:
        catalogue = load_catalogue(catalogue_path)
    except FileNotFoundError as exc:
        raise RecipeError(
            f"catalogue not found: {exc.filename or catalogue_path}"
        ) from None

    recipe_path = root / "recipes" / f"{recipe_id}.yaml"
    try:
        recipe = load_recipe(recipe_path, catalogue)
    except FileNotFoundError as exc:
        raise RecipeError(
            f"no recipe {recipe_id!r}: expected a file at "
            f"{exc.filename or recipe_path}"
        ) from None

    client_dir = root / "clients" / client_slug
    try:
        client = load_client(client_dir)
    except FileNotFoundError as exc:
        raise RecipeError(
            f"no client {client_slug!r}: expected a file at "
            f"{exc.filename or client_dir}"
        ) from None

    book = latest_price_book(root / "data" / "pricebook")

    return recipe, client, book, catalogue


def build_quote(
    recipe_id: str,
    parameters: dict,
    client_slug: str,
    root: Path | None = None,
) -> QuoteResult:
    """Load everything, validate, quantify, cost, total. The only public entry point."""
    recipe, client, book, catalogue = load_setup(recipe_id, client_slug, root)

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
