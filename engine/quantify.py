import math
from decimal import Decimal, InvalidOperation

from engine.catalogue import Catalogue
from engine.errors import ParameterError, RecipeError
from engine.models import ResolvedMaterial, ResolvedTask, Sku
from engine.money import to_decimal
from engine.quantities import evaluate
from engine.recipes import MaterialSpec, Parameter, Recipe

PARAMETER_TYPES = ("number", "enum", "boolean")


def _declared_parameters(recipe: Recipe) -> dict[str, Parameter]:
    """Index the recipe's parameters, refusing declarations we cannot validate against."""
    declared: dict[str, Parameter] = {}
    for param in recipe.parameters:
        if param.id in declared:
            raise RecipeError(
                f"recipe {recipe.id!r} declares parameter {param.id!r} more than once"
            )
        if param.type not in PARAMETER_TYPES:
            raise RecipeError(
                f"recipe {recipe.id!r} parameter {param.id!r} has unknown type {param.type!r}; "
                f"expected one of {list(PARAMETER_TYPES)}"
            )
        declared[param.id] = param
    return declared


def _bound(recipe_id: str, param: Parameter, attr: str) -> float | None:
    raw = getattr(param, attr)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise RecipeError(
            f"recipe {recipe_id!r} parameter {param.id!r} {attr} must be a number, got {raw!r}"
        )
    return float(raw)


def _as_number(recipe_id: str, param: Parameter, value) -> float:
    # A boolean is an int in Python. Silently reading `true` as 1.0 would be a trap.
    if isinstance(value, bool):
        raise ParameterError(f"parameter {param.id!r} must be a number, got boolean {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ParameterError(f"parameter {param.id!r} must be a number, got {value!r}") from None
    if not math.isfinite(number):
        # NaN compares false against every bound, so it would slip past min/max unnoticed.
        raise ParameterError(f"parameter {param.id!r} must be a finite number, got {value!r}")

    minimum = _bound(recipe_id, param, "min")
    maximum = _bound(recipe_id, param, "max")
    if minimum is not None and number < minimum:
        raise ParameterError(f"parameter {param.id!r} value {number} below minimum {minimum}")
    if maximum is not None and number > maximum:
        raise ParameterError(f"parameter {param.id!r} value {number} above maximum {maximum}")
    return number


def _as_enum(recipe_id: str, param: Parameter, value):
    if not isinstance(param.values, list) or not param.values:
        raise RecipeError(
            f"recipe {recipe_id!r} parameter {param.id!r} is an enum but declares no values"
        )
    if value not in param.values:
        raise ParameterError(
            f"parameter {param.id!r} value {value!r} not one of {param.values}"
        )
    return value


def _as_boolean(param: Parameter, value) -> bool:
    if not isinstance(value, bool):
        # `bool("false")` is True. Guessing here would quietly switch tasks on.
        raise ParameterError(f"parameter {param.id!r} must be true or false, got {value!r}")
    return value


def _coerce(recipe_id: str, param: Parameter, value):
    if param.type == "number":
        return _as_number(recipe_id, param, value)
    if param.type == "enum":
        return _as_enum(recipe_id, param, value)
    return _as_boolean(param, value)


def resolve_parameters(recipe: Recipe, supplied: dict) -> dict:
    """Validate supplied parameters against the recipe and fill in defaults."""
    if not isinstance(supplied, dict):
        raise ParameterError(
            f"parameters for recipe {recipe.id!r} must be a mapping, "
            f"got {type(supplied).__name__}"
        )

    declared = _declared_parameters(recipe)

    unknown = set(supplied) - set(declared)
    if unknown:
        raise ParameterError(
            f"unknown parameters for recipe {recipe.id!r}: {sorted(unknown, key=repr)}"
        )

    resolved: dict = {}
    for param_id, param in declared.items():
        if param_id in supplied:
            value, from_default = supplied[param_id], False
        elif not param.required:
            value, from_default = param.default, True
        else:
            raise ParameterError(
                f"missing required parameter {param_id!r} for recipe {recipe.id!r}"
            )

        try:
            resolved[param_id] = _coerce(recipe.id, param, value)
        except ParameterError as exc:
            if from_default:
                # The operator supplied nothing wrong; the recipe's own default is bad.
                raise RecipeError(
                    f"recipe {recipe.id!r} default for parameter {param_id!r} is invalid: {exc}"
                ) from None
            raise

    return resolved


def build_namespace(recipe: Recipe, params: dict) -> dict:
    """Constants, then parameters, then derived values computed in declaration order."""
    namespace = dict(recipe.constants)

    for name in params:
        if name in namespace:
            raise RecipeError(
                f"recipe {recipe.id!r} parameter {name!r} shadows a constant of the same name"
            )
    namespace.update(params)

    for name, expr in recipe.derived.items():
        if not isinstance(name, str):
            raise RecipeError(f"recipe {recipe.id!r} derived name {name!r} must be text")
        if name in namespace:
            raise RecipeError(
                f"recipe {recipe.id!r} derived value {name!r} shadows a constant or parameter "
                f"of the same name"
            )
        namespace[name] = evaluate(expr, namespace)

    return namespace


# Expressions are evaluated in float, so 3.6 + 16.8 - 8.4 lands on
# 12.000000000000002 rather than 12. Left alone, math.ceil in _units_for turns
# that last bit into a whole extra tin of paint or sheet of board, and a value
# that should be 0 can land on -1e-16 and fail the non-negative check below.
# Nine decimal places is far finer than any real quantity and coarser than the
# noise, so quantize once here, at the one boundary where floats become Decimal.
QUANTITY_PLACES = 9


def _quantity(value, where: str) -> Decimal:
    """Turn an evaluated expression into a non-negative Decimal quantity, or explain why not."""
    if value is None or isinstance(value, (bool, str)):
        raise RecipeError(f"{where} evaluated to {value!r}, which is not a quantity")
    try:
        quantity = to_decimal(round(value, QUANTITY_PLACES))
    except (ArithmeticError, InvalidOperation, TypeError, ValueError):
        raise RecipeError(f"{where} evaluated to {value!r}, which is not a quantity") from None
    if not quantity.is_finite():
        raise RecipeError(f"{where} evaluated to {value!r}, which is not a finite quantity")
    if quantity < 0:
        raise RecipeError(f"{where} evaluated to {quantity}, but that cannot be negative")
    return quantity


def _units_for(spec: MaterialSpec, sku: Sku, raw_qty: Decimal, where: str) -> Decimal:
    waste = to_decimal(spec.waste)
    if not waste.is_finite() or waste < 0:
        raise RecipeError(f"{where} has invalid waste {spec.waste!r}; expected zero or more")

    with_waste = raw_qty * (Decimal("1") + waste)

    if spec.by_coverage:
        coverage = sku.coverage_per_unit
        if coverage is None:
            raise RecipeError(
                f"{where} uses by_coverage but SKU {sku.id!r} has no coverage defined"
            )
        if coverage <= 0:
            raise RecipeError(
                f"{where} uses by_coverage but SKU {sku.id!r} covers {coverage} per unit"
            )
        return Decimal(math.ceil(with_waste / coverage))

    if sku.discrete:
        return Decimal(math.ceil(with_waste))

    return with_waste


def _resolve_sku(spec: MaterialSpec, namespace: dict, catalogue: Catalogue, where: str) -> Sku:
    if spec.tier_from is None:
        return catalogue.resolve_tier(spec.sku, None)

    if spec.tier_from not in namespace:
        raise RecipeError(
            f"{where} takes its tier from {spec.tier_from!r}, which is not a parameter, "
            f"constant or derived value of this recipe"
        )
    tier = namespace[spec.tier_from]
    if not isinstance(tier, str):
        raise RecipeError(
            f"{where} takes its tier from {spec.tier_from!r}, which is {tier!r}, not a tier name"
        )
    return catalogue.resolve_tier(spec.sku, tier)


def quantify(recipe: Recipe, params: dict, catalogue: Catalogue) -> tuple[ResolvedTask, ...]:
    """Turn a recipe plus parameters into tasks with quantities. Touches no prices."""
    namespace = build_namespace(recipe, params)
    resolved: list[ResolvedTask] = []

    for task in recipe.tasks:
        task_where = f"recipe {recipe.id!r} task {task.id!r}"

        if task.when is not None:
            verdict = evaluate(task.when, namespace)
            if not isinstance(verdict, bool):
                raise RecipeError(
                    f"{task_where} condition {task.when!r} evaluated to {verdict!r}, "
                    f"not true or false"
                )
            if not verdict:
                continue

        materials: list[ResolvedMaterial] = []
        for i, spec in enumerate(task.materials, start=1):
            where = f"{task_where} material {i} ({spec.sku!r})"
            sku = _resolve_sku(spec, namespace, catalogue, where)
            raw_qty = _quantity(evaluate(spec.qty, namespace), f"{where} qty")
            materials.append(
                ResolvedMaterial(
                    sku=sku,
                    raw_qty=raw_qty,
                    units=_units_for(spec, sku, raw_qty, where),
                )
            )

        resolved.append(
            ResolvedTask(
                id=task.id,
                label=task.label,
                trade=task.trade,
                days=_quantity(evaluate(task.days, namespace), f"{task_where} days"),
                materials=tuple(materials),
            )
        )

    return tuple(resolved)
