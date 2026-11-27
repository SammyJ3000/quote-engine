import pytest

from engine.errors import FormulaError
from engine.quantities import evaluate


def test_arithmetic():
    assert evaluate("2 * (3 + 4)", {}) == 14


def test_reads_names_from_namespace():
    assert evaluate("length_m * width_m", {"length_m": 2.4, "width_m": 1.8}) == pytest.approx(4.32)


def test_indexes_a_constant_lookup_table():
    ns = {"tiling_factor": {"full-height": 1.0, "half-height": 0.5}, "tiling_extent": "half-height"}
    assert evaluate("tiling_factor[tiling_extent]", ns) == 0.5


def test_ceil_is_available():
    assert evaluate("ceil(4.2 / 5)", {}) == 1


def test_rejects_attribute_access():
    with pytest.raises(FormulaError):
        evaluate("x.__class__", {"x": 1})


def test_rejects_unknown_names():
    with pytest.raises(FormulaError):
        evaluate("__import__('os')", {})


def test_rejects_unknown_key_with_a_useful_message():
    ns = {"t": {"a": 1.0}, "k": "b"}
    with pytest.raises(FormulaError) as exc:
        evaluate("t[k]", ns)
    assert "b" in str(exc.value)
