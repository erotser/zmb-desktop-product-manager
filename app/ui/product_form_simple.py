"""Form for adding/editing a SIMPLE product."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ..i18n import t
from ..models import GalleryImage, Product
from .attribute_editor import AttributeEditorWidget
from .custom_fields_editor import CustomFieldsEditorWidget
from .image_picker import ImagePickerWidget


class GalleryEditorWidget(QWidget):
    """A simple list of ImagePickerWidgets for a product's gallery, with add/remove."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pickers: list[ImagePickerWidget] = []
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.pickers_container = QVBoxLayout()
        self.layout_.addLayout(self.pickers_container)

        add_button = QPushButton(t("product_form.add_gallery_image"))
        add_button.clicked.connect(lambda: self.add_slot())
        self.layout_.addWidget(add_button)

    def add_slot(self, path: Optional[str] = None, alt: str = "", ref: Optional[str] = None) -> ImagePickerWidget:
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)

        picker = ImagePickerWidget()
        picker.set_value(path, alt, ref)
        picker.changed.connect(self.changed.emit)
        row_layout.addWidget(picker)

        remove_button = QPushButton("✕")
        remove_button.setFixedWidth(28)
        remove_button.clicked.connect(lambda: self._remove(row_widget, picker))
        row_layout.addWidget(remove_button)

        self._pickers.append(picker)
        self.pickers_container.addWidget(row_widget)
        self.changed.emit()
        return picker

    def _remove(self, row_widget: QWidget, picker: ImagePickerWidget):
        self._pickers.remove(picker)
        self.pickers_container.removeWidget(row_widget)
        row_widget.deleteLater()
        self.changed.emit()

    def get_images(self) -> list[GalleryImage]:
        result = []
        for i, picker in enumerate(self._pickers):
            if picker.has_image():
                result.append(GalleryImage(
                    path=picker.get_local_path(), alt=picker.get_alt(),
                    position=i, image_ref=picker.get_existing_ref(),
                ))
        return result

    def set_images(self, images: list[GalleryImage]):
        while self._pickers:
            self._remove(self.pickers_container.itemAt(0).widget(), self._pickers[0])
        for img in images:
            self.add_slot(img.path, img.alt, img.image_ref)


class SimpleProductForm(QWidget):
    saved = Signal(object)   # emits the saved Product
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
        form.addRow(t("product_form.name"), self.name_input)

        self.sku_input = QLineEdit()
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

        self.price_input = QLineEdit()
        form.addRow(t("product_form.price"), self.price_input)

        self.sale_price_input = QLineEdit()
        form.addRow(t("product_form.sale_price"), self.sale_price_input)

        self.manage_stock_checkbox = QCheckBox(t("product_form.manage_stock"))
        form.addRow("", self.manage_stock_checkbox)

        self.stock_qty_input = QLineEdit()
        form.addRow(t("product_form.stock_quantity"), self.stock_qty_input)

        self.image_picker = ImagePickerWidget(label=t("product_form.main_image"))
        form.addRow(self.image_picker)

        self.gallery_editor = GalleryEditorWidget()
        form.addRow(t("product_form.gallery"), self.gallery_editor)

        self.attribute_editor = AttributeEditorWidget()
        form.addRow(t("product_form.attributes"), self.attribute_editor)

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

    def load_product(self, product: Product):
        self._editing_id = product.id
        self.name_input.setText(product.name)
        self.sku_input.setText(product.sku)
        self.description_input.setPlainText(product.description)
        self.short_description_input.setPlainText(product.short_description)
        self.categories_input.setText(product.categories)
        self.tags_input.setText(product.tags)
        self.price_input.setText(product.price)
        self.sale_price_input.setText(product.sale_price)
        self.manage_stock_checkbox.setChecked(product.manage_stock)
        self.stock_qty_input.setText(product.stock_qty)
        self.image_picker.set_value(product.image_path, product.image_alt, product.image_ref)
        self.gallery_editor.set_images(product.gallery)
        self.attribute_editor.set_attributes(product.attributes)
        self.custom_fields_editor.set_custom_fields(product.custom_fields)
        self.error_label.hide()

    def clear(self):
        self.load_product(Product(sku="", product_type="simple", name=""))
        self._editing_id = None

    def _build_product(self) -> Product:
        return Product(
            id=self._editing_id,
            sku=self.sku_input.text().strip(),
            product_type="simple",
            name=self.name_input.text().strip(),
            description=self.description_input.toPlainText(),
            short_description=self.short_description_input.toPlainText(),
            categories=self.categories_input.text().strip(),
            tags=self.tags_input.text().strip(),
            price=self.price_input.text().strip(),
            sale_price=self.sale_price_input.text().strip(),
            manage_stock=self.manage_stock_checkbox.isChecked(),
            stock_qty=self.stock_qty_input.text().strip(),
            image_path=self.image_picker.get_local_path(),
            image_ref=self.image_picker.get_existing_ref(),
            image_alt=self.image_picker.get_alt(),
            gallery=self.gallery_editor.get_images(),
            attributes=self.attribute_editor.get_attributes(),
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
