"""Main window: product list on the left, edit form on the right."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QFileDialog, QInputDialog, QLabel, QMainWindow, QMessageBox,
    QProgressDialog, QSplitter, QStackedWidget, QWidget,
)
from PySide6.QtCore import Qt

from .. import credential_store
from .. import csv_io
from .. import __version__
from ..db import Database
from ..i18n import t
from ..image_manager import ImageExporter
from ..models import Product
from ..settings import AppSettings, SettingsStore
from ..site_sync import SiteConnection, SiteSyncError, download_export, sync_product
from ..sync_worker import SyncAllWorker
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
        # References kept during a "Sync All" run so the QThread and its
        # progress dialog aren't garbage-collected mid-run (a real PySide6
        # gotcha -- a QThread with no surviving reference can be destroyed
        # out from under itself even while still running).
        self._sync_all_worker = None
        self._sync_all_dialog = None

        self.setWindowTitle(f'{t("app.title")} v{__version__}')
        self.resize(1200, 800)

        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        self.product_list = ProductListWidget()
        self.product_list.add_simple_requested.connect(self._on_add_simple)
        self.product_list.add_variable_requested.connect(self._on_add_variable)
        self.product_list.edit_requested.connect(self._on_edit)
        self.product_list.selection_changed.connect(self._on_list_selection_changed)
        self.product_list.delete_requested.connect(self._on_delete)
        splitter.addWidget(self.product_list)

        self.form_stack = QStackedWidget()

        self.placeholder = QLabel(t("products.empty_state"))
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.form_stack.addWidget(self.placeholder)

        self.simple_form = SimpleProductForm()
        self.simple_form.saved.connect(self._on_form_saved)
        self.simple_form.sync_requested.connect(self._on_sync_requested)
        self.simple_form.cancelled.connect(self._show_placeholder)
        self.form_stack.addWidget(self.simple_form)

        self.variable_form = VariableProductForm()
        self.variable_form.saved.connect(self._on_form_saved)
        self.variable_form.sync_requested.connect(self._on_sync_requested)
        self.variable_form.cancelled.connect(self._show_placeholder)
        self.form_stack.addWidget(self.variable_form)

        splitter.addWidget(self.form_stack)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self._build_menu()
        self._refresh_list()

    def closeEvent(self, event):
        """
        Destroying a still-running QThread out from under itself is a real
        crash risk (Qt logs "QThread: Destroyed while thread is still
        running" and the process can terminate uncleanly, or hang on
        exit). Without this, closing the window mid-sync would do exactly
        that -- the worker thread has no chance to stop first.
        """
        if self._sync_all_worker is not None and self._sync_all_worker.isRunning():
            reply = QMessageBox.question(
                self, t("sync_all.menu_item"),
                t("sync_all.quit_confirm"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            self._sync_all_worker.cancel()
            # Give the current in-flight request a moment to actually stop
            # rather than hanging indefinitely -- if it's still not done
            # after this, proceed with closing anyway rather than blocking
            # the user from quitting at all.
            self._sync_all_worker.wait(3000)

        event.accept()

    # ------------------------------------------------------------------ #
    # Menu
    # ------------------------------------------------------------------ #

    def _build_menu(self):
        file_menu = self.menuBar().addMenu(t("nav.products"))

        import_action = file_menu.addAction(t("csv.import"))
        import_action.triggered.connect(self._on_import_csv)

        download_action = file_menu.addAction(t("csv.download_from_site"))
        download_action.triggered.connect(self._on_download_from_site)

        export_action = file_menu.addAction(t("csv.export"))
        export_action.triggered.connect(self._on_export_csv)

        file_menu.addSeparator()
        self.sync_all_action = file_menu.addAction(t("sync_all.menu_item"))
        self.sync_all_action.triggered.connect(self._on_sync_all)

        file_menu.addSeparator()
        settings_action = file_menu.addAction(t("nav.settings"))
        settings_action.triggered.connect(self._on_open_settings)

        file_menu.addSeparator()
        clear_all_action = file_menu.addAction(t("products.clear_all"))
        clear_all_action.triggered.connect(self._on_clear_all)

        factory_reset_action = file_menu.addAction(t("app.factory_reset"))
        factory_reset_action.triggered.connect(self._on_factory_reset)

        help_menu = self.menuBar().addMenu(t("nav.help"))
        about_action = help_menu.addAction(t("app.about_menu_item"))
        about_action.triggered.connect(self._on_about)

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

    def _on_list_selection_changed(self, product_id):
        # Fires on every click in the list, not just the explicit "Edit"
        # button -- selecting a row immediately previews it in the form.
        if product_id is not None:
            self._on_edit(product_id)

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

    def _on_factory_reset(self):
        text, ok = QInputDialog.getText(
            self, t("app.factory_reset"),
            t("app.factory_reset_confirm_prompt"),
        )
        if not ok:
            return
        if text.strip().upper() != "RESET":
            QMessageBox.information(self, t("app.factory_reset"), t("app.factory_reset_cancelled"))
            return

        self.db.clear_all()
        credential_store.clear_application_password()
        self.settings.site_url = ""
        self.settings.site_username = ""
        self.settings_store.save(self.settings)

        self._refresh_list()
        self._show_placeholder()
        QMessageBox.information(self, t("app.factory_reset"), t("app.factory_reset_done"))

    def _on_about(self):
        QMessageBox.about(self, t("app.about_title"), t("app.about_body", version=__version__))

    def _on_form_saved(self, product: Product):
        try:
            self.db.save_product(product)
        except ValueError as e:
            QMessageBox.critical(self, t("common.error"), str(e))
            return
        self._refresh_list()
        self._show_placeholder()

    def _on_sync_requested(self, product: Product):
        # Local save always happens first and uses the exact same path as
        # the plain Save button -- the local database stays the source of
        # truth even for products that get pushed live.
        try:
            self.db.save_product(product)
        except ValueError as e:
            QMessageBox.critical(self, t("common.error"), str(e))
            return
        self._refresh_list()

        connection = self._get_site_connection()
        if connection is None:
            QMessageBox.information(self, t("product_form.save_and_sync"), t("sync.not_configured"))
            self._show_placeholder()
            return

        self.setCursor(Qt.WaitCursor)
        self.statusBar().showMessage(t("sync.in_progress"))
        # Without this, the cursor/status change above would never actually
        # get painted -- Qt only repaints when the event loop runs, and
        # sync_product() below blocks the same thread synchronously, so the
        # "wait" indicator would be invisible for the entire duration it's
        # meant to show.
        QApplication.processEvents()
        try:
            result = sync_product(connection, product)
        except SiteSyncError as e:
            QMessageBox.critical(self, t("sync.error_title"), str(e))
            return
        finally:
            self.unsetCursor()
            self.statusBar().clearMessage()

        self._show_placeholder()
        self._present_sync_result(product, result)

    def _get_site_connection(self):
        if not self.settings.site_url or not self.settings.site_username:
            return None
        password = credential_store.load_application_password()
        if not password:
            return None
        return SiteConnection(
            site_url=self.settings.site_url,
            username=self.settings.site_username,
            application_password=password,
        )

    def _present_sync_result(self, product: Product, result: dict):
        lines = []
        if result.get("_warnings"):
            lines.extend(result["_warnings"])
        if result.get("log"):
            lines.extend(result["log"])

        if result.get("success"):
            title = t("sync.success_title")
            summary = t("sync.success_body", sku=product.sku)
            if lines:
                QMessageBox.information(self, title, summary + "\n\n" + "\n".join(lines))
            else:
                QMessageBox.information(self, title, summary)
        else:
            QMessageBox.warning(
                self, t("sync.failed_title"),
                t("sync.failed_body", sku=product.sku) + "\n\n" + "\n".join(lines or [t("sync.no_details")]),
            )

    # ------------------------------------------------------------------ #
    # CSV import / export
    # ------------------------------------------------------------------ #

    def _on_import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, t("csv.import"), "", "CSV Files (*.csv)")
        if not path:
            return
        self._import_csv_from_path(path)

    def _import_csv_from_path(self, path: str):
        """Shared by the file-picker Import CSV flow and the Download from
        Site flow -- both end up with a local CSV path and from here on
        should behave identically (same parsing, same per-product error
        handling, same result dialog)."""
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

    def _on_download_from_site(self):
        connection = self._get_site_connection()
        if connection is None:
            QMessageBox.information(self, t("csv.download_from_site"), t("sync.not_configured_download"))
            return

        self.setCursor(Qt.WaitCursor)
        self.statusBar().showMessage(t("csv.downloading"))
        QApplication.processEvents()
        try:
            content = download_export(connection)
        except SiteSyncError as e:
            QMessageBox.critical(self, t("sync.error_title"), str(e))
            return
        finally:
            self.unsetCursor()
            self.statusBar().clearMessage()

        tmp_dir = Path(self.settings.database_path).parent
        tmp_path = tmp_dir / "downloaded-export.csv"
        try:
            tmp_path.write_bytes(content)
        except OSError as e:
            QMessageBox.critical(self, t("common.error"), str(e))
            return

        try:
            self._import_csv_from_path(str(tmp_path))
        finally:
            tmp_path.unlink(missing_ok=True)

    def _on_sync_all(self):
        if self._sync_all_worker is not None and self._sync_all_worker.isRunning():
            # Guards against the menu action firing again before the
            # previous run's finished_all has been processed -- without
            # this, a second click would silently overwrite
            # self._sync_all_worker, orphaning the first (still-running)
            # thread, and the first worker's eventual finished_all would
            # close the dialog/clear the references out from under the
            # SECOND run instead.
            QMessageBox.information(self, t("sync_all.menu_item"), t("sync_all.already_running"))
            return

        products = self.db.list_products()
        if not products:
            QMessageBox.information(self, t("sync_all.menu_item"), t("products.empty_state"))
            return

        connection = self._get_site_connection()
        if connection is None:
            QMessageBox.information(self, t("sync_all.menu_item"), t("sync_all.not_configured"))
            return

        reply = QMessageBox.question(
            self, t("sync_all.menu_item"),
            t("sync_all.confirm_prompt", count=len(products)),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._sync_all_dialog = QProgressDialog(
            t("sync_all.starting"), t("common.cancel"), 0, len(products), self
        )
        self._sync_all_dialog.setWindowTitle(t("sync_all.menu_item"))
        self._sync_all_dialog.setWindowModality(Qt.WindowModal)
        self._sync_all_dialog.setMinimumDuration(0)
        self._sync_all_dialog.setValue(0)

        self._sync_all_worker = SyncAllWorker(connection, products, self)
        self._sync_all_worker.progress.connect(self._on_sync_all_progress)
        self._sync_all_worker.finished_all.connect(self._on_sync_all_finished)
        self._sync_all_dialog.canceled.connect(self._sync_all_worker.cancel)

        self.sync_all_action.setEnabled(False)
        self._sync_all_worker.start()

    def _on_sync_all_progress(self, index: int, total: int, sku: str, success: bool, message: str):
        if self._sync_all_dialog is None:
            return
        self._sync_all_dialog.setLabelText(t("sync_all.progress_label", index=index, total=total, sku=sku))
        self._sync_all_dialog.setValue(index)

    def _on_sync_all_finished(self, succeeded: int, failed: int, failure_details: list):
        self.sync_all_action.setEnabled(True)

        if self._sync_all_dialog is not None:
            self._sync_all_dialog.close()
            self._sync_all_dialog = None

        if self._sync_all_worker is not None:
            self._sync_all_worker.wait()
            self._sync_all_worker = None

        if failed:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle(t("sync_all.menu_item"))
            msg.setText(t("sync_all.done_with_failures", succeeded=succeeded, failed=failed))
            msg.setDetailedText("\n".join(failure_details))
            msg.exec()
        else:
            QMessageBox.information(self, t("sync_all.menu_item"), t("sync_all.done_success", count=succeeded))

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
            password = dialog.get_site_password()
            if password:
                try:
                    credential_store.save_application_password(password)
                except credential_store.CredentialStoreError as e:
                    QMessageBox.warning(self, t("common.warning"), str(e))
            else:
                # The field is pre-filled with the currently stored password
                # when the dialog opens, so submitting it empty is an
                # unambiguous, deliberate "remove it" -- not "nothing to do".
                credential_store.clear_application_password()
