"""Editor for a product's custom fields: name/value pairs, add/remove rows."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ..i18n import t
from ..models import CustomField


class CustomFieldRow(QWidget):
    changed = Signal()
    remove_requested = Signal(object)

    def __init__(self, name: str = "", value: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.name_input = QLineEdit(name)
        self.name_input.setPlaceholderText("field_name")
        self.name_input.textChanged.connect(lambda _: self.changed.emit())
        layout.addWidget(self.name_input, 1)

        self.value_input = QLineEdit(value)
        self.value_input.setPlaceholderText(t("product_form.custom_fields"))
        self.value_input.textChanged.connect(lambda _: self.changed.emit())
        layout.addWidget(self.value_input, 2)

        remove_button = QPushButton("✕")
        remove_button.setFixedWidth(28)
        remove_button.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(remove_button)

    def get_custom_field(self) -> CustomField | None:
        name = self.name_input.text().strip()
        if not name:
            return None
        return CustomField(name=name, value=self.value_input.text())


class CustomFieldsEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[CustomFieldRow] = []

        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.rows_container = QVBoxLayout()
        self.rows_container.setSpacing(8)
        self.layout_.addLayout(self.rows_container)

        add_button = QPushButton(t("product_form.add_custom_field"))
        add_button.clicked.connect(lambda: self.add_row())
        self.layout_.addWidget(add_button)

    def add_row(self, name: str = "", value: str = "") -> CustomFieldRow:
        row = CustomFieldRow(name, value)
        row.remove_requested.connect(self._remove_row)
        row.changed.connect(self.changed.emit)
        self._rows.append(row)
        self.rows_container.addWidget(row)
        self.changed.emit()
        return row

    def _remove_row(self, row: CustomFieldRow):
        self._rows.remove(row)
        self.rows_container.removeWidget(row)
        row.deleteLater()
        self.changed.emit()

    def get_custom_fields(self) -> list[CustomField]:
        result = []
        for row in self._rows:
            cf = row.get_custom_field()
            if cf:
                result.append(cf)
        return result

    def set_custom_fields(self, fields: list[CustomField]):
        for row in list(self._rows):
            self._remove_row(row)
        for cf in fields:
            self.add_row(cf.name, cf.value)
