"""
A single image slot: shows a thumbnail (or a placeholder), a "Choose
Image..." button, and an alt-text field.

Distinguishes two states that matter for the "import, edit, re-export"
workflow:
  - A NEW local file the user just picked in this app (has a thumbnail,
    will be compressed/renamed on export).
  - An EXISTING reference from an earlier CSV import (a URL or filename
    already on the site) -- shown as text, not a thumbnail, since the app
    has no local copy of it to preview. Replacing it with a new local file
    overrides it; leaving it alone preserves it on export.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..i18n import t

THUMBNAIL_SIZE = 96
IMAGE_FILE_FILTER = "Images (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.gif)"


class ImagePickerWidget(QWidget):
    changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None, label: str = ""):
        super().__init__(parent)
        self._local_path: Optional[str] = None
        self._existing_ref: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if label:
            layout.addWidget(QLabel(label))

        row = QHBoxLayout()
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
        self.thumbnail_label.setStyleSheet("border: 1px solid #999; background: #f2f2f2;")
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        row.addWidget(self.thumbnail_label)

        col = QVBoxLayout()
        self.status_label = QLabel(t("image_picker.no_image"))
        self.status_label.setWordWrap(True)
        col.addWidget(self.status_label)

        button_row = QHBoxLayout()
        self.choose_button = QPushButton(t("product_form.choose_image"))
        self.choose_button.clicked.connect(self._on_choose_clicked)
        button_row.addWidget(self.choose_button)

        self.clear_button = QPushButton(t("common.clear"))
        self.clear_button.clicked.connect(self._on_clear_clicked)
        button_row.addWidget(self.clear_button)
        col.addLayout(button_row)

        self.alt_input = QLineEdit()
        self.alt_input.setPlaceholderText(t("product_form.image_alt"))
        self.alt_input.textChanged.connect(lambda _: self.changed.emit())
        col.addWidget(self.alt_input)

        row.addLayout(col)
        layout.addLayout(row)

        self._refresh_display()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def set_value(self, local_path: Optional[str], alt: str = "", existing_ref: Optional[str] = None):
        self._local_path = local_path
        self._existing_ref = existing_ref
        self.alt_input.setText(alt or "")
        self._refresh_display()

    def get_local_path(self) -> Optional[str]:
        return self._local_path

    def get_existing_ref(self) -> Optional[str]:
        return self._existing_ref

    def get_alt(self) -> str:
        return self.alt_input.text()

    def has_image(self) -> bool:
        return bool(self._local_path or self._existing_ref)

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _on_choose_clicked(self):
        path, _ = QFileDialog.getOpenFileName(self, t("product_form.choose_image"), "", IMAGE_FILE_FILTER)
        if path:
            self._local_path = path
            self._refresh_display()
            self.changed.emit()

    def _on_clear_clicked(self):
        self._local_path = None
        self._existing_ref = None
        self._refresh_display()
        self.changed.emit()

    def _refresh_display(self):
        if self._local_path and Path(self._local_path).exists():
            pixmap = QPixmap(self._local_path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    THUMBNAIL_SIZE, THUMBNAIL_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.thumbnail_label.setPixmap(pixmap)
            else:
                self.thumbnail_label.setText(t("image_picker.preview_unavailable"))
            self.status_label.setText(Path(self._local_path).name)
        elif self._existing_ref:
            self.thumbnail_label.clear()
            self.thumbnail_label.setText(t("image_picker.no_preview"))
            self.status_label.setText(t("image_picker.existing_image", ref=self._existing_ref))
        else:
            self.thumbnail_label.clear()
            self.thumbnail_label.setText(t("image_picker.no_preview"))
            self.status_label.setText(t("image_picker.no_image"))
