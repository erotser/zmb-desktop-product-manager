"""
The variation grid for variable products.

Source of truth is `self._variations` (a plain list of Variation objects);
the QTableWidget is a rendering of it, kept in sync via itemChanged for the
plain-text columns and dedicated widgets for the checkbox/image/remove
columns. This is simpler to test and reason about than trying to read
everything back out of table cell text on every access.

"Generate from attributes" computes the Cartesian product of the attribute
palettes and does a smart merge: a combination that already has a variation
keeps all its existing data (SKU, price, image, ...); a brand new
combination gets a fresh row with a suggested SKU the user can edit; a
combination that's no longer possible gets its row removed -- but only
after the caller confirms, since that could discard entered data.
"""

from __future__ import annotations

import itertools
from typing import Callable, Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..i18n import t
from ..models import ProductAttribute, Variation
from .image_picker import ImagePickerWidget
from PySide6.QtWidgets import QDialog, QDialogButtonBox


FIXED_COLUMNS = ["sku", "price", "sale_price", "stock_qty", "manage_stock", "image", "description", "remove"]
FIXED_COLUMN_LABELS = {
    "sku": "variation.sku", "price": "variation.price", "sale_price": "variation.sale_price",
    "stock_qty": "variation.stock_quantity", "manage_stock": "product_form.manage_stock",
    "image": "variation.image", "description": "variation.description", "remove": "",
}


def _attribute_key(attribute_values: dict[str, str], attr_names: list[str]) -> tuple:
    return tuple(attribute_values.get(name, "") for name in attr_names)


def _suggested_sku(parent_sku: str, combo: dict[str, str]) -> str:
    parts = [parent_sku] + [v.upper().replace(" ", "") for v in combo.values()]
    return "-".join(parts)


class VariationImageDialog(QDialog):
    def __init__(self, variation: Variation, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("variation.image"))
        layout = QVBoxLayout(self)

        self.picker = ImagePickerWidget()
        self.picker.set_value(variation.image_path, variation.image_alt, variation.image_ref)
        layout.addWidget(self.picker)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class VariationTableWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None, confirm_fn: Optional[Callable[[str], bool]] = None):
        super().__init__(parent)
        self._variations: list[Variation] = []
        self._attribute_names: list[str] = []
        self._parent_sku = ""
        # Allows tests to inject a fake confirmation instead of a real
        # message box; defaults to a real Qt confirmation dialog.
        self._confirm_fn = confirm_fn or self._default_confirm
        self._syncing = False  # guards against itemChanged firing during programmatic rebuilds

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.generate_button = QPushButton(t("product_form.generate_variations"))
        self.generate_button.clicked.connect(self._on_generate_clicked)
        layout.addWidget(self.generate_button)

        self.table = QTableWidget()
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

    def set_parent_sku(self, sku: str):
        self._parent_sku = sku

    def set_attribute_source(self, get_attributes_fn: Callable[[], list[ProductAttribute]]):
        self._get_attributes_fn = get_attributes_fn

    def get_variations(self) -> list[Variation]:
        return list(self._variations)

    def set_variations(self, variations: list[Variation], attribute_names: list[str]):
        self._variations = list(variations)
        self._attribute_names = list(attribute_names)
        self._render()

    # ------------------------------------------------------------------ #
    # Generation
    # ------------------------------------------------------------------ #

    def _on_generate_clicked(self):
        attributes = self._get_attributes_fn() if hasattr(self, "_get_attributes_fn") else []
        attributes = [a for a in attributes if a.values]
        if not attributes:
            QMessageBox.warning(self, t("common.warning"), t("variations.no_attributes"))
            return
        self.generate_from_attributes(attributes)

    def generate_from_attributes(self, attributes: list[ProductAttribute]):
        attr_names = [a.name for a in attributes]
        value_lists = [a.values for a in attributes]
        combos = [dict(zip(attr_names, combo)) for combo in itertools.product(*value_lists)]

        existing_by_key = {
            _attribute_key(v.attribute_values, attr_names): v
            for v in self._variations
            if set(v.attribute_values.keys()) >= set(attr_names)
        }

        new_variations: list[Variation] = []
        kept_keys = set()
        for combo in combos:
            key = _attribute_key(combo, attr_names)
            kept_keys.add(key)
            if key in existing_by_key:
                new_variations.append(existing_by_key[key])
            else:
                new_variations.append(Variation(
                    sku=_suggested_sku(self._parent_sku, combo),
                    attribute_values=dict(combo),
                ))

        removed = [v for k, v in existing_by_key.items() if k not in kept_keys]
        if removed:
            removed_skus = ", ".join(v.sku for v in removed)
            if not self._confirm_fn(t("variations.confirm_remove", skus=removed_skus)):
                return

        self._variations = new_variations
        self._attribute_names = attr_names
        self._render()
        self.changed.emit()

    def _default_confirm(self, message: str) -> bool:
        reply = QMessageBox.question(
            self, t("common.warning"), message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        return reply == QMessageBox.Yes

    # ------------------------------------------------------------------ #
    # Table rendering / sync
    # ------------------------------------------------------------------ #

    def _columns(self) -> list[str]:
        return list(self._attribute_names) + FIXED_COLUMNS

    def _render(self):
        self._syncing = True
        columns = self._columns()
        self.table.setColumnCount(len(columns))

        labels = []
        for c in self._attribute_names:
            labels.append(c)
        for c in FIXED_COLUMNS:
            key = FIXED_COLUMN_LABELS[c]
            labels.append(t(key) if key else "")
        self.table.setHorizontalHeaderLabels(labels)

        self.table.setRowCount(len(self._variations))
        for row_index, variation in enumerate(self._variations):
            self._render_row(row_index, variation, columns)

        self._syncing = False

    def _render_row(self, row_index: int, variation: Variation, columns: list[str]):
        for col_index, col in enumerate(columns):
            if col in self._attribute_names:
                item = QTableWidgetItem(variation.attribute_values.get(col, ""))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_index, col_index, item)
            elif col == "sku":
                self.table.setItem(row_index, col_index, QTableWidgetItem(variation.sku))
            elif col == "price":
                self.table.setItem(row_index, col_index, QTableWidgetItem(variation.price))
            elif col == "sale_price":
                self.table.setItem(row_index, col_index, QTableWidgetItem(variation.sale_price))
            elif col == "stock_qty":
                self.table.setItem(row_index, col_index, QTableWidgetItem(variation.stock_qty))
            elif col == "manage_stock":
                checkbox = QCheckBox()
                checkbox.setChecked(variation.manage_stock)
                checkbox.stateChanged.connect(
                    lambda state, r=row_index: self._on_manage_stock_changed(r, state)
                )
                self.table.setCellWidget(row_index, col_index, checkbox)
            elif col == "image":
                button = QPushButton(t("product_form.choose_image") if not variation.has_image_set() else "🖼")
                button.clicked.connect(lambda _, r=row_index: self._on_image_button_clicked(r))
                self.table.setCellWidget(row_index, col_index, button)
            elif col == "description":
                self.table.setItem(row_index, col_index, QTableWidgetItem(variation.description))
            elif col == "remove":
                button = QPushButton("✕")
                button.clicked.connect(lambda _, r=row_index: self._on_remove_row_clicked(r))
                self.table.setCellWidget(row_index, col_index, button)

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._syncing:
            return
        row, col = item.row(), item.column()
        columns = self._columns()
        if row >= len(self._variations) or col >= len(columns):
            return
        col_name = columns[col]
        variation = self._variations[row]
        text = item.text()
        if col_name == "sku":
            variation.sku = text
        elif col_name == "price":
            variation.price = text
        elif col_name == "sale_price":
            variation.sale_price = text
        elif col_name == "stock_qty":
            variation.stock_qty = text
        elif col_name == "description":
            variation.description = text
        self.changed.emit()

    def _on_manage_stock_changed(self, row: int, state: int):
        if row < len(self._variations):
            self._variations[row].manage_stock = bool(state)
            self.changed.emit()

    def _on_image_button_clicked(self, row: int):
        if row >= len(self._variations):
            return
        variation = self._variations[row]
        dialog = VariationImageDialog(variation, self)
        if dialog.exec() == QDialog.Accepted:
            variation.image_path = dialog.picker.get_local_path()
            variation.image_ref = dialog.picker.get_existing_ref()
            variation.image_alt = dialog.picker.get_alt()
            self._render()
            self.changed.emit()

    def _on_remove_row_clicked(self, row: int):
        if row < len(self._variations):
            del self._variations[row]
            self._render()
            self.changed.emit()
