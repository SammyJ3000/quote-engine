from decimal import Decimal

import pytest

from engine.clientconfig import load_client
from engine.errors import RecipeError


@pytest.fixture
def client_dir(tmp_path):
    d = tmp_path / "demo-nw"
    d.mkdir()
    (d / "labour.yaml").write_text("plumber: 300\ntiler: 260\nlabourer: 160\n")
    (d / "discounts.yaml").write_text("default: 0.15\n")
    (d / "commercial.yaml").write_text(
        "overhead_margin: 0.22\ncontingency: 0.05\nquote_band: 0.08\n"
        "vat_rate: 0.20\ndisplay_rounding: 50\n"
    )
    return d


def test_day_rates_are_decimal(client_dir):
    assert load_client(client_dir).day_rate("plumber") == Decimal("300")


def test_commercial_settings_load(client_dir):
    client = load_client(client_dir)
    assert client.overhead_margin == Decimal("0.22")
    assert client.contingency == Decimal("0.05")
    assert client.quote_band == Decimal("0.08")
    assert client.vat_rate == Decimal("0.20")
    assert client.display_rounding == 50


def test_slug_comes_from_directory_name(client_dir):
    assert load_client(client_dir).slug == "demo-nw"


def test_unknown_trade_raises_and_names_it(client_dir):
    with pytest.raises(RecipeError) as exc:
        load_client(client_dir).day_rate("stonemason")
    assert "stonemason" in str(exc.value)


def test_zero_display_rounding_raises_and_names_client(client_dir):
    (client_dir / "commercial.yaml").write_text(
        "overhead_margin: 0.22\ncontingency: 0.05\nquote_band: 0.08\n"
        "vat_rate: 0.20\ndisplay_rounding: 0\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_client(client_dir)
    assert "demo-nw" in str(exc.value)


def test_negative_display_rounding_raises(client_dir):
    (client_dir / "commercial.yaml").write_text(
        "overhead_margin: 0.22\ncontingency: 0.05\nquote_band: 0.08\n"
        "vat_rate: 0.20\ndisplay_rounding: -10\n"
    )
    with pytest.raises(RecipeError):
        load_client(client_dir)


def test_quoted_string_display_rounding_is_coerced_to_int(client_dir):
    (client_dir / "commercial.yaml").write_text(
        "overhead_margin: 0.22\ncontingency: 0.05\nquote_band: 0.08\n"
        'vat_rate: 0.20\ndisplay_rounding: "50"\n'
    )
    client = load_client(client_dir)
    assert client.display_rounding == 50
    assert isinstance(client.display_rounding, int)


def test_float_display_rounding_is_coerced_to_int(client_dir):
    (client_dir / "commercial.yaml").write_text(
        "overhead_margin: 0.22\ncontingency: 0.05\nquote_band: 0.08\n"
        "vat_rate: 0.20\ndisplay_rounding: 50.0\n"
    )
    client = load_client(client_dir)
    assert client.display_rounding == 50
    assert isinstance(client.display_rounding, int)


def test_boolean_display_rounding_raises(client_dir):
    (client_dir / "commercial.yaml").write_text(
        "overhead_margin: 0.22\ncontingency: 0.05\nquote_band: 0.08\n"
        "vat_rate: 0.20\ndisplay_rounding: true\n"
    )
    with pytest.raises(RecipeError) as exc:
        load_client(client_dir)
    assert "demo-nw" in str(exc.value)


def test_non_numeric_string_display_rounding_raises(client_dir):
    (client_dir / "commercial.yaml").write_text(
        "overhead_margin: 0.22\ncontingency: 0.05\nquote_band: 0.08\n"
        'vat_rate: 0.20\ndisplay_rounding: "fifty"\n'
    )
    with pytest.raises(RecipeError) as exc:
        load_client(client_dir)
    assert "demo-nw" in str(exc.value)


def test_display_rounding_defaults_to_fifty_when_the_key_is_omitted(client_dir):
    (client_dir / "commercial.yaml").write_text(
        "overhead_margin: 0.22\ncontingency: 0.05\nquote_band: 0.08\nvat_rate: 0.20\n"
    )
    client = load_client(client_dir)
    assert client.display_rounding == 50
    assert isinstance(client.display_rounding, int)


def test_commercial_rates_default_when_omitted(client_dir):
    (client_dir / "commercial.yaml").write_text("display_rounding: 50\n")
    client = load_client(client_dir)
    assert client.overhead_margin == Decimal("0.22")
    assert client.vat_rate == Decimal("0.20")


# --- a mistyped skin must explain itself, not traceback ---------------------

def test_a_day_rate_written_with_a_pound_sign_names_the_trade(client_dir):
    (client_dir / "labour.yaml").write_text('plumber: "£285"\ntiler: 260\n')
    with pytest.raises(RecipeError) as exc:
        load_client(client_dir)
    assert "plumber" in str(exc.value) and "labour.yaml" in str(exc.value)


@pytest.mark.parametrize("rate", ["0", "-40", "not a rate"])
def test_an_impossible_day_rate_names_the_trade(client_dir, rate):
    (client_dir / "labour.yaml").write_text(f"plumber: {rate}\n")
    with pytest.raises(RecipeError) as exc:
        load_client(client_dir)
    assert "plumber" in str(exc.value)


def test_overhead_margin_written_as_a_percentage_names_the_key(client_dir):
    (client_dir / "commercial.yaml").write_text("overhead_margin: 22%\n")
    with pytest.raises(RecipeError) as exc:
        load_client(client_dir)
    assert "overhead_margin" in str(exc.value) and "commercial.yaml" in str(exc.value)


@pytest.mark.parametrize("key", ["overhead_margin", "contingency", "quote_band", "vat_rate"])
def test_a_commercial_rate_of_twenty_meaning_twenty_percent_raises(client_dir, key):
    (client_dir / "commercial.yaml").write_text(f"{key}: 20\n")
    with pytest.raises(RecipeError) as exc:
        load_client(client_dir)
    assert key in str(exc.value)


def test_labour_yaml_that_is_not_a_mapping_names_the_file(client_dir):
    (client_dir / "labour.yaml").write_text("- plumber\n- tiler\n")
    with pytest.raises(RecipeError) as exc:
        load_client(client_dir)
    assert "labour.yaml" in str(exc.value)
