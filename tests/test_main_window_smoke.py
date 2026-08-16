"""
Smoke tests that build the actual MainWindow (headlessly) and exercise the
full add -> save -> list -> edit -> CSV export -> CSV import loop, the way a
real user session would. These catch wiring mistakes that per-widget unit
tests can't (signals connected to the wrong slot, wrong data flowing
between the list/forms/db, etc).
"""

import csv as csv_module

import pytest

from app.db import Database
from app.image_manager import CompressionSettings
from app.models import ProductAttribute
from app.settings import AppSettings, SettingsStore
from app.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot, tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    settings_store = SettingsStore(config_dir=tmp_path / "config")
    settings = AppSettings(
        database_path=str(tmp_path / "test.sqlite3"),
        output_images_folder=str(tmp_path / "upload-images"),
    )
    win = MainWindow(db, settings_store, settings)
    qtbot.addWidget(win)
    yield win
    db.close()


def test_add_simple_product_end_to_end(window, qtbot):
    window._on_add_simple()
    assert window.form_stack.currentWidget() is window.simple_form

    window.simple_form.sku_input.setText("MUG-001")
    window.simple_form.name_input.setText("Ceramic Mug")
    window.simple_form.price_input.setText("12.50")

    with qtbot.waitSignal(window.simple_form.saved, timeout=1000):
        window.simple_form._on_save_clicked()

    products = window.db.list_products()
    assert len(products) == 1
    assert products[0].sku == "MUG-001"

    # List should reflect the newly saved product.
    assert window.product_list.table.rowCount() == 1
    assert window.product_list.table.item(0, 1).text() == "MUG-001"


def test_add_variable_product_end_to_end(window, qtbot):
    window._on_add_variable()
    window.variable_form.sku_input.setText("TSHIRT-001")
    window.variable_form.name_input.setText("Tee")
    window.variable_form.attribute_editor.add_row("Color", ["Red", "Blue"])
    window.variable_form.variation_table.generate_from_attributes(
        window.variable_form.attribute_editor.get_attributes()
    )
    # Generated variations intentionally start with an empty price (no
    # sensible default) -- a real user fills these in before saving.
    for v in window.variable_form.variation_table.get_variations():
        v.price = "19.99"

    with qtbot.waitSignal(window.variable_form.saved, timeout=1000):
        window.variable_form._on_save_clicked()

    products = window.db.list_products()
    assert len(products) == 1
    assert len(products[0].variations) == 2


def test_edit_existing_product_loads_correct_form(window, qtbot):
    window._on_add_simple()
    window.simple_form.sku_input.setText("X-001")
    window.simple_form.name_input.setText("X")
    window.simple_form.price_input.setText("5")
    with qtbot.waitSignal(window.simple_form.saved, timeout=1000):
        window.simple_form._on_save_clicked()

    product_id = window.db.list_products()[0].id
    window._on_edit(product_id)

    assert window.form_stack.currentWidget() is window.simple_form
    assert window.simple_form.sku_input.text() == "X-001"


def test_delete_product_removes_it_from_list(window, qtbot, monkeypatch):
    window._on_add_simple()
    window.simple_form.sku_input.setText("X-001")
    window.simple_form.name_input.setText("X")
    window.simple_form.price_input.setText("5")
    with qtbot.waitSignal(window.simple_form.saved, timeout=1000):
        window.simple_form._on_save_clicked()

    product_id = window.db.list_products()[0].id

    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **kw: QMessageBox.Yes))

    window._on_delete(product_id)
    assert window.db.list_products() == []
    assert window.product_list.table.rowCount() == 0


def test_import_with_one_bad_row_still_saves_and_shows_the_good_ones(window, qtbot, tmp_path, monkeypatch):
    """
    Regression test: previously, if one product in a CSV failed
    Database.save_product()'s validation (e.g. a variation SKU identical to
    its own parent SKU -- valid enough to have made it past CSV parsing,
    but rejected by the stricter app-level validation), the save loop
    raised uncaught, aborting before the product list ever refreshed. Every
    earlier product in the file was silently saved to the database but
    never shown until some unrelated action triggered a refresh.
    """
    import csv as csv_module

    csv_path = tmp_path / "mixed.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv_module.writer(f)
        writer.writerow(["parent_sku", "product_type", "product_name", "variation_sku", "variation_price"])
        # A valid product first.
        writer.writerow(["GOOD-001", "simple", "Good Product", "", "10.00"])
        # A second product whose variation SKU equals its own parent SKU --
        # passes CSV-level parsing (both fields non-empty) but fails the
        # app's stricter Product.validate().
        writer.writerow(["BAD-001", "variable", "Bad Product", "BAD-001", "5.00"])

    from PySide6.QtWidgets import QFileDialog, QMessageBox
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **kw: (str(csv_path), "")))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: None))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))

    window._on_import_csv()

    # The good product must be saved AND the list must reflect it immediately.
    products = window.db.list_products()
    skus = {p.sku for p in products}
    assert "GOOD-001" in skus

    assert window.product_list.table.rowCount() == len(products)
    displayed_skus = {window.product_list.table.item(r, 1).text() for r in range(window.product_list.table.rowCount())}
    assert "GOOD-001" in displayed_skus


def test_clear_all_via_menu_requires_typing_delete(window, qtbot, monkeypatch):
    window._on_add_simple()
    window.simple_form.sku_input.setText("X-001")
    window.simple_form.name_input.setText("X")
    window.simple_form.price_input.setText("5")
    with qtbot.waitSignal(window.simple_form.saved, timeout=1000):
        window.simple_form._on_save_clicked()
    assert window.db.count_products() == 1

    from PySide6.QtWidgets import QInputDialog, QMessageBox
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))

    # Wrong confirmation text -- nothing should be deleted.
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **kw: ("nope", True)))
    window._on_clear_all()
    assert window.db.count_products() == 1

    # User cancels the dialog entirely -- nothing deleted.
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **kw: ("DELETE", False)))
    window._on_clear_all()
    assert window.db.count_products() == 1

    # Correct confirmation -- everything is deleted and the list refreshes.
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **kw: ("DELETE", True)))
    window._on_clear_all()
    assert window.db.count_products() == 0
    assert window.product_list.table.rowCount() == 0


def test_full_export_then_import_cycle(window, qtbot, tmp_path, monkeypatch):
    # Save one simple and one variable product.
    window._on_add_simple()
    window.simple_form.sku_input.setText("MUG-001")
    window.simple_form.name_input.setText("Mug")
    window.simple_form.price_input.setText("10")
    with qtbot.waitSignal(window.simple_form.saved, timeout=1000):
        window.simple_form._on_save_clicked()

    window._on_add_variable()
    window.variable_form.sku_input.setText("TSHIRT-001")
    window.variable_form.name_input.setText("Tee")
    window.variable_form.attribute_editor.add_row("Color", ["Red"])
    window.variable_form.variation_table.generate_from_attributes(
        window.variable_form.attribute_editor.get_attributes()
    )
    window.variable_form.variation_table.get_variations()[0].price = "19.99"
    with qtbot.waitSignal(window.variable_form.saved, timeout=1000):
        window.variable_form._on_save_clicked()

    assert len(window.db.list_products()) == 2

    # Export -- bypass the real file dialogs/message boxes.
    csv_path = tmp_path / "export.csv"
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **kw: (str(csv_path), "")))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **kw: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))

    window._on_export_csv()
    assert csv_path.exists()

    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv_module.DictReader(f))
    assert len(rows) == 2  # 1 simple row + 1 variation row
    skus = {r["parent_sku"] for r in rows}
    assert skus == {"MUG-001", "TSHIRT-001"}

    # Wipe the DB and re-import the exported file -- should restore both products.
    for p in window.db.list_products():
        window.db.delete_product(p.id)
    assert window.db.list_products() == []

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **kw: (str(csv_path), "")))

    window._on_import_csv()
    reimported = window.db.list_products()
    assert len(reimported) == 2
    reimported_skus = {p.sku for p in reimported}
    assert reimported_skus == {"MUG-001", "TSHIRT-001"}
