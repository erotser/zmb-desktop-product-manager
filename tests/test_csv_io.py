import csv as csv_module

import pytest

from app import csv_io
from app.models import CustomField, GalleryImage, Product, ProductAttribute, Variation


def read_csv_dicts(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv_module.DictReader(f))


def test_export_then_import_variable_product_round_trips(tmp_path):
    product = Product(
        sku="TSHIRT-001",
        product_type="variable",
        name="Classic Tee",
        description="A soft tee.",
        categories="Clothing > T-Shirts",
        tags="Bestseller|Cotton",
        attributes=[
            ProductAttribute(name="Color", values=["Red", "Blue"]),
            ProductAttribute(name="Size", values=["S", "M"]),
        ],
        variations=[
            Variation(sku="TSHIRT-001-RED-S", price="19.99", attribute_values={"Color": "Red", "Size": "S"}),
            Variation(sku="TSHIRT-001-RED-M", price="19.99", attribute_values={"Color": "Red", "Size": "M"}),
            Variation(sku="TSHIRT-001-BLUE-S", price="21.99", sale_price="18.99",
                      attribute_values={"Color": "Blue", "Size": "S"}),
        ],
        custom_fields=[CustomField(name="material_origin", value="Portugal")],
    )

    csv_path = tmp_path / "export.csv"
    csv_io.export_to_csv([product], csv_path)

    rows = read_csv_dicts(csv_path)
    assert len(rows) == 3
    assert rows[0]["parent_sku"] == "TSHIRT-001"
    assert rows[0]["product_type"] == "variable"
    assert rows[0]["attribute:Color"] == "Red"
    assert rows[0]["attribute:Size"] == "S"
    assert rows[0]["customf:material_origin"] == "Portugal"
    assert rows[2]["variation_sale_price"] == "18.99"

    imported, warnings = csv_io.import_from_csv(csv_path)
    assert warnings == []
    assert len(imported) == 1

    reimported = imported[0]
    assert reimported.sku == "TSHIRT-001"
    assert reimported.product_type == "variable"
    assert reimported.categories == "Clothing > T-Shirts"
    assert reimported.tags == "Bestseller|Cotton"
    assert len(reimported.variations) == 3
    assert reimported.custom_fields[0].name == "material_origin"
    assert reimported.custom_fields[0].value == "Portugal"

    attr_names = {a.name for a in reimported.attributes}
    assert attr_names == {"Color", "Size"}


def test_export_then_import_simple_product_round_trips(tmp_path):
    product = Product(
        sku="CANDLE-003",
        product_type="simple",
        name="Soy Candle",
        price="16.00",
        sale_price="13.50",
        stock_qty="40",
        manage_stock=True,
        attributes=[ProductAttribute(name="Scent", values=["Lavender", "Vanilla"])],
    )

    csv_path = tmp_path / "export.csv"
    csv_io.export_to_csv([product], csv_path)

    rows = read_csv_dicts(csv_path)
    assert len(rows) == 1
    assert rows[0]["product_type"] == "simple"
    assert rows[0]["attribute:Scent"] == "Lavender|Vanilla"
    assert rows[0]["variation_price"] == "16.0" or rows[0]["variation_price"] == "16.00"

    imported, warnings = csv_io.import_from_csv(csv_path)
    assert warnings == []
    reimported = imported[0]
    assert reimported.product_type == "simple"
    assert reimported.price in ("16.00", "16.0")
    assert reimported.sale_price in ("13.50", "13.5")
    assert reimported.manage_stock is True
    assert set(reimported.attributes[0].values) == {"Lavender", "Vanilla"}


def test_import_without_product_type_column_defaults_to_variable(tmp_path):
    """Backward compatibility: files created before simple-product support
    (no product_type column at all) must still import as variable."""
    csv_path = tmp_path / "old_format.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv_module.writer(f)
        writer.writerow(["parent_sku", "product_name", "variation_sku", "variation_price"])
        writer.writerow(["MUG-002", "Mug", "MUG-002-11OZ", "12.50"])

    imported, warnings = csv_io.import_from_csv(csv_path)
    assert warnings == []
    assert imported[0].product_type == "variable"
    assert imported[0].variations[0].sku == "MUG-002-11OZ"


def test_negative_price_rejected(tmp_path):
    csv_path = tmp_path / "bad.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv_module.writer(f)
        writer.writerow(["parent_sku", "product_type", "product_name", "variation_sku", "variation_price"])
        writer.writerow(["X-001", "simple", "Bad Product", "", "-5"])

    imported, warnings = csv_io.import_from_csv(csv_path)
    assert len(imported) == 0
    assert len(warnings) == 1
    assert "non-negative" in warnings[0]


def test_formula_injection_escape_and_reverse():
    dangerous_values = ["=cmd|'/c calc'!A1", "+1+1", "-5", "@SUM(A1)", "\tsneaky"]
    for value in dangerous_values:
        escaped = csv_io.sanitize_csv_cell(value)
        assert escaped.startswith("'")
        reversed_value = csv_io.strip_formula_escape(escaped)
        assert reversed_value == value


def test_formula_injection_round_trips_through_full_export_import(tmp_path):
    product = Product(
        sku="X-001", product_type="simple", name="X",
        description="- bullet point description",
        price="1.00",
        custom_fields=[CustomField(name="note", value="-5 degrees")],
    )
    csv_path = tmp_path / "export.csv"
    csv_io.export_to_csv([product], csv_path)

    # Confirm the raw file actually contains the escape marker.
    raw = csv_path.read_text(encoding="utf-8-sig")
    assert "'- bullet point description" in raw

    imported, warnings = csv_io.import_from_csv(csv_path)
    assert warnings == []
    reimported = imported[0]
    # Must NOT have a stray leading quote after round-tripping.
    assert reimported.description == "- bullet point description"
    assert reimported.custom_fields[0].value == "-5 degrees"


def test_legitimate_leading_quote_is_not_touched():
    value = "'Twas a good sale"  # genuine content that happens to start with a quote, not a trigger char after it
    assert csv_io.strip_formula_escape(value) == value


def test_image_filename_used_in_export_not_local_path(tmp_path):
    product = Product(
        sku="TSHIRT-001", product_type="simple", name="Tee", price="10",
        image_path="/local/original/photo.png",
    )
    csv_path = tmp_path / "export.csv"
    csv_io.export_to_csv([product], csv_path, image_filename_map={"/local/original/photo.png": "TSHIRT-001.webp"})

    rows = read_csv_dicts(csv_path)
    assert rows[0]["product_image"] == "TSHIRT-001.webp"
    assert "/local/original" not in rows[0]["product_image"]


def test_image_ref_preserved_when_not_reexported(tmp_path):
    """A product imported with an existing image URL, re-exported without
    picking a new local file, should keep referencing that same URL."""
    product = Product(
        sku="TSHIRT-001", product_type="simple", name="Tee", price="10",
        image_path=None, image_ref="https://example.com/tee.jpg",
    )
    csv_path = tmp_path / "export.csv"
    csv_io.export_to_csv([product], csv_path, image_filename_map={})

    rows = read_csv_dicts(csv_path)
    assert rows[0]["product_image"] == "https://example.com/tee.jpg"


def test_mismatched_product_type_across_rows_is_skipped(tmp_path):
    csv_path = tmp_path / "mixed.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv_module.writer(f)
        writer.writerow(["parent_sku", "product_type", "product_name", "variation_sku", "variation_price"])
        writer.writerow(["X-001", "simple", "X", "", "5"])
        writer.writerow(["X-001", "variable", "X", "X-001-A", "5"])

    imported, warnings = csv_io.import_from_csv(csv_path)
    assert len(imported) == 1
    assert len(warnings) == 1
    assert "does not match" in warnings[0]
