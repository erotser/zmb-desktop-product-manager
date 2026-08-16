import pytest

from app.models import ProductAttribute, Variation
from app.ui.variation_table import VariationTableWidget


@pytest.fixture
def widget(qtbot):
    w = VariationTableWidget(confirm_fn=lambda msg: True)  # auto-confirm by default
    w.set_parent_sku("TSHIRT-001")
    qtbot.addWidget(w)
    return w


def test_generate_creates_cartesian_product(widget):
    attrs = [
        ProductAttribute(name="Color", values=["Red", "Blue"]),
        ProductAttribute(name="Size", values=["S", "M"]),
    ]
    widget.generate_from_attributes(attrs)

    variations = widget.get_variations()
    assert len(variations) == 4
    combos = {(v.attribute_values["Color"], v.attribute_values["Size"]) for v in variations}
    assert combos == {("Red", "S"), ("Red", "M"), ("Blue", "S"), ("Blue", "M")}


def test_generate_suggests_readable_skus(widget):
    attrs = [ProductAttribute(name="Color", values=["Red"]), ProductAttribute(name="Size", values=["S"])]
    widget.generate_from_attributes(attrs)
    assert widget.get_variations()[0].sku == "TSHIRT-001-RED-S"


def test_regenerate_preserves_existing_variation_data(widget):
    attrs = [ProductAttribute(name="Color", values=["Red", "Blue"])]
    widget.generate_from_attributes(attrs)

    # Simulate the user editing the Red variation's price and SKU.
    red_variation = next(v for v in widget.get_variations() if v.attribute_values["Color"] == "Red")
    red_variation.price = "25.00"
    red_variation.sku = "CUSTOM-RED-SKU"

    # Regenerate with an extra color added -- Red's data must survive untouched.
    attrs2 = [ProductAttribute(name="Color", values=["Red", "Blue", "Green"])]
    widget.generate_from_attributes(attrs2)

    variations = widget.get_variations()
    assert len(variations) == 3
    red_after = next(v for v in variations if v.attribute_values["Color"] == "Red")
    assert red_after.price == "25.00"
    assert red_after.sku == "CUSTOM-RED-SKU"

    green_after = next(v for v in variations if v.attribute_values["Color"] == "Green")
    assert green_after.price == ""  # brand new row, no data yet


def test_regenerate_removes_stale_combo_after_confirmation(widget):
    attrs = [ProductAttribute(name="Color", values=["Red", "Blue"])]
    widget.generate_from_attributes(attrs)
    assert len(widget.get_variations()) == 2

    # Removing "Blue" from the palette should drop that variation (confirm_fn=True by default fixture).
    attrs2 = [ProductAttribute(name="Color", values=["Red"])]
    widget.generate_from_attributes(attrs2)

    variations = widget.get_variations()
    assert len(variations) == 1
    assert variations[0].attribute_values["Color"] == "Red"


def test_regenerate_cancelled_leaves_variations_untouched(qtbot):
    widget = VariationTableWidget(confirm_fn=lambda msg: False)  # user clicks "No"
    widget.set_parent_sku("TSHIRT-001")
    qtbot.addWidget(widget)

    attrs = [ProductAttribute(name="Color", values=["Red", "Blue"])]
    widget.generate_from_attributes(attrs)
    assert len(widget.get_variations()) == 2

    attrs2 = [ProductAttribute(name="Color", values=["Red"])]
    widget.generate_from_attributes(attrs2)  # would remove Blue, but confirm_fn declines

    # Nothing changed since the removal wasn't confirmed.
    variations = widget.get_variations()
    assert len(variations) == 2


def test_generate_with_no_existing_variations_and_no_confirmation_needed(widget):
    """Growing the palette (no removals) shouldn't need confirmation at all."""
    attrs = [ProductAttribute(name="Color", values=["Red"])]
    widget.generate_from_attributes(attrs)

    calls = []
    widget._confirm_fn = lambda msg: calls.append(msg) or True

    attrs2 = [ProductAttribute(name="Color", values=["Red", "Blue"])]
    widget.generate_from_attributes(attrs2)

    assert calls == []  # confirm_fn should never have been called
    assert len(widget.get_variations()) == 2


def test_set_and_get_variations_round_trip(widget):
    variations = [
        Variation(sku="A-1", price="10", attribute_values={"Color": "Red"}),
        Variation(sku="A-2", price="12", attribute_values={"Color": "Blue"}),
    ]
    widget.set_variations(variations, ["Color"])
    result = widget.get_variations()
    assert [v.sku for v in result] == ["A-1", "A-2"]


def test_editing_sku_cell_updates_underlying_variation(widget, qtbot):
    variations = [Variation(sku="OLD-SKU", price="10", attribute_values={"Color": "Red"})]
    widget.set_variations(variations, ["Color"])

    # Column order is [Color, sku, price, sale_price, stock_qty, manage_stock, image, description, remove]
    sku_col_index = 1
    item = widget.table.item(0, sku_col_index)
    item.setText("NEW-SKU")

    assert widget.get_variations()[0].sku == "NEW-SKU"


def test_removing_row_via_button(widget):
    variations = [
        Variation(sku="A-1", price="10", attribute_values={"Color": "Red"}),
        Variation(sku="A-2", price="12", attribute_values={"Color": "Blue"}),
    ]
    widget.set_variations(variations, ["Color"])
    widget._on_remove_row_clicked(0)
    result = widget.get_variations()
    assert len(result) == 1
    assert result[0].sku == "A-2"
