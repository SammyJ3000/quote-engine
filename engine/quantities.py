import ast
import math

from simpleeval import InvalidExpression, SimpleEval

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
