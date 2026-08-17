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


def test_clicking_a_list_row_previews_it_without_clicking_edit(window, qtbot):
    """QOL: selecting a row in the list should load it into the form
    immediately, without requiring a separate click on the Edit button."""
    window._on_add_simple()
    window.simple_form.sku_input.setText("X-001")
    window.simple_form.name_input.setText("Preview Me")
    window.simple_form.price_input.setText("5")
    with qtbot.waitSignal(window.simple_form.saved, timeout=1000):
        window.simple_form._on_save_clicked()

    # Move off the form so we can confirm selecting the row is what brings it back.
    window._show_placeholder()
    assert window.form_stack.currentWidget() is window.placeholder

    # Simulate an actual row click by selecting the row in the table --
    # this exercises the real itemSelectionChanged -> selection_changed
    # signal path, not just calling the handler function directly.
    window.product_list.table.selectRow(0)

    assert window.form_stack.currentWidget() is window.simple_form
    assert window.simple_form.sku_input.text() == "X-001"


def test_clicking_a_variable_product_row_previews_correct_form(window, qtbot):
    window._on_add_variable()
    window.variable_form.sku_input.setText("TSHIRT-001")
    window.variable_form.name_input.setText("Tee")
    window.variable_form.attribute_editor.add_row("Color", ["Red"])
    window.variable_form.variation_table.generate_from_attributes(
        window.variable_form.attribute_editor.get_attributes()
    )
    window.variable_form.variation_table.get_variations()[0].price = "10"
    with qtbot.waitSignal(window.variable_form.saved, timeout=1000):
        window.variable_form._on_save_clicked()

    window._show_placeholder()
    window.product_list.table.selectRow(0)

    assert window.form_stack.currentWidget() is window.variable_form
    assert window.variable_form.sku_input.text() == "TSHIRT-001"


def test_save_and_sync_end_to_end_against_real_server(window, qtbot, monkeypatch):
    """Full chain: click 'Save & Sync to Site' in the real form -> main
    window handler -> site_sync client -> a real local HTTP server
    standing in for the WordPress site -> result dialog. Verifies the
    actual wiring, not just each piece in isolation."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    received = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self._json(200, {"plugin": "zombee-product-manager", "plugin_version": "1.4.2", "site_name": "Test"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            received["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
            self._json(200, {
                "success": True, "product_id": 999,
                "counts": {"products_created": 1, "products_updated": 0, "variations_created": 0,
                           "variations_updated": 0, "rows_failed": 0},
                "log": ["Creating new product MUG-SYNC-001"],
            })

        def _json(self, status, body):
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        window.settings.site_url = f"http://127.0.0.1:{server.server_port}"
        window.settings.site_username = "admin"

        from app import credential_store
        monkeypatch.setattr(credential_store, "load_application_password", lambda: "xxxx xxxx xxxx xxxx")

        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))

        window._on_add_simple()
        window.simple_form.sku_input.setText("MUG-SYNC-001")
        window.simple_form.name_input.setText("Sync Test Mug")
        window.simple_form.price_input.setText("10.00")

        window.simple_form._on_sync_clicked()

        # The product was saved locally...
        assert window.db.get_product_by_sku("MUG-SYNC-001") is not None
        # ...and the real HTTP server actually received it.
        assert received["body"]["parent_sku"] == "MUG-SYNC-001"
        assert received["body"]["product_name"] == "Sync Test Mug"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_sync_without_configured_connection_still_saves_locally(window, qtbot, monkeypatch):
    """If no site connection is set up, syncing should still save locally
    and tell the user why it didn't push, rather than failing silently or
    losing the local save."""
    from PySide6.QtWidgets import QMessageBox
    messages = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: messages.append(a)))

    window._on_add_simple()
    window.simple_form.sku_input.setText("X-001")
    window.simple_form.name_input.setText("X")
    window.simple_form.price_input.setText("5")

    window.simple_form._on_sync_clicked()

    assert window.db.get_product_by_sku("X-001") is not None
    assert len(messages) == 1


def test_clearing_password_field_in_settings_actually_clears_stored_credential(window, qtbot, monkeypatch):
    """Regression: previously, submitting Settings with the password field
    blanked out silently left the OLD stored password untouched instead of
    removing it, since `if password:` was false for an empty string and
    nothing else handled that case. This exercises the real
    _on_open_settings() code path, not a reimplementation of its logic."""
    from app import credential_store
    from app.ui.settings_dialog import SettingsDialog

    # No real OS keychain exists in this test environment -- swap in an
    # in-memory fake, same approach as test_credential_store.py.
    fake_store = {}
    monkeypatch.setattr(credential_store.keyring, "set_password", lambda s, u, p: fake_store.update({u: p}))
    monkeypatch.setattr(credential_store.keyring, "get_password", lambda s, u: fake_store.get(u))

    def fake_delete(s, u):
        if u not in fake_store:
            import keyring.errors
            raise keyring.errors.PasswordDeleteError("not found")
        del fake_store[u]

    monkeypatch.setattr(credential_store.keyring, "delete_password", fake_delete)

    credential_store.save_application_password("original-password")
    assert credential_store.load_application_password() == "original-password"

    def fake_exec(self):
        # Simulates: dialog opened (pre-filled with "original-password" per
        # normal behavior), user deliberately cleared the field, clicked OK.
        self.site_password_input.setText("")
        return 1  # QDialog.Accepted

    monkeypatch.setattr(SettingsDialog, "exec", fake_exec)

    window._on_open_settings()

    assert credential_store.load_application_password() is None


def test_factory_reset_wrong_or_cancelled_confirmation_changes_nothing(window, qtbot, monkeypatch):
    from app import credential_store

    fake_store = {}
    monkeypatch.setattr(credential_store.keyring, "set_password", lambda s, u, p: fake_store.update({u: p}))
    monkeypatch.setattr(credential_store.keyring, "get_password", lambda s, u: fake_store.get(u))
    monkeypatch.setattr(credential_store.keyring, "delete_password", lambda s, u: fake_store.pop(u, None))

    window._on_add_simple()
    window.simple_form.sku_input.setText("X-001")
    window.simple_form.name_input.setText("X")
    window.simple_form.price_input.setText("5")
    with qtbot.waitSignal(window.simple_form.saved, timeout=1000):
        window.simple_form._on_save_clicked()

    credential_store.save_application_password("secret-password")
    window.settings.site_url = "https://example.com"
    window.settings.site_username = "admin"

    from PySide6.QtWidgets import QInputDialog, QMessageBox
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **kw: ("nope", True)))
    window._on_factory_reset()
    assert window.db.count_products() == 1
    assert credential_store.load_application_password() == "secret-password"
    assert window.settings.site_url == "https://example.com"

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **kw: ("RESET", False)))
    window._on_factory_reset()
    assert window.db.count_products() == 1
    assert credential_store.load_application_password() == "secret-password"


def test_factory_reset_clears_products_credential_and_site_settings(window, qtbot, monkeypatch):
    from app import credential_store

    fake_store = {}
    monkeypatch.setattr(credential_store.keyring, "set_password", lambda s, u, p: fake_store.update({u: p}))
    monkeypatch.setattr(credential_store.keyring, "get_password", lambda s, u: fake_store.get(u))
    monkeypatch.setattr(credential_store.keyring, "delete_password", lambda s, u: fake_store.pop(u, None))

    window._on_add_simple()
    window.simple_form.sku_input.setText("X-001")
    window.simple_form.name_input.setText("X")
    window.simple_form.price_input.setText("5")
    with qtbot.waitSignal(window.simple_form.saved, timeout=1000):
        window.simple_form._on_save_clicked()
    assert window.db.count_products() == 1

    credential_store.save_application_password("secret-password")
    window.settings.site_url = "https://example.com"
    window.settings.site_username = "admin"

    from PySide6.QtWidgets import QInputDialog, QMessageBox
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **kw: ("RESET", True)))

    window._on_factory_reset()

    assert window.db.count_products() == 0
    assert window.product_list.table.rowCount() == 0
    assert credential_store.load_application_password() is None
    assert window.settings.site_url == ""
    assert window.settings.site_username == ""

    # Also confirmed persisted to disk, not just the in-memory object.
    reloaded = window.settings_store.load()
    assert reloaded.site_url == ""
    assert reloaded.site_username == ""


def test_window_title_shows_current_version(window):
    from app import __version__
    assert __version__ in window.windowTitle()


def test_about_dialog_shows_current_version(window, monkeypatch):
    from app import __version__
    from PySide6.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "about", staticmethod(lambda *a: shown.append(a)))

    window._on_about()

    assert len(shown) == 1
    about_body = shown[0][2]  # QMessageBox.about(parent, title, text) -- text is 3rd arg
    assert __version__ in about_body


def test_download_from_site_end_to_end_against_real_server(window, qtbot, monkeypatch):
    """Full chain: Download from Site -> real HTTP server standing in for
    the WordPress site -> downloaded CSV written locally -> parsed via the
    same import path as a manually picked file -> products appear in the
    local database and the list."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/wp-json/zombee/v1/export":
                csv_content = (
                    "\ufeffparent_sku,product_type,product_name,variation_sku,variation_price\r\n"
                    "DL-MUG-001,simple,Downloaded Mug,,15.00\r\n"
                )
                payload = csv_content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        window.settings.site_url = f"http://127.0.0.1:{server.server_port}"
        window.settings.site_username = "admin"

        from app import credential_store
        monkeypatch.setattr(credential_store, "load_application_password", lambda: "xxxx xxxx xxxx xxxx")

        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))

        window._on_download_from_site()

        product = window.db.get_product_by_sku("DL-MUG-001")
        assert product is not None
        assert product.name == "Downloaded Mug"
        assert product.price == "15.00"
        assert window.product_list.table.rowCount() == 1

        # The temp download file shouldn't linger after a successful import.
        from pathlib import Path
        tmp_path = Path(window.settings.database_path).parent / "downloaded-export.csv"
        assert not tmp_path.exists()
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_download_from_site_without_connection_shows_setup_message(window, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    messages = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: messages.append(a)))

    window._on_download_from_site()

    assert len(messages) == 1
    assert window.db.list_products() == []


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
