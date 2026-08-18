"""
Background worker for "Sync All to Site".

Runs the per-product sync loop on a separate thread rather than the UI
thread. A single product sync already blocks briefly for one HTTP call,
which is tolerable -- looping that sequentially over a whole catalog on the
UI thread would freeze the app for the entire duration, with no progress
feedback and no way to cancel. This keeps every actual network call off
the UI thread, communicating back only through Qt signals (which are safe
to cross threads), while the UI thread stays free to paint a progress
dialog and respond to Cancel.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from .models import Product
from .site_sync import SiteConnection, SiteSyncError, sync_product


class SyncAllWorker(QThread):
    # index (1-based), total, sku, success, message (warnings on success, reason on failure)
    progress = Signal(int, int, str, bool, str)
    # succeeded_count, failed_count, failure_details (one line per failed product)
    finished_all = Signal(int, int, list)

    def __init__(self, connection: SiteConnection, products: list[Product], parent=None):
        super().__init__(parent)
        self.connection = connection
        self.products = list(products)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        succeeded = 0
        failed = 0
        failure_details: list[str] = []
        total = len(self.products)

        for index, product in enumerate(self.products, start=1):
            if self._cancelled:
                break

            label = product.sku or "(no SKU)"

            try:
                result = sync_product(self.connection, product)
            except SiteSyncError as e:
                failed += 1
                message = str(e)
                failure_details.append(f"{label}: {message}")
                self.progress.emit(index, total, label, False, message)
                continue

            if result.get("success"):
                succeeded += 1
                warnings = result.get("_warnings") or []
                message = "; ".join(warnings)
                self.progress.emit(index, total, label, True, message)
            else:
                failed += 1
                log_lines = result.get("log") or []
                message = "; ".join(log_lines) if log_lines else "Unknown failure"
                failure_details.append(f"{label}: {message}")
                self.progress.emit(index, total, label, False, message)

        self.finished_all.emit(succeeded, failed, failure_details)
