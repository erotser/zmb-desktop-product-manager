"""Left-hand product list: search box, table, add/edit/delete buttons."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..i18n import t
from ..models import Product


class ProductListWidget(QWidget):
    add_simple_requested = Signal()
    add_variable_requested = Signal()
    edit_requested = Signal(int)     # product id
    delete_requested = Signal(int)   # product id
    selection_changed = Signal(object)  # Optional[int]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._products: list[Product] = []

        layout = QVBoxLayout(self)

        button_row = QHBoxLayout()
        self.add_simple_button = QPushButton(t("products.add_simple"))
        self.add_simple_button.clicked.connect(self.add_simple_requested.emit)
        button_row.addWidget(self.add_simple_button)

        self.add_variable_button = QPushButton(t("products.add_variable"))
        self.add_variable_button.clicked.connect(self.add_variable_requested.emit)
        button_row.addWidget(self.add_variable_button)
        layout.addLayout(button_row)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(t("products.search_placeholder"))
        self.search_input.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_input)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            t("products.column.name"), t("products.column.sku"),
            t("products.column.type"), t("products.column.price"),
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

        action_row = QHBoxLayout()
        self.edit_button = QPushButton(t("products.edit"))
        self.edit_button.clicked.connect(self._on_edit_clicked)
        self.edit_button.setEnabled(False)
        action_row.addWidget(self.edit_button)

        self.delete_button = QPushButton(t("products.delete"))
        self.delete_button.clicked.connect(self._on_delete_clicked)
        self.delete_button.setEnabled(False)
        action_row.addWidget(self.delete_button)
        layout.addLayout(action_row)

    def set_products(self, products: list[Product]):
        self._products = products
        self._apply_filter()

    def get_selected_product_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0 or row >= self.table.rowCount():
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _apply_filter(self):
        query = self.search_input.text().strip().lower()
        filtered = [
            p for p in self._products
            if not query or query in p.name.lower() or query in p.sku.lower()
        ]
        self._render(filtered)

    def _render(self, products: list[Product]):
        self.table.setRowCount(len(products))
        for row, p in enumerate(products):
            name_item = QTableWidgetItem(p.name)
            name_item.setData(Qt.UserRole, p.id)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(p.sku))
            self.table.setItem(row, 2, QTableWidgetItem(
                t("product.type.simple") if p.is_simple() else t("product.type.variable")
            ))
            price_display = p.price if p.is_simple() else self._variable_price_range(p)
            self.table.setItem(row, 3, QTableWidgetItem(price_display))

    @staticmethod
    def _variable_price_range(product: Product) -> str:
        prices = [v.price for v in product.variations if v.price]
        if not prices:
            return ""
        try:
            values = sorted(float(p) for p in prices)
            if values[0] == values[-1]:
                return f"{values[0]:g}"
            return f"{values[0]:g}\u2013{values[-1]:g}"
        except ValueError:
            return ""

    def _on_selection_changed(self):
        selected_id = self.get_selected_product_id()
        has_selection = selected_id is not None
        self.edit_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)
        self.selection_changed.emit(selected_id)

    def _on_edit_clicked(self):
        selected_id = self.get_selected_product_id()
        if selected_id is not None:
            self.edit_requested.emit(selected_id)

    def _on_delete_clicked(self):
        selected_id = self.get_selected_product_id()
        if selected_id is not None:
            self.delete_requested.emit(selected_id)
