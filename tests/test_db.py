import pytest

from app.db import Database
from app.models import CustomField, GalleryImage, Product, ProductAttribute, Variation


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    yield database
    database.close()


def test_save_and_reload_simple_product(db):
    p = Product(
        sku="MUG-001",
        product_type="simple",
        name="Ceramic Mug",
        description="A mug.",
        price="12.50",
        stock_qty="10",
        manage_stock=True,
        categories="Home > Kitchen",
        tags="Bestseller|Gift",
        custom_fields=[CustomField(name="material_origin", value="Portugal")],
        attributes=[ProductAttribute(name="Material", values=["Ceramic", "Stoneware"])],
    )
    saved = db.save_product(p)
    assert saved.id is not None

    reloaded = db.get_product_by_sku("MUG-001")
    assert reloaded.name == "Ceramic Mug"
    assert reloaded.price == "12.50"
    assert reloaded.manage_stock is True
    assert reloaded.custom_fields[0].name == "material_origin"
    assert reloaded.attributes[0].values == ["Ceramic", "Stoneware"]


def test_save_and_reload_variable_product(db):
    p = Product(
        sku="TSHIRT-001",
        product_type="variable",
        name="Classic Tee",
        attributes=[
            ProductAttribute(name="Color", values=["Red", "Blue"]),
            ProductAttribute(name="Size", values=["S", "M"]),
        ],
        variations=[
            Variation(sku="TSHIRT-001-RED-S", price="19.99", attribute_values={"Color": "Red", "Size": "S"}),
            Variation(sku="TSHIRT-001-RED-M", price="19.99", attribute_values={"Color": "Red", "Size": "M"}),
        ],
    )
    db.save_product(p)

    reloaded = db.get_product_by_sku("TSHIRT-001")
    assert len(reloaded.variations) == 2
    assert reloaded.variations[0].attribute_values == {"Color": "Red", "Size": "S"}


def test_update_existing_product_replaces_children(db):
    p = Product(sku="MUG-001", product_type="simple", name="Mug", price="10",
                custom_fields=[CustomField(name="a", value="1")])
    db.save_product(p)

    p2 = Product(sku="MUG-001", product_type="simple", name="Mug v2", price="11",
                 custom_fields=[CustomField(name="b", value="2")])
    db.save_product(p2)

    reloaded = db.get_product_by_sku("MUG-001")
    assert reloaded.name == "Mug v2"
    assert len(reloaded.custom_fields) == 1
    assert reloaded.custom_fields[0].name == "b"


def test_validate_rejects_missing_sku():
    p = Product(sku="", product_type="simple", name="X", price="1")
    errors = p.validate()
    assert any("SKU" in e for e in errors)


def test_validate_rejects_negative_price():
    p = Product(sku="X", product_type="simple", name="X", price="-5")
    errors = p.validate()
    assert any("non-negative" in e for e in errors)


def test_validate_variable_requires_variations():
    p = Product(sku="X", product_type="variable", name="X")
    errors = p.validate()
    assert any("variation" in e.lower() for e in errors)


def test_validate_rejects_variation_sku_equal_to_parent():
    p = Product(sku="X", product_type="variable", name="X",
                variations=[Variation(sku="X", price="1")])
    errors = p.validate()
    assert any("must not be the same" in e for e in errors)


def test_save_rejects_invalid_product(db):
    p = Product(sku="", product_type="simple", name="X", price="1")
    with pytest.raises(ValueError):
        db.save_product(p)


def test_gallery_image_ref_persists(db):
    p = Product(
        sku="MUG-001", product_type="simple", name="Mug", price="10",
        gallery=[GalleryImage(path=None, alt="alt text", image_ref="https://example.com/mug.jpg")],
    )
    db.save_product(p)
    reloaded = db.get_product_by_sku("MUG-001")
    assert reloaded.gallery[0].image_ref == "https://example.com/mug.jpg"
    assert reloaded.gallery[0].path is None
