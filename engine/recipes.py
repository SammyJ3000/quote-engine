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


def _require(mapping: dict, key: str, where: str):
    try:
        return mapping[key]
    except (KeyError, TypeError):
        raise RecipeError(f"{where} missing required key {key!r}") from None


def _require_list(mapping: dict, key: str, where: str, *, allow_empty: bool = True) -> list:
    value = mapping.get(key)
    if value is None:
        value = []
    if not isinstance(value, list):
        raise RecipeError(f"{where} key {key!r} must be a list, got {type(value).__name__}")
    if not value and not allow_empty:
        raise RecipeError(f"{where} key {key!r} must not be empty")
    return value


def _require_float(mapping: dict, key: str, where: str, *, default: float = 0.0) -> float:
    value = mapping.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        raise RecipeError(f"{where} key {key!r} must be a number, got {value!r}") from None


def _require_bool(mapping: dict, key: str, where: str, *, default: bool = False) -> bool:
    value = mapping.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    # A quoted "true"/"false" is an authoring mistake, not a value to guess at.
    raise RecipeError(f"{where} key {key!r} must be a boolean, got {value!r}") from None


def _require_mapping(mapping: dict, key: str, where: str) -> dict:
    value = mapping.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RecipeError(f"{where} key {key!r} must be a mapping, got {type(value).__name__}")
    return value


def _parse_material(raw: dict, where: str) -> MaterialSpec:
    return MaterialSpec(
        sku=_require(raw, "sku", where),
        qty=_require(raw, "qty", where),
        waste=_require_float(raw, "waste", where),
        by_coverage=_require_bool(raw, "by_coverage", where),
        tier_from=raw.get("tier"),
    )


def load_recipe(path: str | Path, catalogue: Catalogue) -> Recipe:
    raw = yaml.safe_load(Path(path).read_text())

    if not isinstance(raw, dict):
        raise RecipeError(f"recipe {str(path)!r} is empty or not a mapping")

    for key in ("id", "label"):
        if raw.get(key) is None:
            raise RecipeError(f"recipe {str(path)!r} missing required key {key!r}")

    recipe_id = raw["id"]
    where_recipe = f"recipe {recipe_id!r}"

    parameters = []
    for i, p in enumerate(_require_list(raw, "parameters", where_recipe), start=1):
        where = f"recipe {recipe_id!r} parameter {i}"
        parameters.append(
            Parameter(
                id=_require(p, "id", where),
                type=_require(p, "type", where),
                values=p.get("values"),
                min=p.get("min"),
                max=p.get("max"),
                default=p.get("default"),
            )
        )
    parameters = tuple(parameters)

    tasks: list[TaskSpec] = []
    seen: set[str] = set()
    for i, t in enumerate(_require_list(raw, "tasks", where_recipe, allow_empty=False), start=1):
        index_where = f"recipe {recipe_id!r} task {i}"
        task_id = _require(t, "id", index_where)
        if task_id in seen:
            raise RecipeError(f"recipe {recipe_id!r} has duplicate task id {task_id!r}")
        seen.add(task_id)
        task_where = f"recipe {recipe_id!r} task {task_id!r}"
        materials = tuple(
            _parse_material(m, f"{task_where} material {j}")
            for j, m in enumerate(_require_list(t, "materials", task_where), start=1)
        )
        tasks.append(
            TaskSpec(
                id=task_id,
                label=_require(t, "label", task_where),
                trade=_require(t, "trade", task_where),
                days=_require(t, "days", task_where),
                when=t.get("when"),
                materials=materials,
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
        constants=_require_mapping(raw, "constants", where_recipe),
        derived=_require_mapping(raw, "derived", where_recipe),
    )
