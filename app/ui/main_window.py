"""Main window: product list on the left, edit form on the right."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog, QInputDialog, QLabel, QMainWindow, QMessageBox, QSplitter, QStackedWidget, QWidget,
)
from PySide6.QtCore import Qt

from .. import csv_io
from ..db import Database
from ..i18n import t
from ..image_manager import ImageExporter
from ..models import Product
from ..settings import AppSettings, SettingsStore
from .product_form_simple import SimpleProductForm
from .product_form_variable import VariableProductForm
from .product_list import ProductListWidget
from .settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self, db: Database, settings_store: SettingsStore, settings: AppSettings):
        super().__init__()
        self.db = db
        self.settings_store = settings_store
        self.settings = settings

        self.setWindowTitle(t("app.title"))
        self.resize(1200, 800)

        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        self.product_list = ProductListWidget()
        self.product_list.add_simple_requested.connect(self._on_add_simple)
        self.product_list.add_variable_requested.connect(self._on_add_variable)
        self.product_list.edit_requested.connect(self._on_edit)
        self.product_list.delete_requested.connect(self._on_delete)
        splitter.addWidget(self.product_list)

        self.form_stack = QStackedWidget()

        self.placeholder = QLabel(t("products.empty_state"))
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.form_stack.addWidget(self.placeholder)

        self.simple_form = SimpleProductForm()
        self.simple_form.saved.connect(self._on_form_saved)
        self.simple_form.cancelled.connect(self._show_placeholder)
        self.form_stack.addWidget(self.simple_form)

        self.variable_form = VariableProductForm()
        self.variable_form.saved.connect(self._on_form_saved)
        self.variable_form.cancelled.connect(self._show_placeholder)
        self.form_stack.addWidget(self.variable_form)

        splitter.addWidget(self.form_stack)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self._build_menu()
        self._refresh_list()

    # ------------------------------------------------------------------ #
    # Menu
    # ------------------------------------------------------------------ #

    def _build_menu(self):
        file_menu = self.menuBar().addMenu(t("nav.products"))

        import_action = file_menu.addAction(t("csv.import"))
        import_action.triggered.connect(self._on_import_csv)

        export_action = file_menu.addAction(t("csv.export"))
        export_action.triggered.connect(self._on_export_csv)

        file_menu.addSeparator()
        settings_action = file_menu.addAction(t("nav.settings"))
        settings_action.triggered.connect(self._on_open_settings)

        file_menu.addSeparator()
        clear_all_action = file_menu.addAction(t("products.clear_all"))
        clear_all_action.triggered.connect(self._on_clear_all)

    # ------------------------------------------------------------------ #
    # List / navigation
    # ------------------------------------------------------------------ #

    def _refresh_list(self):
        self.product_list.set_products(self.db.list_products())

    def _show_placeholder(self):
        self.form_stack.setCurrentWidget(self.placeholder)

    def _on_add_simple(self):
        self.simple_form.clear()
        self.form_stack.setCurrentWidget(self.simple_form)

    def _on_add_variable(self):
        self.variable_form.clear()
        self.form_stack.setCurrentWidget(self.variable_form)

    def _on_edit(self, product_id: int):
        product = self.db.get_product(product_id)
        if not product:
            return
        if product.is_simple():
            self.simple_form.load_product(product)
            self.form_stack.setCurrentWidget(self.simple_form)
        else:
            self.variable_form.load_product(product)
            self.form_stack.setCurrentWidget(self.variable_form)

    def _on_delete(self, product_id: int):
        product = self.db.get_product(product_id)
        if not product:
            return
        reply = QMessageBox.question(
            self, t("products.delete"),
            f"{t('products.delete')}: {product.name} ({product.sku})?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.db.delete_product(product_id)
            self._refresh_list()
            self._show_placeholder()

    def _on_clear_all(self):
        count = self.db.count_products()
        if count == 0:
            QMessageBox.information(self, t("products.clear_all"), t("products.clear_all_empty"))
            return

        text, ok = QInputDialog.getText(
            self, t("products.clear_all"),
            t("products.clear_all_confirm_prompt", count=count),
        )
        if not ok:
            return
        if text.strip().upper() != "DELETE":
            QMessageBox.information(self, t("products.clear_all"), t("products.clear_all_cancelled"))
            return

        self.db.clear_all()
        self._refresh_list()
        self._show_placeholder()
        QMessageBox.information(self, t("products.clear_all"), t("products.clear_all_done", count=count))

    def _on_form_saved(self, product: Product):
        try:
            self.db.save_product(product)
        except ValueError as e:
            QMessageBox.critical(self, t("common.error"), str(e))
            return
        self._refresh_list()
        self._show_placeholder()

    # ------------------------------------------------------------------ #
    # CSV import / export
    # ------------------------------------------------------------------ #

    def _on_import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, t("csv.import"), "", "CSV Files (*.csv)")
        if not path:
            return
        try:
            products, warnings = csv_io.import_from_csv(path)
        except csv_io.CsvFormatError as e:
            QMessageBox.critical(self, t("common.error"), str(e))
            return
        except Exception as e:  # noqa: BLE001 -- any unexpected parsing failure should be visible, not silent
            QMessageBox.critical(
                self, t("common.error"),
                f"Could not read this CSV file:\n\n{type(e).__name__}: {e}",
            )
            return

        save_errors = []
        saved_count = 0
        for product in products:
            try:
                self.db.save_product(product)
                saved_count += 1
            except ValueError as e:
                save_errors.append(f"{product.sku or '(no SKU)'}: {e}")

        self._refresh_list()

        all_issues = list(warnings) + save_errors
        if all_issues:
            QMessageBox.warning(
                self, t("csv.import_warnings_title"),
                t("csv.import_success", count=saved_count) + "\n\n" + "\n".join(all_issues),
            )
        else:
            QMessageBox.information(self, t("common.ok"), t("csv.import_success", count=saved_count))

    def _on_export_csv(self):
        products = self.db.list_products()
        if not products:
            QMessageBox.information(self, t("common.ok"), t("products.empty_state"))
            return

        csv_path, _ = QFileDialog.getSaveFileName(self, t("csv.export"), "products.csv", "CSV Files (*.csv)")
        if not csv_path:
            return

        output_dir = Path(self.settings.output_images_folder)
        cache_dir = output_dir.parent / ".zpm-image-cache"
        exporter = ImageExporter(output_dir, cache_dir, self.settings.compression_settings())

        def confirm_clear() -> bool:
            reply = QMessageBox.question(
                self, t("images.export_confirm_title"),
                t("images.export_confirm_body", folder=str(output_dir)),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            return reply == QMessageBox.Yes

        try:
            filename_map = exporter.export_images(products, confirm_clear=confirm_clear)
        except Exception as e:  # noqa: BLE001 -- surfacing any image failure to the user, not just our own error type
            if "cancelled" not in str(e).lower():
                QMessageBox.critical(self, t("common.error"), str(e))
            return

        csv_io.export_to_csv(products, csv_path, image_filename_map=filename_map)
        QMessageBox.information(
            self, t("common.ok"), t("csv.export_success", count=len(products), path=csv_path)
        )

    # ------------------------------------------------------------------ #
    # Settings
    # ------------------------------------------------------------------ #

    def _on_open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            self.settings = dialog.get_settings()
            self.settings_store.save(self.settings)
