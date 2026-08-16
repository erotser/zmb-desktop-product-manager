"""
Editor for a product's attributes: a list of rows, each with a name and a
comma-separated list of possible values. Used by both the simple-product
form (values become the displayed pipe-joined options) and the
variable-product form (values become the palette variations are generated
from).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..i18n import t
from ..models import ProductAttribute


class AttributeRow(QWidget):
    changed = Signal()
    remove_requested = Signal(object)  # emits self

    def __init__(self, name: str = "", values: list[str] | None = None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.name_input = QLineEdit(name)
        self.name_input.setPlaceholderText(t("product_form.attribute_name"))
        self.name_input.textChanged.connect(lambda _: self.changed.emit())
        layout.addWidget(self.name_input, 1)

        self.values_input = QLineEdit(", ".join(values or []))
        self.values_input.setPlaceholderText(t("product_form.attribute_values"))
        self.values_input.textChanged.connect(lambda _: self.changed.emit())
        layout.addWidget(self.values_input, 2)

        remove_button = QPushButton("✕")
        remove_button.setFixedWidth(28)
        remove_button.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(remove_button)

    def get_attribute(self) -> ProductAttribute | None:
        name = self.name_input.text().strip()
        values = [v.strip() for v in self.values_input.text().split(",") if v.strip()]
        if not name or not values:
            return None
        return ProductAttribute(name=name, values=values)


class AttributeEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[AttributeRow] = []

        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)

        self.rows_container = QVBoxLayout()
        self.layout_.addLayout(self.rows_container)

        add_button = QPushButton(t("product_form.add_attribute"))
        add_button.clicked.connect(lambda: self.add_row())
        self.layout_.addWidget(add_button)

    def add_row(self, name: str = "", values: list[str] | None = None) -> AttributeRow:
        row = AttributeRow(name, values)
        row.remove_requested.connect(self._remove_row)
        row.changed.connect(self.changed.emit)
        self._rows.append(row)
        self.rows_container.addWidget(row)
        self.changed.emit()
        return row

    def _remove_row(self, row: AttributeRow):
        self._rows.remove(row)
        self.rows_container.removeWidget(row)
        row.deleteLater()
        self.changed.emit()

    def get_attributes(self) -> list[ProductAttribute]:
        result = []
        for row in self._rows:
            attr = row.get_attribute()
            if attr:
                result.append(attr)
        return result

    def set_attributes(self, attributes: list[ProductAttribute]):
        for row in list(self._rows):
            self._remove_row(row)
        for attr in attributes:
            self.add_row(attr.name, attr.values)
