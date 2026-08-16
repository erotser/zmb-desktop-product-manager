"""Form for adding/editing a VARIABLE product."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ..i18n import t
from ..models import Product
from .attribute_editor import AttributeEditorWidget
from .custom_fields_editor import CustomFieldsEditorWidget
from .image_picker import ImagePickerWidget
from .product_form_simple import GalleryEditorWidget
from .variation_table import VariationTableWidget


class VariableProductForm(QWidget):
    saved = Signal(object)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        form = QFormLayout(content)

        self.name_input = QLineEdit()
        self.name_input.textChanged.connect(self._on_sku_or_name_changed)
        form.addRow(t("product_form.name"), self.name_input)

        self.sku_input = QLineEdit()
        self.sku_input.textChanged.connect(self._on_sku_or_name_changed)
        form.addRow(t("product_form.sku"), self.sku_input)

        self.description_input = QPlainTextEdit()
        self.description_input.setFixedHeight(80)
        form.addRow(t("product_form.description"), self.description_input)

        self.short_description_input = QPlainTextEdit()
        self.short_description_input.setFixedHeight(50)
        form.addRow(t("product_form.short_description"), self.short_description_input)

        self.categories_input = QLineEdit()
        self.categories_input.setPlaceholderText(t("product_form.categories_help"))
        form.addRow(t("product_form.categories"), self.categories_input)

        self.tags_input = QLineEdit()
        self.tags_input.setPlaceholderText(t("product_form.tags_help"))
        form.addRow(t("product_form.tags"), self.tags_input)

        self.image_picker = ImagePickerWidget(label=t("product_form.main_image"))
        form.addRow(self.image_picker)

        self.gallery_editor = GalleryEditorWidget()
        form.addRow(t("product_form.gallery"), self.gallery_editor)

        self.attribute_editor = AttributeEditorWidget()
        self.attribute_editor.changed.connect(self._on_attributes_changed)
        form.addRow(t("product_form.attributes"), self.attribute_editor)

        self.variation_table = VariationTableWidget()
        self.variation_table.set_attribute_source(self.attribute_editor.get_attributes)
        form.addRow(t("product_form.variations"), self.variation_table)

        self.custom_fields_editor = CustomFieldsEditorWidget()
        form.addRow(t("product_form.custom_fields"), self.custom_fields_editor)

        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #b00020;")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        form.addRow(self.error_label)

        button_row = QHBoxLayout()
        self.save_button = QPushButton(t("product_form.save"))
        self.save_button.clicked.connect(self._on_save_clicked)
        button_row.addWidget(self.save_button)

        self.cancel_button = QPushButton(t("product_form.cancel"))
        self.cancel_button.clicked.connect(self.cancelled.emit)
        button_row.addWidget(self.cancel_button)
        outer.addLayout(button_row)

        self._editing_id: Optional[int] = None

    def _on_sku_or_name_changed(self, _text: str):
        self.variation_table.set_parent_sku(self.sku_input.text().strip())

    def _on_attributes_changed(self):
        # Attribute names/values changing doesn't auto-regenerate variations
        # (that could silently discard entered data) -- the user clicks
        # "Generate Variations from Attributes" explicitly when ready.
        pass

    def load_product(self, product: Product):
        self._editing_id = product.id
        self.name_input.setText(product.name)
        self.sku_input.setText(product.sku)
        self.description_input.setPlainText(product.description)
        self.short_description_input.setPlainText(product.short_description)
        self.categories_input.setText(product.categories)
        self.tags_input.setText(product.tags)
        self.image_picker.set_value(product.image_path, product.image_alt, product.image_ref)
        self.gallery_editor.set_images(product.gallery)
        self.attribute_editor.set_attributes(product.attributes)
        self.variation_table.set_parent_sku(product.sku)
        self.variation_table.set_variations(product.variations, [a.name for a in product.attributes])
        self.custom_fields_editor.set_custom_fields(product.custom_fields)
        self.error_label.hide()

    def clear(self):
        self.load_product(Product(sku="", product_type="variable", name=""))
        self._editing_id = None

    def _build_product(self) -> Product:
        return Product(
            id=self._editing_id,
            sku=self.sku_input.text().strip(),
            product_type="variable",
            name=self.name_input.text().strip(),
            description=self.description_input.toPlainText(),
            short_description=self.short_description_input.toPlainText(),
            categories=self.categories_input.text().strip(),
            tags=self.tags_input.text().strip(),
            image_path=self.image_picker.get_local_path(),
            image_ref=self.image_picker.get_existing_ref(),
            image_alt=self.image_picker.get_alt(),
            gallery=self.gallery_editor.get_images(),
            attributes=self.attribute_editor.get_attributes(),
            variations=self.variation_table.get_variations(),
            custom_fields=self.custom_fields_editor.get_custom_fields(),
        )

    def _on_save_clicked(self):
        product = self._build_product()
        errors = product.validate()
        if errors:
            self.error_label.setText("\n".join(errors))
            self.error_label.show()
            return
        self.error_label.hide()
        self.saved.emit(product)
