import pytest

from app.models import CustomField, GalleryImage, Product, ProductAttribute, Variation
from app.ui.product_form_simple import SimpleProductForm
from app.ui.product_form_variable import VariableProductForm


@pytest.fixture
def simple_form(qtbot):
    w = SimpleProductForm()
    qtbot.addWidget(w)
    return w


@pytest.fixture
def variable_form(qtbot):
    w = VariableProductForm()
    qtbot.addWidget(w)
    return w


def test_simple_form_round_trip(simple_form):
    product = Product(
        sku="MUG-001", product_type="simple", name="Ceramic Mug",
        description="A mug.", short_description="Short.",
        categories="Home > Kitchen", tags="Bestseller|Gift",
        price="12.50", sale_price="9.99", manage_stock=True, stock_qty="10",
        custom_fields=[CustomField(name="material_origin", value="Portugal")],
        attributes=[ProductAttribute(name="Material", values=["Ceramic", "Stoneware"])],
    )
    simple_form.load_product(product)

    result = simple_form._build_product()
    assert result.sku == "MUG-001"
    assert result.name == "Ceramic Mug"
    assert result.price == "12.50"
    assert result.sale_price == "9.99"
    assert result.manage_stock is True
    assert result.stock_qty == "10"
    assert result.categories == "Home > Kitchen"
    assert result.tags == "Bestseller|Gift"
    assert result.custom_fields[0].name == "material_origin"
    assert result.attributes[0].values == ["Ceramic", "Stoneware"]


def test_simple_form_save_emits_signal_when_valid(simple_form, qtbot):
    simple_form.sku_input.setText("X-001")
    simple_form.name_input.setText("Test Product")
    simple_form.price_input.setText("10")

    with qtbot.waitSignal(simple_form.saved, timeout=1000) as blocker:
        simple_form._on_save_clicked()

    saved_product = blocker.args[0]
    assert saved_product.sku == "X-001"


def test_simple_form_save_blocked_when_invalid(simple_form, qtbot):
    # No SKU, no name, no price -- should show errors and NOT emit saved.
    signal_received = []
    simple_form.saved.connect(lambda p: signal_received.append(p))

    simple_form._on_save_clicked()

    assert signal_received == []
    assert not simple_form.error_label.isHidden()


def test_simple_form_clear_resets_fields(simple_form):
    product = Product(sku="X", product_type="simple", name="X", price="5")
    simple_form.load_product(product)
    simple_form.clear()

    result = simple_form._build_product()
    assert result.sku == ""
    assert result.name == ""


def test_variable_form_round_trip(variable_form):
    product = Product(
        sku="TSHIRT-001", product_type="variable", name="Classic Tee",
        categories="Clothing", tags="Sale",
        attributes=[
            ProductAttribute(name="Color", values=["Red", "Blue"]),
            ProductAttribute(name="Size", values=["S", "M"]),
        ],
        variations=[
            Variation(sku="TSHIRT-001-RED-S", price="19.99", attribute_values={"Color": "Red", "Size": "S"}),
            Variation(sku="TSHIRT-001-BLUE-M", price="21.99", attribute_values={"Color": "Blue", "Size": "M"}),
        ],
    )
    variable_form.load_product(product)

    result = variable_form._build_product()
    assert result.sku == "TSHIRT-001"
    assert result.product_type == "variable"
    assert len(result.variations) == 2
    assert result.variations[0].sku == "TSHIRT-001-RED-S"
    assert result.variations[0].price == "19.99"
    assert {a.name for a in result.attributes} == {"Color", "Size"}


def test_variable_form_generate_variations_end_to_end(variable_form):
    variable_form.sku_input.setText("TSHIRT-001")
    variable_form.name_input.setText("Tee")
    variable_form.attribute_editor.add_row("Color", ["Red", "Blue"])

    variable_form.variation_table.generate_from_attributes(variable_form.attribute_editor.get_attributes())

    result = variable_form._build_product()
    assert len(result.variations) == 2
    skus = {v.sku for v in result.variations}
    assert skus == {"TSHIRT-001-RED", "TSHIRT-001-BLUE"}


def test_variable_form_save_blocked_without_variations(variable_form, qtbot):
    variable_form.sku_input.setText("TSHIRT-001")
    variable_form.name_input.setText("Tee")
    # No variations generated.

    signal_received = []
    variable_form.saved.connect(lambda p: signal_received.append(p))
    variable_form._on_save_clicked()

    assert signal_received == []
    assert "variation" in variable_form.error_label.text().lower()


def test_gallery_images_round_trip(simple_form):
    product = Product(
        sku="X", product_type="simple", name="X", price="1",
        gallery=[
            GalleryImage(path=None, alt="alt1", image_ref="https://example.com/1.jpg"),
            GalleryImage(path=None, alt="alt2", image_ref="https://example.com/2.jpg"),
        ],
    )
    simple_form.load_product(product)
    result = simple_form._build_product()
    assert len(result.gallery) == 2
    assert result.gallery[0].image_ref == "https://example.com/1.jpg"
    assert result.gallery[1].alt == "alt2"
